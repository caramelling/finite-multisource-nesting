import argparse
from collections import defaultdict
import csv
from decimal import Decimal, ROUND_HALF_EVEN
from itertools import combinations
import hashlib
import json
from pathlib import Path
import platform

import numpy as np
import scipy
from scipy.stats import friedmanchisquare


ROOT = Path(__file__).resolve().parents[2]
METHODS = ('BFD', 'GA', 'ALNS', 'ALNS_MILP')
COMPONENT_PAIRS = 'data/results/component_records/Abc2a82dfd79c_paired_seed_differences.csv'
COMPONENT_ARCHIVE = 'data/results/component_records/Aca6c6b12b99b_component_statistics.csv'


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def digest(path):
    content = path.read_bytes()
    return {'sha256': hashlib.sha256(content).hexdigest(), 'size_bytes': len(content)}


def to_units(value, resolution):
    decimal = Decimal(str(value))
    if not decimal.is_finite():
        raise ValueError('Non-finite observation')
    return int((decimal / Decimal(resolution)).to_integral_value(rounding=ROUND_HALF_EVEN))


def exact_signed_rank(differences):
    observations = [int(value) for value in differences]
    nonzero = [value for value in observations if value != 0]
    ordered = sorted(range(len(nonzero)), key=lambda index: abs(nonzero[index]))
    ranks_twice = [0] * len(nonzero)
    tied_groups = 0
    start = 0
    while start < len(ordered):
        stop = start + 1
        while stop < len(ordered) and abs(nonzero[ordered[stop]]) == abs(nonzero[ordered[start]]):
            stop += 1
        tied_groups += int(stop - start > 1)
        for position in range(start, stop):
            ranks_twice[ordered[position]] = start + 1 + stop
        start = stop
    positive_twice = sum(rank for value, rank in zip(nonzero, ranks_twice) if value > 0)
    total_twice = sum(ranks_twice)
    counts = {0: 1}
    for rank in ranks_twice:
        updated = dict(counts)
        for rank_sum, count in counts.items():
            updated[rank_sum + rank] = updated.get(rank_sum + rank, 0) + count
        counts = updated
    denominator = 2 ** len(nonzero)
    lower = sum(count for rank_sum, count in counts.items() if rank_sum <= positive_twice)
    upper = sum(count for rank_sum, count in counts.items() if rank_sum >= positive_twice)
    numerator = min(denominator, 2 * min(lower, upper))
    return {
        'paired_count': len(observations),
        'nonzero_pairs': len(nonzero),
        'zero_pairs': len(observations) - len(nonzero),
        'positive_pairs': sum(value > 0 for value in nonzero),
        'negative_pairs': sum(value < 0 for value in nonzero),
        'tied_absolute_difference_groups': tied_groups,
        'positive_rank_sum': positive_twice / 2,
        'negative_rank_sum': (total_twice - positive_twice) / 2,
        'statistic': min(positive_twice, total_twice - positive_twice) / 2,
        'p_numerator': numerator,
        'p_denominator': denominator,
        'pvalue': numerator / denominator,
    }


def holm_adjust(pvalues):
    if any(not np.isfinite(value) or not 0 <= value <= 1 for value in pvalues):
        raise ValueError('Invalid p-value in Holm family')
    adjusted = [0.0] * len(pvalues)
    previous = 0.0
    for position, index in enumerate(sorted(range(len(pvalues)), key=pvalues.__getitem__)):
        previous = max(previous, (len(pvalues) - position) * pvalues[index])
        adjusted[index] = min(1.0, previous)
    return adjusted


def bootstrap_indices(sample_size, settings, stream_id):
    sequence = np.random.SeedSequence([settings['bootstrap_seed'], stream_id])
    generator = np.random.Generator(np.random.PCG64(sequence))
    return generator.integers(0, sample_size, size=(settings['bootstrap_resamples'], sample_size), dtype=np.int64)


def summarize(differences, scale, indices, settings):
    observations = np.asarray(differences, dtype=np.int64)
    estimates = np.median(observations[indices], axis=1) * scale
    tail = (1 - settings['confidence_level']) / 2
    bounds = np.quantile(estimates, [tail, 1 - tail], method=settings['bootstrap_quantile_method'])
    return {
        'median_difference': float(np.median(observations) * scale),
        'ci95_low': float(bounds[0]),
        'ci95_high': float(bounds[1]),
        **exact_signed_rank(observations),
    }


def main_analysis(root, settings):
    rows = read_csv(root / 'data/results/formal_run_metrics.csv')
    grouped = defaultdict(dict)
    for row in rows:
        scenario = row['algorithm'].split('_')[-1]
        seed = int(row['seed'])
        if scenario not in ('S0', 'S1', 'S2', 'S3', 'S4') or seed in grouped[scenario]:
            raise ValueError('Unknown scenario or duplicate scenario/seed')
        if int(row['input_count']) != 4555 or int(row['unassigned_count']) != 0:
            raise ValueError('Incomplete formal main run')
        grouped[scenario][seed] = row
    expected = set(range(20))
    if set(grouped) != {'S0', 'S1', 'S2', 'S3', 'S4'} or any(set(group) != expected for group in grouped.values()):
        raise ValueError('Expected five scenarios with seeds 0 through 19')
    seeds = sorted(expected)
    indices = bootstrap_indices(len(seeds), settings, settings['bootstrap_stream_ids']['main'])
    resolution = settings['weight_resolution_t']
    comparisons = []
    paired = []
    for scenario_a, scenario_b in settings['main_comparisons']:
        weight_differences = []
        count_differences = []
        for seed in seeds:
            first, second = grouped[scenario_a][seed], grouped[scenario_b][seed]
            weight = to_units(first['purchase_weight_t'], resolution) - to_units(second['purchase_weight_t'], resolution)
            count = int(first['purchase_count']) - int(second['purchase_count'])
            weight_differences.append(weight)
            count_differences.append(count)
            paired.append({'comparison': scenario_a + '-' + scenario_b, 'seed': seed,
                           'weight_difference_t_a_minus_b': weight * float(resolution),
                           'count_difference_a_minus_b': count})
        weight = summarize(weight_differences, float(resolution), indices, settings)
        count = summarize(count_differences, 1.0, indices, settings)
        median_a = float(np.median([to_units(grouped[scenario_a][seed]['purchase_weight_t'], resolution) for seed in seeds]))
        median_b = float(np.median([to_units(grouped[scenario_b][seed]['purchase_weight_t'], resolution) for seed in seeds]))
        comparisons.append({'scenario_a': scenario_a, 'scenario_b': scenario_b,
                            'relative_difference_between_scenario_medians_percent': (median_a - median_b) / median_a * 100,
                            'weight': weight, 'purchase_count': count})
    for endpoint in ('weight', 'purchase_count'):
        for comparison, adjusted in zip(comparisons, holm_adjust([item[endpoint]['pvalue'] for item in comparisons])):
            comparison[endpoint]['holm_adjusted_p'] = adjusted
    archived = {(row['comparison'], int(row['seed'])): row for row in read_csv(root / 'data/results/archived_main_paired_differences.csv')}
    if len(archived) != len(paired):
        raise ValueError('Archived paired record count mismatch')
    for row in paired:
        old = archived[(row['comparison'], row['seed'])]
        if to_units(row['weight_difference_t_a_minus_b'], resolution) != to_units(old['weight_difference_t_a_minus_b'], resolution):
            raise ValueError('Archived paired weight differs from formal outcomes')
        if row['count_difference_a_minus_b'] != int(old['count_difference_a_minus_b']):
            raise ValueError('Archived paired purchase count differs from formal outcomes')
    return {'comparisons': comparisons, 'paired_records': paired,
            'bootstrap_index_sha256': hashlib.sha256(indices.astype('<i8', copy=False).tobytes()).hexdigest()}


def standard_analysis(root, split, settings):
    relative = 'data/results/standard_' + split + '_runs.csv'
    groups = defaultdict(lambda: defaultdict(list))
    baselines = {}
    identifiers = set()
    for row in read_csv(root / relative):
        key = (row['project_code'], row['block_name'])
        run_key = (key, row['algorithm'], int(row['random_seed']))
        if run_key in identifiers or row['algorithm'] not in METHODS[1:]:
            raise ValueError('Duplicate or unknown standard-comparison run')
        identifiers.add(run_key)
        if row['is_valid'] != '1' or int(row['unassigned_count']) != 0:
            raise ValueError('Invalid standard-comparison outcome')
        baseline = to_units(row['bfd_stock_mm'], settings['standard_stock_resolution_mm'])
        if key in baselines and baselines[key] != baseline:
            raise ValueError('BFD baseline changes within a block')
        baselines[key] = baseline
        groups[key][row['algorithm']].append(to_units(row['total_stock_length_mm'], settings['standard_stock_resolution_mm']))
    expected = 20 if split == 'development_validation' else 7
    if len(groups) != expected or any(set(group) != set(METHODS[1:]) for group in groups.values()):
        raise ValueError('Incomplete standard-comparison block/method groups')
    matrix = []
    medians = []
    for key in sorted(groups):
        values = [baselines[key], *[float(np.median(groups[key][method])) for method in METHODS[1:]]]
        matrix.append(values)
        for method, value in zip(METHODS, values):
            medians.append({'split': split, 'project_code': key[0], 'block_name': key[1],
                            'method': method, 'median_stock_length_mm': value,
                            'saving_vs_bfd_m': (values[0] - value) / 1000})
    matrix = np.asarray(matrix, dtype=float)
    result = friedmanchisquare(*matrix.T)
    pairwise = []
    for first, second in combinations(range(len(METHODS)), 2):
        differences_twice = np.rint(2 * (matrix[:, first] - matrix[:, second])).astype(np.int64)
        pairwise.append({'method_a': METHODS[first], 'method_b': METHODS[second],
                         'median_stock_reduction_m_a_minus_b': float(np.median(differences_twice) / 2000),
                         **exact_signed_rank(differences_twice)})
    for comparison, adjusted in zip(pairwise, holm_adjust([row['pvalue'] for row in pairwise])):
        comparison['holm_adjusted_p'] = adjusted
    return {'block_count': expected, 'run_count': len(identifiers), 'method_order': list(METHODS),
            'friedman_statistic': float(result.statistic), 'friedman_df': 3,
            'friedman_p': float(result.pvalue), 'pairwise': pairwise, 'block_medians': medians}


def component_analysis(root, settings):
    rows = read_csv(root / COMPONENT_PAIRS)
    if len(rows) != 20 or {int(row['seed']) for row in rows} != set(range(20)):
        raise ValueError('Expected 20 unique regret-ablation seeds')
    if {row['variant'] for row in rows} != {'REGRET_GREEDY'}:
        raise ValueError('Unknown component comparison')
    rows.sort(key=lambda row: int(row['seed']))
    differences = [to_units(row['purchase_weight_variant_minus_full_t'], settings['weight_resolution_t']) for row in rows]
    indices = bootstrap_indices(len(rows), settings, settings['bootstrap_stream_ids']['component'])
    result = summarize(differences, float(settings['weight_resolution_t']), indices, settings)
    return {'variant': 'REGRET_GREEDY', 'direction': 'variant minus full',
            'holm_family_size': 1, 'holm_adjusted_p': result['pvalue'], **result,
            'bootstrap_index_sha256': hashlib.sha256(indices.astype('<i8', copy=False).tobytes()).hexdigest()}


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def run_analysis(root, output, settings_path):
    settings = json.loads(settings_path.read_text(encoding='utf-8-sig'))
    if settings['bootstrap_resamples'] < 1 or not 0 < settings['confidence_level'] < 1:
        raise ValueError('Invalid bootstrap settings')
    if settings['bootstrap_interval'] != 'percentile' or settings['signed_rank_alternative'] != 'two-sided':
        raise ValueError('Unsupported analysis settings')
    supported = {'bootstrap_generator': 'PCG64',
                 'signed_rank_zeros': 'discard before ranking (wilcox)',
                 'signed_rank_ties': 'average ranks of equal absolute differences',
                 'standard_stock_resolution_mm': '1'}
    if any(settings[key] != value for key, value in supported.items()):
        raise ValueError('Unsupported rounding, zero, tie, or generator setting')
    if Decimal(settings['weight_resolution_t']) <= 0:
        raise ValueError('Weight resolution must be positive')
    main_result = main_analysis(root, settings)
    standard_results = {split: standard_analysis(root, split, settings) for split in ('development_validation', 'test')}
    component = component_analysis(root, settings)
    source_paths = ['data/results/formal_run_metrics.csv', 'data/results/archived_main_paired_differences.csv',
                    'data/results/archived_main_comparisons.csv',
                    'data/results/standard_development_validation_runs.csv', 'data/results/standard_test_runs.csv',
                    COMPONENT_PAIRS, COMPONENT_ARCHIVE]
    source_manifest = {relative: digest(root / relative) for relative in source_paths}
    crosscheck_relative = 'metadata/original_statistics_crosscheck.json'
    crosscheck_path = root / crosscheck_relative
    crosscheck = json.loads(crosscheck_path.read_text(encoding='utf-8')) if crosscheck_path.is_file() else {}
    provenance = {'settings': settings, 'settings_file': digest(settings_path),
                  'implementation_file': digest(Path(__file__)), 'sources': source_manifest,
                  'software': {'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy.__version__},
                  'optimization_runs_launched': 0,
                  'original_project_crosscheck_pending': crosscheck.get('status') != 'PASS',
                  'main_bootstrap_index_sha256': main_result['bootstrap_index_sha256']}
    if crosscheck:
        provenance['original_project_crosscheck'] = {
            'file': crosscheck_relative, **digest(crosscheck_path),
            'audit_date': crosscheck['audit_date'], 'scope': crosscheck['scope']}
    main_rows = []
    archive_rows = []
    archived = {(row['scenario_a'], row['scenario_b']): row for row in read_csv(root / 'data/results/archived_main_comparisons.csv')}
    for comparison in main_result['comparisons']:
        row = {'scenario_a': comparison['scenario_a'], 'scenario_b': comparison['scenario_b'],
               'relative_difference_between_scenario_medians_percent': comparison['relative_difference_between_scenario_medians_percent']}
        for endpoint in ('weight', 'purchase_count'):
            row.update({endpoint + '_' + key: value for key, value in comparison[endpoint].items()})
        main_rows.append(row)
        old = archived[(row['scenario_a'], row['scenario_b'])]
        for new_key, old_key in [('weight_median_difference', 'median_weight_reduction_t_a_minus_b'),
                                 ('weight_ci95_low', 'weight_ci95_low_t'), ('weight_ci95_high', 'weight_ci95_high_t'),
                                 ('weight_pvalue', 'weight_wilcoxon_exact_p'), ('weight_holm_adjusted_p', 'weight_holm_adjusted_p'),
                                 ('purchase_count_median_difference', 'median_count_reduction_a_minus_b'),
                                 ('purchase_count_ci95_low', 'count_ci95_low'), ('purchase_count_ci95_high', 'count_ci95_high'),
                                 ('purchase_count_pvalue', 'count_wilcoxon_exact_p'),
                                 ('purchase_count_holm_adjusted_p', 'count_holm_adjusted_p')]:
            archive_rows.append({'comparison': row['scenario_a'] + '-' + row['scenario_b'], 'quantity': new_key,
                                 'archived_value': float(old[old_key]), 'reanalysis_value': row[new_key],
                                 'reanalysis_minus_archive': row[new_key] - float(old[old_key])})
    old_component = read_csv(root / COMPONENT_ARCHIVE)[0]
    for new_key, old_key in [('median_difference', 'median_purchase_weight_delta_t'),
                             ('ci95_low', 'purchase_weight_ci95_low_t'), ('ci95_high', 'purchase_weight_ci95_high_t'),
                             ('pvalue', 'exact_wilcoxon_p'), ('holm_adjusted_p', 'holm_adjusted_p')]:
        archive_rows.append({'comparison': 'REGRET_GREEDY-full', 'quantity': new_key,
                             'archived_value': float(old_component[old_key]), 'reanalysis_value': component[new_key],
                             'reanalysis_minus_archive': component[new_key] - float(old_component[old_key])})
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / 'main_comparisons.csv', main_rows)
    write_csv(output / 'main_paired_differences.csv', main_result['paired_records'])
    write_csv(output / 'archive_comparison.csv', archive_rows)
    write_csv(output / 'standard_block_medians.csv', [row for result in standard_results.values() for row in result['block_medians']])
    write_csv(output / 'standard_pairwise.csv', [{'split': split, **row} for split, result in standard_results.items() for row in result['pairwise']])
    write_csv(output / 'regret_ablation.csv', [component])
    result = {'provenance': provenance, 'main': main_result['comparisons'],
              'standard': standard_results, 'regret_ablation': component}
    write_json(output / 'statistics.json', result)
    write_json(output / 'provenance.json', provenance)
    print(json.dumps({'status': 'PASS', 'main_comparisons': 4, 'standard_blocks': 27,
                      'regret_ablation_pairs': 20, 'optimization_runs_launched': 0}, ensure_ascii=False))
    return result


def main():
    parser = argparse.ArgumentParser(description='Reanalyse saved outcomes without importing or running an optimizer.')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/statistics')
    parser.add_argument('--settings', type=Path, default=ROOT / 'configs/statistical_reanalysis.json')
    args = parser.parse_args()
    run_analysis(ROOT, args.output.resolve(), args.settings.resolve())


if __name__ == '__main__':
    main()
