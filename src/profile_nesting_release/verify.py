from collections import Counter, defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import math
import re
import statistics

from .io import ROOT, read_csv, read_json


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, label, tolerance=1e-6):
    require(math.isclose(float(actual), float(expected), rel_tol=1e-9, abs_tol=tolerance),
            f'{label}: {actual} != {expected}')


def grade(value):
    return re.sub(r'^ABS[-/_]', '', value.upper().replace(' ', ''))


def section(value):
    return value.upper().replace('HP', '').replace(' ', '').replace('×', '*').replace('.0', '')


def geometry(row):
    return row['profile_type'].upper(), section(row['specification'])


def validate_plan(demands, stocks, bars, assignments, settings, rules):
    demand_index = {row['demand_id']: row for row in demands}
    stock_index = {row['stock_unit_id']: row for row in stocks}
    bar_index = {row['bar_id']: row for row in bars}
    require(len(demand_index) == len(demands), 'Duplicate input demand.')
    require(len(stock_index) == len(stocks), 'Duplicate input entity.')
    require(len(bar_index) == len(bars), 'Duplicate bar identifier.')
    seen = Counter(row['demand_id'] for row in assignments)
    require(set(seen) == set(demand_index) and all(count == 1 for count in seen.values()), 'Demand assignment is incomplete or duplicated.')
    by_bar = defaultdict(list)
    substitution_count, substitution_length, substitution_penalty = 0, 0.0, 0.0
    for assigned in assignments:
        require(assigned['bar_id'] in bar_index, 'Unknown assignment bar.')
        bar = bar_index[assigned['bar_id']]
        demand = demand_index[assigned['demand_id']]
        for column in ('project_code', 'block_name', 'material', 'profile_type', 'specification'):
            require(assigned[column] == demand[column], 'Assignment/input attribute mismatch: ' + column)
        close(assigned['net_length_mm'], demand['net_length_mm'], 'Demand length')
        require((assigned['project_code'], assigned['block_name']) == (bar['project_code'], bar['block_name']), 'Block isolation violated.')
        require(geometry(assigned) == geometry(bar), 'Section compatibility violated.')
        required_grade, actual_grade = grade(demand['material']), grade(bar['material'])
        changed = required_grade != actual_grade
        penalty = 0.0
        if changed:
            rule_key = (required_grade, actual_grade, bar['profile_type'].upper())
            require(settings['use_substitution'] and rule_key in rules, 'Grade substitution is not permitted.')
            penalty = rules[rule_key]
            substitution_count += 1
            substitution_length += float(demand['net_length_mm'])
            substitution_penalty += penalty
        require(int(assigned['is_substitution']) == int(changed), 'Substitution flag mismatch.')
        require(grade(assigned['stock_material']) == actual_grade, 'Stored stock grade mismatch.')
        close(assigned['substitution_penalty'], penalty, 'Substitution penalty')
        by_bar[assigned['bar_id']].append(assigned)
    used_entities = set()
    totals = Counter()
    for bar in bars:
        pieces = by_bar[bar['bar_id']]
        require(pieces, 'Empty output bar.')
        require(sorted(int(row['sequence_in_bar']) for row in pieces) == list(range(1, len(pieces) + 1)), 'Invalid cutting sequence.')
        close(len(pieces), bar['piece_count'], 'Piece count')
        length = float(bar['stock_length_mm'])
        net = sum(float(row['net_length_mm']) for row in pieces)
        allowance = (len(pieces) + 1) * settings['boundary_allowance_mm']
        remaining = length - net - allowance
        require(remaining >= -1e-6, 'Length capacity violated.')
        for column, value in (('net_length_mm', net), ('allowance_length_mm', allowance), ('used_length_mm', net + allowance), ('remaining_length_mm', remaining)):
            close(bar[column], value, column)
        purchased = int(bar['is_additional_purchase']) == 1
        entity = bar['stock_unit_id']
        if purchased:
            require(bar['stock_source_type'] == 'NEW_PURCHASE', 'New purchase source mismatch.')
            require(any(abs(length - value) < 1e-6 for value in settings['standard_lengths_mm']), 'Purchase outside length catalogue.')
            totals['purchase_count'] += 1
            totals['purchase_length_m'] += length / 1000
            totals['purchase_weight_t'] += length * float(bar['unit_weight_kg_per_m']) / 1e6
            require(not entity or entity not in stock_index, 'New purchase reuses a finite entity.')
        else:
            require(entity in stock_index and entity not in used_entities, 'Finite entity unknown or duplicated.')
            used_entities.add(entity)
            stock = stock_index[entity]
            close(length, stock['stock_length_mm'], 'Finite entity length')
            require(geometry(bar) == geometry(stock) and grade(bar['material']) == grade(stock['material']), 'Finite entity attributes changed.')
            require(bar['stock_source_type'] == stock['source_type'], 'Finite entity source mismatch.')
            if stock['unit_weight_kg_per_m']:
                close(bar['unit_weight_kg_per_m'], stock['unit_weight_kg_per_m'], 'Finite entity density')
            if bar['stock_source_type'] == 'CONTROLLED_REMNANT':
                require(settings['use_remnants'], 'Remnants forbidden in this scenario.')
                totals['controlled_remnant_count'] += 1
                totals['controlled_remnant_length_m'] += length / 1000
        if bar['unit_weight_kg_per_m']:
            close(bar['stock_weight_t'], length * float(bar['unit_weight_kg_per_m']) / 1e6, 'Bar nominal weight')
        residual = max(0, remaining)
        totals['stock_length_m'] += length / 1000
        totals['net_mm'] += net
        totals['used_mm'] += net + allowance
        if residual < 1000 - 1e-6:
            totals['waste_length_m'] += residual / 1000
        else:
            totals['reusable_tail_count'] += 1
            totals['reusable_tail_length_m'] += residual / 1000
            totals['reusable_tail_weight_proxy_t'] += residual * float(bar['unit_weight_kg_per_m'] or 0) / 1e6
    totals.update({'substitution_count': substitution_count, 'substitution_length_m': substitution_length / 1000,
                   'substitution_penalty': substitution_penalty, 'input_count': len(demands), 'unassigned_count': 0,
                   'unassigned_length_m': 0})
    totals['net_utilization'] = totals['net_mm'] / (totals['stock_length_m'] * 1000)
    totals['occupied_utilization'] = totals['used_mm'] / (totals['stock_length_m'] * 1000)
    return dict(totals)


def verify(root=ROOT):
    data = root / 'data'
    inputs = data / 'inputs' / 'main'
    demands = read_csv(inputs / 'demands.csv')
    planned = read_csv(inputs / 'planned_stock.csv')
    remnants = read_csv(inputs / 'remnants_high.csv')
    rules = {(grade(row['demand_material']), grade(row['stock_material']), row['profile_type']): float(row['penalty'])
             for row in read_csv(inputs / 'grade_rules.csv')}
    configs = read_json(root / 'configs' / 'formal_scenarios.json')
    require(len(demands) == 4555 and len({row['block_name'] for row in demands}) == 50, 'Main input counts changed.')
    require(len(planned) == 2868 and len(remnants) == 124, 'Main resource counts changed.')
    close(sum(float(row['stock_length_mm']) for row in remnants), 493194, 'HIGH pool total length')
    close(sum(float(row['stock_length_mm']) * float(row['unit_weight_kg_per_m']) / 1e6 for row in planned), 812.708320, 'Planned-stock weight')
    metrics = read_csv(data / 'results' / 'formal_run_metrics.csv')
    require(len(metrics) == 100, 'Expected 100 formal runs.')
    require(Counter(row['algorithm'][-2:] for row in metrics) == Counter({name: 20 for name in configs}), 'Scenario run counts changed.')
    summaries, checked_assignments, checked_bars = {}, 0, 0
    for record in metrics:
        scenario = record['algorithm'][-2:]
        folder = data / 'results' / 'formal_plans' / record['run_id']
        bars, assignments = read_csv(folder / 'bars.csv'), read_csv(folder / 'assignments.csv')
        totals = validate_plan(demands, planned + remnants, bars, assignments, configs[scenario], rules)
        for column, value in totals.items():
            if column in record:
                close(record[column], value, record['run_id'] + ':' + column)
        key = scenario, int(record['seed'])
        require(key not in summaries, 'Duplicate scenario/seed.')
        summaries[key] = totals
        checked_assignments += len(assignments)
        checked_bars += len(bars)
    require(set(summaries) == {(scenario, seed) for scenario in configs for seed in range(20)}, 'Missing scenario/seed.')
    differences = [summaries['S3', seed]['purchase_weight_t'] - summaries['S4', seed]['purchase_weight_t'] for seed in range(20)]
    signs = [sum(value > 1e-9 for value in differences), sum(abs(value) <= 1e-9 for value in differences), sum(value < -1e-9 for value in differences)]
    require(signs == [17, 2, 1], 'Paired procurement signs changed.')
    close(statistics.median(differences), 0.037400, 'Paired median procurement difference')
    for record in read_csv(data / 'figure_source' / 'multisource_paired_existing.csv'):
        seed = int(record['seed'])
        for scenario in configs:
            close(record['ASSIGNMENT_' + scenario], summaries[scenario, seed]['purchase_weight_t'], 'Figure source purchase')
        close(record['difference_s3_minus_s4_t'], differences[seed], 'Figure paired difference')
    for record in read_csv(data / 'figure_source' / 'multisource_summary_existing.csv'):
        source = [row for row in metrics if row['algorithm'][-2:] == record['scenario']]
        for column in record:
            if column.endswith('_median') and column[:-7] in source[0]:
                close(record[column], statistics.median(float(row[column[:-7]]) for row in source), 'Main scenario median:' + column)
    entity_table = read_csv(data / 'figure_source' / 'representative_hp160_entity_comparison.csv')
    require(len(entity_table) == 35, 'Representative entity count changed.')
    require(sum(int(row['segment_changed']) for row in entity_table) == 9, 'Representative block changes changed.')
    require(sum(int(row['combination_changed']) for row in entity_table) == 28, 'Representative combination changes changed.')
    rep = {}
    rep_entities = {}
    for scenario in ('S3', 'S4'):
        folder = data / 'results' / 'formal_plans' / ('M_' + scenario + '_01')
        bars = [row for row in read_csv(folder / 'bars.csv') if section(row['specification']) == '160*10']
        assignments = [row for row in read_csv(folder / 'assignments.csv') if section(row['specification']) == '160*10']
        existing = {row['stock_unit_id'] for row in bars if row['is_additional_purchase'] == '0'}
        purchases = [row for row in bars if row['is_additional_purchase'] == '1']
        require(len(assignments) == 206 and len(existing) == 35 and len(purchases) == 14, 'Representative case size changed.')
        close(sum(float(row['net_length_mm']) for row in assignments), 428648, 'Representative net length')
        rep[scenario] = existing, sum(float(row['stock_length_mm']) for row in purchases)
        rep_entities[scenario] = {row['stock_unit_id']: {'block': row['block_name'],
            'demands': {piece['demand_id'] for piece in assignments if piece['bar_id'] == row['bar_id']}}
            for row in bars if row['is_additional_purchase'] == '0'}
    require(rep['S3'][0] == rep['S4'][0], 'Representative existing-entity set changed.')
    close(rep['S3'][1], 135500, 'Representative S3 purchase length')
    close(rep['S4'][1], 133000, 'Representative S4 purchase length')
    require(sum(rep_entities['S3'][entity]['block'] != rep_entities['S4'][entity]['block'] for entity in rep['S3'][0]) == 9,
            'Plan-derived representative block changes mismatch.')
    require(sum(rep_entities['S3'][entity]['demands'] != rep_entities['S4'][entity]['demands'] for entity in rep['S3'][0]) == 28,
            'Plan-derived representative part-set changes mismatch.')
    entity_links = {row['paper_entity']: row['stock_entity_id'] for row in read_csv(data / 'representative_entity_links.csv')}
    demand_links = {row['paper_demand']: row['demand_id'] for row in read_csv(data / 'representative_demand_links.csv')}
    require(len(entity_links) == 35 and set(entity_links.values()) == rep['S3'][0], 'Paper/entity crosswalk mismatch.')
    require(len(demand_links) == 206, 'Paper/demand crosswalk mismatch.')
    for row in entity_table:
        for scenario in ('S3', 'S4'):
            actual = rep_entities[scenario][entity_links[row['entity_ref']]]
            require(row['block_' + scenario.lower()] == actual['block'], 'Paper entity/block link mismatch.')
            require({demand_links[alias] for alias in row['demand_refs_' + scenario.lower()].split(';') if alias} == actual['demands'],
                    'Paper entity/part-set link mismatch.')
    execution = read_csv(data / 'results' / 'formal_execution_settings.csv')
    require(len(execution) == 100, 'Execution settings missing.')
    for record in execution:
        expected = 1000 if record['scenario'] == 'S3' else 500
        close(record['iterations_per_active_geometry'], expected, 'Archived iteration budget')
        close(configs[record['scenario']]['iterations_per_active_geometry'], expected, 'Configured iteration budget')
    cases = read_csv(data / 'inputs' / 'cases.csv')
    require(Counter(row['kind'] for row in cases) == Counter(standard=27, small=15), 'Auxiliary case counts changed.')
    for case in cases:
        rows = read_csv(data / 'inputs' / case['kind'] / case['case_id'] / 'demands.csv')
        require(len(rows) == int(case['part_count']), 'Auxiliary case demand count mismatch.')
        require(all(row['project_code'] == case['project_id'] and row['block_name'] == case['block_id'] for row in rows), 'Auxiliary case identifiers inconsistent.')
    small = read_csv(data / 'results' / 'small_case_metrics.csv')
    require(len(small) == 15 and sum(int(row['alns_run_count']) for row in small) == 450, 'Small run counts changed.')
    require(sum(int(row['alns_optimal_hit_count']) for row in small) == 360, 'Small optimal-hit counts changed.')
    require(all(row['milp_status'] == 'OPTIMAL' and float(row['milp_mip_gap']) == 0 for row in small), 'Small exact certificate status changed.')
    small_runs = read_csv(data / 'results' / 'small_runs.csv')
    require(len(small_runs) == 465, 'Small per-run records missing.')
    plotted_small = {row['block_name']: row for row in read_csv(data / 'figure_source' / 'small_cases_existing.csv')}
    for case in small:
        source = [row for row in small_runs if row['block_name'] == case['block_name']]
        exact = [row for row in source if 'ALNS' not in row['algorithm']]
        search = [row for row in source if 'ALNS' in row['algorithm']]
        require(len(exact) == 1 and len(search) == 30, 'Small algorithm record counts mismatch.')
        require({int(row['random_seed']) for row in search} == set(range(30)), 'Small seed coverage mismatch.')
        require(all(row['is_valid'] == '1' and int(row['issue_count']) == 0 and int(row['unassigned_count']) == 0 for row in source),
                'Small archived validity flags inconsistent.')
        optimum = float(exact[0]['additional_purchase_weight_t'])
        close(case['milp_purchase_weight_t'], optimum, 'Small optimum cross-file')
        weights = [float(row['additional_purchase_weight_t']) for row in search]
        hits = sum(abs(value - optimum) <= 1e-8 for value in weights)
        close(case['alns_optimal_hit_count'], hits, 'Small optimal-hit arithmetic')
        close(case['alns_purchase_weight_t_best'], min(weights), 'Small best purchase')
        close(case['alns_purchase_weight_t_median'], statistics.median(weights), 'Small median purchase')
        gaps = [(value - optimum) / optimum * 100 if optimum else 0 for value in weights]
        close(plotted_small[case['block_name']]['max_gap_percent'], max(gaps), 'Small maximum gap')
        close(plotted_small[case['block_name']]['median_gap_percent'], statistics.median(gaps), 'Small median gap')
    standard_runs = read_csv(data / 'results' / 'standard_development_validation_runs.csv') + read_csv(data / 'results' / 'standard_test_runs.csv')
    grouped_standard = defaultdict(list)
    for row in standard_runs:
        require(row['is_valid'] == '1' and int(row['issue_count']) == 0 and int(row['unassigned_count']) == 0,
                'Standard archived validity flags inconsistent.')
        close(row['saved_vs_bfd_mm'], float(row['bfd_stock_mm']) - float(row['total_stock_length_mm']), 'Standard BFD-relative arithmetic')
        grouped_standard[row['project_code'], row['block_name'], row['algorithm'].replace('+', '_')].append(row)
    standard_medians = read_csv(data / 'figure_source' / 'standard_case_medians_existing.csv')
    require(len(standard_medians) == 81 and len(grouped_standard) == 81, 'Standard method/case coverage mismatch.')
    for row in standard_medians:
        source = grouped_standard[row['project_code'], row['block_name'], row['algorithm'].replace('+', '_')]
        expected_seeds = set(range(20 if source[0]['size_class'] == 'LARGE' else 30))
        require(len(source) == len(expected_seeds) and {int(item['random_seed']) for item in source} == expected_seeds,
                'Standard seed coverage mismatch.')
        for public_column, raw_column in (('stock_length_m', 'total_stock_length_mm'), ('elapsed_s', 'elapsed_ms'), ('saved_m', 'saved_vs_bfd_mm')):
            close(row[public_column], statistics.median(float(item[raw_column]) for item in source) / 1000, 'Standard case median:' + public_column)
    for relative, record in read_json(root / 'metadata' / 'frozen_code.json').items():
        require(hashlib.sha256((root / relative).read_bytes()).hexdigest() == record['sha256'], 'Frozen code hash mismatch: ' + relative)
    manifest = root / 'metadata' / 'checksums.json'
    if manifest.exists():
        for relative, record in read_json(manifest).items():
            content = (root / relative).read_bytes()
            require(len(content) == record['size_bytes'] and hashlib.sha256(content).hexdigest() == record['sha256'], 'Release file hash mismatch: ' + relative)
    return {'status': 'PASS', 'optimization_runs_launched': 0, 'main_runs_checked': len(metrics),
            'assignments_checked': checked_assignments, 'bars_checked': checked_bars,
            'main_parts': len(demands), 'main_blocks': 50, 'planned_stock_entities': 2868,
            'paired_lower_tied_higher': signs, 'paired_median_purchase_difference_t': statistics.median(differences),
            'representative_purchase_length_reduction_m': (rep['S3'][1] - rep['S4'][1]) / 1000,
            'representative_same_existing_entities': 35, 'standard_cases': 27, 'small_cases': 15,
            'small_search_runs': 450, 'small_optimal_hits': 360, 'frozen_modules_checked': 8,
            'small_run_records_checked': len(small_runs), 'standard_run_records_checked': len(standard_runs), 'standard_case_method_medians_checked': 81,
            'scope': 'Independent recalculation of archived plans and selected descriptive results; no optimization reruns or new inferential statistics.'}


def main():
    parser = argparse.ArgumentParser(description='Verify released archived evidence without running optimization.')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report = verify(args.root)
    print(json.dumps(report, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
