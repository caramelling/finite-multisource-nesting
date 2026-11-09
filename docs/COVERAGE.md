# Evidence and reproduction coverage

## Included study evidence

| Evidence | Inputs | Existing outputs | Execution/verification route |
|---|---|---|---|
| Formal main experiment | All 4,555 demands, 2,868 planned entities, controlled pools and rules | 100 complete per-bar/per-part plans plus metrics | Independent verifier; five opt-in scenario entry points; eight selected frozen computational modules |
| Standard method comparison | 27 cases with split/size metadata | Per-run results and BFD-relative metrics; 81 per-case method medians for plotting | BFD/GA/ALNS/ALNS+MILP adapter; input-load and import checks |
| Controlled small cases | 15 demand sets, selected finite entities and case-specific density references | 15 exact-model records and 450 search records, with per-case summaries | Exact/search adapter; archived certificate status and 360 optimal hits checked |
| Representative mechanism evidence | Main-instance inputs and public `E`/`Q` crosswalks | Seed-1 S3/S4 complete plans and comparison tables | Same 35 finite entities, 9 block changes, 28 part-set changes, 206 parts and 2.500 m purchase reduction cross-checked |
| Quantitative figures | 15 de-identified source CSVs | Data for Figures 2, 3, S1 and S2 | Portable Matplotlib script, all observations retained, PDF/SVG/PNG exports |
| Historical auxiliary studies | Three remnant pools; whitelisted archived parameter records | 68 configuration records, 67 available batch metric tables, five paired/component analysis tables | Archival evidence; metadata maps available snapshots to two distinct code bundles; not automatically rerun by the release CLI |
| Capacity relaxation reference | Recorded scalar model descriptors | Archived 1.817640 t relaxation reference and 1.937320 t exploratory upper record | Retained as an auxiliary record, not a formal S4 optimality certificate or an independently rebuilt solver model |

The released input sets comprise 11,557 distinct demand entities. Each retained demand's project/block membership, grade, cross-section and net length was matched with the frozen demand-unit table before replacing identity fields.

## Computational version boundaries

`src/profile_nesting_release/frozen/` is the selected implementation. Its eight source files preserve the original bytes; `metadata/frozen_code.json` records their SHA-256 hashes. New release files implement CSV loading, dry-run/opt-in execution, independent checks and portable plotting; they are not presented as frozen experimental drivers.

`archived_code/` retains available historical computational bundles byte-for-byte. `metadata/archived_code_index.json` links 62 auxiliary batch snapshots to two bundles; six batch records lack a complete computational source snapshot in the archive. Historical bundles are not silently substituted for the selected implementation, and the selected implementation is not claimed to recreate every historical variant.

The archived original database, storage/application drivers, user environment logs and all original identity mappings are deliberately excluded. Some unused original dispatch branches reference application modules outside the selected release; use only the documented entry points. Small-case selection inputs and density references are provided, but its original orchestration driver was not archived. The new small-search adapter uses the frozen configuration class defaults for unrecorded options (including its 90 s per-geometry default), while applying the archived total budget and local-MILP settings; exact reconstruction of every historical orchestration choice is not claimed.

## What was and was not rerun

Preparation ran input/identity checks, independent recalculation of archived main plans, module imports, dry-run loading, unit tests and quantitative figure regeneration. **No optimizer or new benchmark experiment was launched.** Standard/small and auxiliary result tables retain their existing values. Full small/standard per-piece historical output plans are not included; their input sets and per-run metrics are included. Formal main plans receive the exhaustive per-piece verification.

The archived main comparison table retains its existing exact-test statistics, Holm corrections and interval endpoints. The original inferential-analysis program and complete resampling settings were absent from the initial inspected archive but were subsequently recovered from the author's complete project. A separate source-level statistical audit reproduces all 23 historical artifact files and verifies saved-result pairing; the regret p-value difference is traced to floating-point tie splitting. See `docs/ORIGINAL_STATISTICS_CROSSCHECK.md` and `metadata/original_statistics_crosscheck.json`. The reported analysis remains the explicitly configured new reanalysis in `scripts/reproduce_statistics.py`, with settings in `configs/statistical_reanalysis.json` and outputs in `data/results/reanalysis_20261108/`. See `docs/STATISTICAL_REANALYSIS.md` for exact zero/tie handling, intervals, and comparison families. Historical tables and computational modules are not overwritten; the audit does not claim that all original project functions have been revalidated.

Wall-clock-limited stochastic reruns can differ across hardware, dependencies and identity-dependent tie breaks. Surrogates preserve lexicographic order within identifier domains to minimize ordering changes, but the verification environment differs from the historical solver environment. `metadata/environment.json` distinguishes those records. Reproducing historical evidence from saved plans is separate from generating a new optimization result.

## Scope of the engineering data

Demand and planned-stock attributes derive from the frozen engineering inputs. Remnant pools and substitution settings are controlled experimental resources/rules; they are not represented as complete operational yard inventory or universal material approval policy. No physical production trial, dynamic arrival simulation or new industrial deployment is added by packaging.
