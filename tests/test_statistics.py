from fractions import Fraction
from itertools import product
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
try:
    statistics_module = importlib.import_module('profile_nesting_release.statistics')
except ModuleNotFoundError as error:
    if error.name not in ('numpy', 'scipy'):
        raise
    statistics_module = None


@unittest.skipIf(statistics_module is None, 'Install requirements-statistics.txt')
class StatisticsTests(unittest.TestCase):
    def test_signed_rank_matches_independent_brute_force(self):
        cases = ([1, 2, -3], [1, 1, -2, 0], [2, -2, 3, 3, -4], [0, 0, 0], [1, 1, 2, 0])
        for values in cases:
            nonzero = [value for value in values if value]
            absolute = sorted(abs(value) for value in nonzero)
            ranks = [sum(Fraction(position + 1) for position, item in enumerate(absolute) if item == abs(value))
                     / absolute.count(abs(value)) for value in nonzero]
            observed = sum(rank for rank, value in zip(ranks, nonzero) if value > 0)
            distribution = [sum(rank for rank, sign in zip(ranks, signs) if sign > 0)
                            for signs in product((-1, 1), repeat=len(nonzero))]
            lower = sum(value <= observed for value in distribution)
            upper = sum(value >= observed for value in distribution)
            expected = min(1, 2 * min(lower, upper) / len(distribution))
            with self.subTest(values=values):
                self.assertEqual(statistics_module.exact_signed_rank(values)['pvalue'], expected)

    def test_all_zero_and_all_positive(self):
        self.assertEqual(statistics_module.exact_signed_rank([0, 0])['pvalue'], 1)
        result = statistics_module.exact_signed_rank([1] * 20)
        self.assertEqual(result['pvalue'], 2 / 2 ** 20)
        self.assertEqual(result['tied_absolute_difference_groups'], 1)

    def test_decimal_normalization_avoids_artificial_ties(self):
        first = statistics_module.to_units('0.014960000000000084', '0.000000001')
        second = statistics_module.to_units('0.014959999999999862', '0.000000001')
        self.assertEqual(first, second)
        self.assertEqual(statistics_module.to_units('-0.0000000000000001', '0.000000001'), 0)
        with self.assertRaisesRegex(ValueError, 'Non-finite'):
            statistics_module.to_units('NaN', '0.000000001')

    def test_holm_separate_family(self):
        self.assertEqual(statistics_module.holm_adjust([0.03, 0.01, 0.04]), [0.06, 0.03, 0.06])
        with self.assertRaises(ValueError):
            statistics_module.holm_adjust([float('nan')])

    def test_seed_stream_is_deterministic(self):
        settings = json.loads((ROOT / 'configs/statistical_reanalysis.json').read_text(encoding='utf-8'))
        settings['bootstrap_resamples'] = 30
        first = statistics_module.bootstrap_indices(20, settings, 0)
        second = statistics_module.bootstrap_indices(20, settings, 0)
        other = statistics_module.bootstrap_indices(20, settings, 1)
        self.assertTrue((first == second).all())
        self.assertFalse((first == other).all())

    def test_full_reanalysis_is_deterministic_without_optimizer_imports(self):
        before = {name for name in sys.modules if name.startswith('profile_nesting_release.frozen')}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            settings = json.loads((ROOT / 'configs/statistical_reanalysis.json').read_text(encoding='utf-8'))
            settings['bootstrap_resamples'] = 200
            settings_path = directory / 'settings.json'
            settings_path.write_text(json.dumps(settings), encoding='utf-8')
            first = statistics_module.run_analysis(ROOT, directory / 'first', settings_path)
            statistics_module.run_analysis(ROOT, directory / 'second', settings_path)
            for path in (directory / 'first').iterdir():
                self.assertEqual(path.read_bytes(), (directory / 'second' / path.name).read_bytes())
            comparison = next(row for row in first['main'] if row['scenario_a'] == 'S3')
            self.assertAlmostEqual(comparison['weight']['median_difference'], 0.0374)
            self.assertEqual(comparison['weight']['positive_pairs'], 17)
            self.assertEqual(comparison['weight']['zero_pairs'], 2)
            self.assertEqual(comparison['weight']['negative_pairs'], 1)
            self.assertEqual(first['standard']['test']['block_count'], 7)
            self.assertFalse(first['provenance']['original_project_crosscheck_pending'])
            crosscheck_path = ROOT / 'metadata/original_statistics_crosscheck.json'
            self.assertEqual(first['provenance']['original_project_crosscheck']['sha256'],
                             statistics_module.digest(crosscheck_path)['sha256'])
        after = {name for name in sys.modules if name.startswith('profile_nesting_release.frozen')}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
