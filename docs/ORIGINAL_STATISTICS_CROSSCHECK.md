# Original-source statistical cross-check

**English** | [简体中文](ORIGINAL_STATISTICS_CROSSCHECK_zh.md)

Completed on **9 November 2026** using the author-supplied complete original project. This is a source-level audit of statistical provenance and saved-result pairing, not a new optimization experiment or a claim that every project function has been revalidated.

## Execution and coverage

The original statistical function bodies were executed without alteration. Relative application imports were omitted, and the SQLite connector was replaced with read-only URI mode and `query_only=ON`. Results were written to a separate audit directory. The original runtime database and 70 computational source files retained their SHA-256 hashes.

- All **23** historical main, regret-ablation, development/validation, and test statistical artifact files were reproduced byte for byte, including their manifests.
- All **100** main S0–S4 outcomes matched the frozen database. Public CSV weights matched at the documented `10^-9 t` resolution; the maximum serialization discrepancy was `4.440892098500626e-16 t`.
- All **1,500** development/validation and **570** test run records matched at complete block/method/seed-result-signature level, including stock length, bar count, and runtime. All four-method block-median vectors also matched.
- The **20** regret-ablation paired records were identical to the public saved records, and the original configuration check accepted the `regret_k`-only variant difference.

The original test statistical artifact folder was not included in the frozen export. It is present in the complete project and was reproduced there; the saved test outcomes and reported statistics were already part of the released evidence. This distinction is retained in the audit metadata.

## Recovered historical settings

| Analysis | Bootstrap resamples | Historical seeds |
|---|---:|---|
| Main weight comparisons | 10,000 | `20260925 + comparison index` |
| Main purchase-count comparisons | 10,000 | `20261025 + comparison index` |
| Regret ablation | 10,000 | `20260926` |
| Standard-length method pairs | 10,000 | `20260923 + pair index` |

The main comparison order is S0–S1, S0–S2, S3–S4, S0–S4. Historical bootstrap sampling uses Python `random.Random` and linearly interpolated percentile endpoints. The original signed-rank implementation removes differences of magnitude at most `10^-12`, averages ties using strict floating-point equality, and computes the exact sign distribution with doubled-rank dynamic programming. Holm families agree with the documented analysis.

## Regret p-value diagnosis

The original function reproduces historical **p=0.8194255828857422** from unnormalized differences. Four nominally tied absolute-difference groups contain slightly unequal binary floating-point representations. Using the same original function with differences normalized to integer units of `10^-9 t` gives **p=0.8050556182861328**, exactly matching the new analysis. The positive rank sum changes from **111.5** to **112.0**. The median, interval, and non-significant interpretation remain unchanged.

The paper retains the declared **100,000-resample** reanalysis with base seed **20261108**, its precision normalization, and its documented comparison families. Historical tables are not overwritten.

## Computational version identity

All eight public frozen modules match original archived source snapshots. Current workspace versions of `algorithms.py`, `assignment_alns.py`, and `true_multisource_alns.py` differ: they make the reusable-remnant threshold configurable and propagate that setting. The other five selected modules match. No frozen module was replaced, and no result is attributed to the differing workspace code.

`metadata/original_statistics_crosscheck.json` records source hashes, archived-file matches, settings, and findings without private paths or identifiers. Its hash is included in the new analysis provenance. The original complete project, private mappings, and database credentials are not part of this research package. No GitHub push is performed by the audit or reanalysis scripts.
