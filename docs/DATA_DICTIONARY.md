# Data dictionary

All CSV files are UTF-8 with headers. Empty cells mean unavailable/not applicable, not zero. `metadata/file_inventory.csv` lists each CSV, row count and columns; `metadata/data_fields.csv` indexes distinct field names and their units/roles. These inventories complement the semantic definitions below.

## Identity and linkage

| Field/family | Meaning |
|---|---|
| `project_code`, `public_alias`, `project_id` | Surrogate project identifier `P` plus six digits; original names/codes are removed. |
| `block_name`, `block_id`, `block_s3`, `block_s4` | Surrogate block identifier `B` plus six digits. `ALL_MAIN_BLOCKS` denotes the aggregate main-instance run, not a physical block. |
| `demand_id` | Globally consistent surrogate part identifier `D` plus six digits. |
| `stock_unit_id` | Globally consistent finite-entity identifier `I` plus six digits; empty for new purchases. |
| `stock_id` | Group identifier `G` plus six digits for planned stock; remnant rows use their surrogate entity identifier. |
| `bar_id` | Per-run output bar identifier; meaningful only together with a run identifier. |
| `run_id`, `batch_id` | Main runs use `M_Sx_seed`; other archived runs use `R` plus six digits; batch records use `X` plus six digits. |
| `case_id` | `STD001`–`STD027` for standard comparisons and `SMALL001`–`SMALL015` for small controlled cases. |
| `pool_id` | `LOW`, `MEDIUM`, or `HIGH`, not the original UUID. |
| `paper_entity`, `entity_ref`, `paper_demand`, `demand_ref` | Existing paper aliases `E`, `P`, and `Q`; numeric suffixes are not original identifiers. |

`data/representative_entity_links.csv` maps the 35 existing `E` aliases to released entity IDs. `data/representative_demand_links.csv` maps the 206 `Q` aliases to released demand IDs. Purchased `P` aliases are scenario-local figure labels, not finite stock entities. Semicolon-separated `demand_refs` fields contain `Q` aliases. An entity's output bar number can change between runs; the entity identifier is the cross-run key.

## Inputs and plan columns

- `material` is the required grade in a demand/assignment row and the actual stock grade in a stock/bar row. `stock_material` explicitly records the actual grade on assignment/figure rows. Prefixes such as `ABS-` are retained where they occurred and normalized for compatibility checks.
- `profile_type` and `specification` identify cross-section geometry. `HP160*10`, `160*10.0` and equivalent forms are normalized to the same section; original spellings are retained.
- `net_length_mm` is part net length, or the sum of net part lengths on a bar. For a nonempty bar with `n` pieces, `allowance_length_mm = (n+1) × boundary_allowance_mm`, `used_length_mm = net_length_mm + allowance_length_mm`, and `remaining_length_mm = stock_length_mm − used_length_mm`.
- Lengths ending in `_mm` are millimetres; lengths ending in `_m` are metres. Density `unit_weight_kg_per_m` is kg/m. Nominal weights ending in `_t` are metric tonnes; nominal bar weight is `stock_length_mm × unit_weight_kg_per_m / 1,000,000`. These are length-density calculations, not new physical weighings.
- `source_type`/`stock_source_type`: **`PURCHASE` denotes existing finite planned stock**, not a new purchase in the optimization. `CONTROLLED_REMNANT` denotes an eligible controlled-remnant entity. `NEW_PURCHASE` denotes new stock selected from the purchasable length catalogue. In representative figure tables, `PLANNED` denotes existing planned stock.
- `is_additional_purchase`, `is_substitution`, `segment_changed`, `combination_changed` are 0/1 flags. `sequence_in_bar` is one-based cutting order.
- Same-grade use has zero penalty. Directional upgrades require a row in `grade_rules.csv`; each row specifies required grade, actual stock grade, profile type and dimensionless penalty. Reverse substitution is not implied.
- Blank remnant density is retained when neither an exact-grade nor geometry-level planned-stock reference exists, matching the frozen loading rule. No density is invented for unused geometries. Small-case zero-length `WEIGHT_REFERENCE` objects are created only by the adapter to supply the archived case-specific densities; they are not usable physical inventory.

## Metrics and statistics

- `purchase_*` / `additional_purchase_*` describe newly purchased bars only. `stock_length_m` in run metrics includes all used sources.
- Short residual waste is the sum of nonnegative per-bar residuals below 1,000 mm (numerical tolerance 1e-6 mm). Reusable tails have residuals at least that threshold. `reusable_tail_weight_proxy_t` is a nominal density-based proxy.
- Net utilization uses total net part length / total used-stock length. Occupied utilization includes boundary allowances in its numerator. Neither includes unused inventory.
- `substitution_count` counts upgraded parts; `substitution_length_m` sums their net lengths; `substitution_penalty` sums their rule penalties.
- `_median`, `_q1`, `_q3`, `_std` denote recorded marginal summaries. `difference_s3_minus_s4_t` is a within-seed procurement-weight difference, positive when S4 purchases less. A difference of marginal medians is not the median paired difference.
- Standard-comparison `saved_m`/`saved_vs_bfd_mm` compare stock length with the archived BFD baseline for the same case. `DEVELOPMENT_VALIDATION`/`HELDOUT` in plotting tables correspond to development/validation and the test split; input records keep their original split categories.
- `elapsed_ms`, `elapsed_s`, and `*_seconds` use their indicated units. Stored execution times are historical measurements, not reproduced performance measurements.
- `mip_gap` is a dimensionless solver gap; explicitly named `*_percent` fields use percent. P-values, Holm-adjusted P-values, rank-biserial correlations and penalties are dimensionless. `all_valid`/`is_valid` are archived validity flags; formal plans are additionally checked independently by this release.
- CI endpoints and inferential statistics are retained from archived analysis. Their original analysis driver and full interval-resampling settings are not present in this release; the verification program does not re-estimate them.

## Configurations, versions and integrity

`configs/formal_scenarios.json` contains the actual archived formal iteration/time settings. `formal_execution_settings.csv` retains per-run corroboration. `metadata/frozen_code.json` records unchanged selected module hashes; `metadata/archived_code_index.json` links auxiliary batches to available historical bundles. `metadata/checksums.json` covers every distributed payload file except itself. The adjacent ZIP checksum authenticates the archive bytes, including that manifest. Retain `.gitattributes` to prevent Git line-ending conversion from invalidating byte hashes.
