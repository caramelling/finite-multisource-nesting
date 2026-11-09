# Reproducible statistical reanalysis

**English** | [简体中文](STATISTICAL_REANALYSIS_zh.md)

This is a new, explicitly configured analysis of saved computational outcomes, not a recovered copy of the historical inferential-analysis program. It runs no optimization. Original input records, saved plans, frozen computational modules, and archived statistical tables remain unchanged.

## Reproduce

From the repository root, install `requirements-statistics.txt` and run:

```bash
python scripts/reproduce_statistics.py --output outputs/statistics
python -m unittest discover -s tests -p test_statistics.py -v
```

The recorded results are in `data/results/reanalysis_20261108/`. The command regenerates the same eight output files. `configs/statistical_reanalysis.json` fixes all analysis settings. `provenance.json` records input/configuration/implementation SHA-256 hashes and Python, NumPy, and SciPy versions. It contains no private filesystem paths. The script imports no optimizer.

## Units and analysis choices

- **Main instance:** all 100 saved S0–S4 outcomes are paired by the same 20 seeds. Differences are A minus B, so positive differences indicate lower procurement in B. The four comparisons are S0–S1, S0–S2, S3–S4, and S0–S4. These are stochastic runs on one fixed ship problem, not 20 independent ships.
- **Numeric normalization:** purchase weights are converted to integer units of `0.000000001 t` using decimal half-even rounding before subtraction. This removes floating-point noise without changing scientifically reported procurement values. Standard stock lengths use integer millimetres; even-sized seed medians may be half-millimetres and use doubled integers for ranking.
- **Intervals:** 100,000 paired percentile-bootstrap samples, 95% coverage level, linear-interpolated 2.5th/97.5th percentiles. Complete main seed rows are resampled with replacement, preserving scenario/end-point pairing. The generator is PCG64 initialized with `SeedSequence([20261108, 0])`. The regret comparison uses `SeedSequence([20261108, 1])`. Intervals are pointwise, not simultaneous multiplicity-adjusted intervals.
- **Signed-rank tests:** two-sided; discard zero differences before ranking; average ranks for equal absolute differences. The null is a difference distribution symmetric about zero. The exact conditional distribution includes every sign assignment to the nonzero ranks. Doubled average ranks permit integer dynamic programming, including ties. The two-sided p value is twice the smaller inclusive tail probability, capped at 1. An all-zero difference set returns p=1.
- **Multiplicity:** four main weight tests and four main purchase-count tests are separate Holm families. Each standard-comparison split has its own six-pair family. The regret ablation is one comparison. All comparisons are retained, regardless of significance.
- **Standard-length comparisons:** aggregate seeds to the median stock length within each block/method before tests. The two sets contain 20 development/validation blocks and 7 test-split blocks. The Friedman test uses a tie-corrected chi-square reference with 3 degrees of freedom. Block dependence within ships bounds the interpretation; these results are not relabelled as independent-ship validation.

## Relation to the archive

The main S3–S4 result remains a paired median reduction of **0.037400 t**, pointwise 95% CI **0.029920–0.078540 t**, and Holm-adjusted **p=0.0000152587890625**. Its 17 lower / 2 tied / 1 higher outcomes are unchanged. The representative 2.500 m procurement reduction is a saved allocation result, not a bootstrap estimate.

The regret-1 versus regret-2 comparison gives **p=0.8050556182861328**, compared with the archived **0.8194255828857422**. Its median difference, interval, and non-significant interpretation are unchanged. The original-source cross-check on 9 November 2026 identifies the cause: direct binary floating-point subtraction split four nominally tied absolute-difference groups. Applying the original exact-test function to integer-normalized differences reproduces the new p value; the positive rank sum changes from 111.5 to 112.0. `archive_comparison.csv` retains both versions, including all main weight and purchase-count comparisons. Tiny endpoint display differences reflect decimal rounding rather than new optimization outcomes.

An independent local check uses SciPy's exhaustive-permutation signed-rank calculation for S3–S4 and the regret comparison, and SciPy's percentile bootstrap for the four main weight intervals. The new code also includes brute-force small-case rank-distribution tests and deterministic-output tests.

The separate original-source cross-check is complete within the statistical provenance and pairing scope. It reproduces all 23 historical artifact files, verifies 100 main outcomes and 2,070 standard-comparison run records, and matches all eight public frozen modules to original archived snapshots. Three current workspace modules differ from those snapshots; the frozen release is deliberately retained. See [the audit report](ORIGINAL_STATISTICS_CROSSCHECK.md) and `metadata/original_statistics_crosscheck.json`. The reported analysis remains the explicitly configured new reanalysis, not a silent substitution of historical settings. No optimization or automatic network publication occurs.

## Output fields

- `main_comparisons.csv`: four comparisons, effect medians, pointwise intervals, positive/negative/zero counts, rank sums, exact p-value numerators/denominators, and endpoint-specific Holm-adjusted p values. `weight_*` values for effects/intervals use tonnes; `purchase_count_*` effects/intervals use bars.
- `main_paired_differences.csv`: 80 normalized paired records, 20 per comparison.
- `standard_block_medians.csv` and `standard_pairwise.csv`: block/method aggregation and six-pair tests per split.
- `regret_ablation.csv`: 20-seed variant-minus-full weight analysis in tonnes.
- `archive_comparison.csv`: archived value, new value, and signed new-minus-old difference.
- `statistics.json` and `provenance.json`: structured results, settings, versions, and hashes.

Methods are documented against the SciPy `wilcoxon` and `bootstrap` API documentation and NumPy `SeedSequence` documentation; the executable implementation and pinned dependencies define this release's exact calculations.
