from copy import deepcopy
from pathlib import Path
import importlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from profile_nesting_release.io import ROOT, read_csv, read_json
from profile_nesting_release.run import execute_job, load_job, main
from profile_nesting_release.verify import validate_plan


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = ROOT / 'data' / 'results' / 'formal_plans' / 'M_S4_01'
        cls.bar = read_csv(folder / 'bars.csv')[0]
        cls.assignments = [row for row in read_csv(folder / 'assignments.csv') if row['bar_id'] == cls.bar['bar_id']]
        identifiers = {row['demand_id'] for row in cls.assignments}
        cls.demands = [row for row in read_csv(ROOT / 'data' / 'inputs' / 'main' / 'demands.csv') if row['demand_id'] in identifiers]
        cls.stocks = [row for row in read_csv(ROOT / 'data' / 'inputs' / 'main' / 'planned_stock.csv') if row['stock_unit_id'] == cls.bar['stock_unit_id']]
        cls.settings = read_json(ROOT / 'configs' / 'formal_scenarios.json')['S4']

    def test_frozen_modules_import(self):
        for module in read_json(ROOT / 'metadata' / 'frozen_code.json'):
            importlib.import_module('profile_nesting_release.frozen.' + Path(module).stem)

    def test_actual_bar_passes(self):
        totals = validate_plan(self.demands, self.stocks, [self.bar], self.assignments, self.settings, {})
        self.assertEqual(totals['input_count'], len(self.demands))

    def test_duplicate_assignment_rejected(self):
        with self.assertRaisesRegex(ValueError, 'incomplete or duplicated'):
            validate_plan(self.demands, self.stocks, [self.bar], self.assignments + [self.assignments[0]], self.settings, {})

    def test_insufficient_capacity_rejected(self):
        revised = deepcopy(self.bar)
        revised['stock_length_mm'] = '1'
        with self.assertRaisesRegex(ValueError, 'capacity'):
            validate_plan(self.demands, self.stocks, [revised], self.assignments, self.settings, {})

    def test_main_inputs_load_without_optimization(self):
        for scenario in ('S0', 'S1', 'S2', 'S3', 'S4'):
            job = load_job('main', '', scenario, 'ALNS', 1)
            self.assertEqual(len(job['demands']), 4555)
        self.assertEqual(load_job('main', '', 'S3', 'ALNS', 1)['settings']['iterations_per_active_geometry'], 1000)

    def test_all_auxiliary_inputs_load_without_optimization(self):
        for case in read_csv(ROOT / 'data' / 'inputs' / 'cases.csv'):
            algorithm = 'SEARCH' if case['kind'] == 'small' else 'ALNS'
            job = load_job(case['kind'], case['case_id'], 'S4', algorithm, 1)
            self.assertEqual(len(job['demands']), int(case['part_count']))

    def test_default_cli_never_calls_optimizer(self):
        with patch('sys.argv', ['run_experiment.py']), patch('profile_nesting_release.run.execute_job') as execute:
            main()
            execute.assert_not_called()

    def test_unknown_case_rejected(self):
        with self.assertRaisesRegex(ValueError, 'released case'):
            load_job('small', 'UNKNOWN', 'S4', 'SEARCH', 1)

    def test_main_dispatch_without_solver_execution(self):
        with patch('profile_nesting_release.frozen.true_multisource_alns.solve_true_multisource_alns') as solver, \
             patch('profile_nesting_release.frozen.validation.assert_valid_result'):
            for scenario in ('S0', 'S1', 'S2', 'S3', 'S4'):
                execute_job(load_job('main', '', scenario, 'ALNS', 1))
                arguments = solver.call_args.args
                self.assertEqual(arguments[-2].joint_material_nesting, scenario == 'S4')
                self.assertEqual(arguments[-1].iterations_per_active_geometry, 1000 if scenario == 'S3' else 500)
                self.assertFalse(arguments[-1].with_local_milp)
            self.assertEqual(solver.call_count, 5)

    def test_auxiliary_dispatch_without_solver_execution(self):
        with patch('profile_nesting_release.frozen.algorithms.solve') as bfd, \
             patch('profile_nesting_release.frozen.metaheuristics.solve_genetic') as genetic, \
             patch('profile_nesting_release.frozen.metaheuristics.solve_alns') as alns, \
             patch('profile_nesting_release.frozen.finite_exact.solve_resource_purchase_milp') as exact, \
             patch('profile_nesting_release.frozen.true_multisource_alns.solve_true_multisource_alns') as small, \
             patch('profile_nesting_release.frozen.validation.assert_valid_result'):
            for algorithm in ('BFD', 'GA', 'ALNS', 'ALNS_MILP'):
                execute_job(load_job('standard', 'STD001', 'S4', algorithm, 1))
            self.assertEqual(bfd.call_count, 1)
            self.assertEqual(genetic.call_count, 1)
            self.assertEqual(alns.call_count, 2)
            self.assertTrue(alns.call_args.kwargs['with_milp_repair'])
            for algorithm in ('EXACT', 'SEARCH'):
                execute_job(load_job('small', 'SMALL001', 'S4', algorithm, 1))
            self.assertEqual(exact.call_args.kwargs['threads'], 1)
            self.assertTrue(small.call_args.args[-1].with_local_milp)
            self.assertEqual(small.call_args.args[-1].geometry_time_limit_seconds, 90)


if __name__ == '__main__':
    unittest.main()
