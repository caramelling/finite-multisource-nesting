from dataclasses import asdict
from pathlib import Path
import argparse
import json

from .io import ROOT, demands_from_csv, read_csv, read_json, rules_from_csv, stocks_from_csv, write_csv


def load_job(family, case, scenario, algorithm, seed):
    inputs = ROOT / 'data' / 'inputs'
    if family == 'main':
        settings = read_json(ROOT / 'configs' / 'formal_scenarios.json')[scenario]
        if seed not in settings['seeds']:
            raise ValueError('Main experiment seed must be in the archived seed list.')
        demands = demands_from_csv(inputs / 'main' / 'demands.csv')
        stocks = stocks_from_csv(inputs / 'main' / 'planned_stock.csv')
        remnants = stocks_from_csv(inputs / 'main' / 'remnants_high.csv') if settings['use_remnants'] else []
        rules = rules_from_csv(inputs / 'main' / 'grade_rules.csv') if settings['use_substitution'] else {}
        label = scenario
    else:
        cases = {row['case_id']: row for row in read_csv(inputs / 'cases.csv')}
        if case not in cases or cases[case]['kind'] != family:
            raise ValueError('Choose a released case belonging to this family.')
        demands = demands_from_csv(inputs / family / case / 'demands.csv')
        remnants, rules = [], {}
        if family == 'standard':
            filename = 'standard_test.json' if cases[case]['split'] == 'TEST' else 'standard_development_validation.json'
            settings = read_json(ROOT / 'configs' / filename)
            settings['size_class'] = cases[case]['size_class']
            seed_key = 'large_seeds' if settings['size_class'] == 'LARGE' else 'medium_seeds'
            if seed not in settings[seed_key]:
                raise ValueError('Seed not present in the archived case configuration.')
            if algorithm not in ('BFD', *settings['algorithms']):
                raise ValueError('Unsupported standard algorithm.')
            stocks = []
        else:
            from .frozen.algorithms import StockUnit

            settings = read_json(ROOT / 'configs' / 'small_experiments.json')
            if seed not in settings['seeds']:
                raise ValueError('Small experiment seed must be in the archived seed list.')
            stocks = stocks_from_csv(inputs / 'small' / case / 'planned_stock.csv')
            references = read_json(ROOT / 'configs' / 'small' / (case + '.json'))['weight_references']
            for index, reference in enumerate(references):
                stocks.append(StockUnit('WEIGHT_REFERENCE_%03d' % index, 'WEIGHT_REFERENCE', reference['material'],
                                        reference['profile_type'], reference['specification'], 0.0,
                                        'WEIGHT_REFERENCE', reference['unit_weight_kg_per_m']))
        label = case + '_' + algorithm
    return {'family': family, 'label': label, 'seed': seed, 'settings': settings, 'demands': demands,
            'stocks': stocks, 'remnants': remnants, 'rules': rules, 'algorithm': algorithm, 'scenario': scenario}


def execute_job(job):
    from .frozen import algorithms, finite_exact, metaheuristics, true_multisource_alns
    from .frozen.multisource_alns import MultiSourceScenario
    from .frozen.validation import assert_valid_result

    settings = job['settings']
    lengths = settings['standard_lengths_mm']
    allowance = settings['boundary_allowance_mm']
    if job['family'] == 'main':
        config = true_multisource_alns.TrueMultiSourceAlnsConfig(
            seed=job['seed'], **{key: settings[key] for key in ('iterations_per_active_geometry', 'destroy_fraction',
            'max_removed', 'regret_k', 'with_local_milp', 'geometry_time_limit_seconds', 'total_time_limit_seconds')})
        scenario = MultiSourceScenario(job['scenario'], settings['use_remnants'], settings['use_substitution'],
                                      settings['joint_material_nesting'])
        result = true_multisource_alns.solve_true_multisource_alns(job['demands'], job['stocks'], job['remnants'],
                  lengths, allowance, job['rules'], scenario, config)
    elif job['family'] == 'small':
        if job['algorithm'] == 'EXACT':
            result = finite_exact.solve_resource_purchase_milp(job['demands'], job['stocks'], lengths, allowance,
                      time_limit_seconds=settings['milp_seconds_per_case'], threads=1)
        elif job['algorithm'] == 'SEARCH':
            config = true_multisource_alns.TrueMultiSourceAlnsConfig(seed=job['seed'],
                iterations_per_active_geometry=settings['alns_iterations_per_active_geometry'],
                destroy_fraction=settings['destroy_fraction'], max_removed=settings['max_removed'], regret_k=settings['regret_k'],
                with_local_milp=settings['local_milp_enabled'], total_time_limit_seconds=settings['alns_seconds_per_case'],
                local_milp_total_seconds=settings['local_milp_total_seconds'])
            result = true_multisource_alns.solve_true_multisource_alns(job['demands'], job['stocks'], [], lengths,
                      allowance, {}, MultiSourceScenario('SMALL', False, False, False), config)
        else:
            raise ValueError('Small cases support EXACT or SEARCH.')
    elif job['algorithm'] == 'BFD':
        result = algorithms.solve(job['demands'], 'BFD', lengths, allowance)
    else:
        config = metaheuristics.MetaheuristicConfig(seed=job['seed'], iterations=settings['iterations_by_algorithm'][job['algorithm']],
            population_size=settings['ga_population_size'], mutation_probability=settings['ga_mutation_probability'],
            alns_cooling_rate=settings['alns_cooling_rate'], milp_neighborhood_size=settings['alns_milp_max_group_parts'],
            milp_seconds_per_group=settings['alns_milp_seconds_per_group'], milp_max_groups=settings['alns_milp_max_groups_per_instance'],
            total_time_limit_seconds=settings['large_time_limit_seconds'] if settings['size_class'] == 'LARGE' else settings['medium_time_limit_seconds'])
        if job['algorithm'] == 'GA':
            result = metaheuristics.solve_genetic(job['demands'], lengths, allowance, config)
        else:
            result = metaheuristics.solve_alns(job['demands'], lengths, allowance, config, with_milp_repair=job['algorithm'] == 'ALNS_MILP')
    assert_valid_result(job['demands'], result, stock_units=job['stocks'] + job['remnants'],
                        standard_lengths_mm=lengths, substitution_rules=job['rules'], require_purchase_weight=job['family'] != 'standard')
    return result


def main():
    parser = argparse.ArgumentParser(description='Load archived inputs; optimization is opt-in through --execute.')
    parser.add_argument('--family', choices=('main', 'standard', 'small'), default='main')
    parser.add_argument('--scenario', choices=('S0', 'S1', 'S2', 'S3', 'S4'), default='S4')
    parser.add_argument('--case', default='')
    parser.add_argument('--algorithm', choices=('BFD', 'GA', 'ALNS', 'ALNS_MILP', 'EXACT', 'SEARCH'), default='ALNS')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs' / 'runs')
    args = parser.parse_args()
    if args.family == 'small' and args.algorithm not in ('EXACT', 'SEARCH'):
        parser.error('Small cases require --algorithm EXACT or SEARCH.')
    job = load_job(args.family, args.case, args.scenario, args.algorithm, args.seed)
    summary = {key: job[key] for key in ('family', 'label', 'seed', 'settings')}
    summary.update(demand_count=len(job['demands']), stock_rows=len(job['stocks']), remnant_rows=len(job['remnants']),
                   execute_requested=args.execute)
    print(json.dumps(summary, indent=2))
    if not args.execute:
        print('DRY RUN: inputs loaded; no optimizer called.')
        return
    result = execute_job(job)
    folder = args.output / (job['label'] + '_seed%02d' % args.seed)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'result.json').write_text(json.dumps(asdict(result), indent=2), encoding='utf-8')
    (folder / 'execution.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    write_csv(folder / 'assignments.csv', [{'bar_id': bar.bar_id, 'demand_id': demand.demand_id}
              for bar in result.bars for demand in bar.demands], ['bar_id', 'demand_id'])
    print('Validated new optimization output:', folder)


if __name__ == '__main__':
    main()
