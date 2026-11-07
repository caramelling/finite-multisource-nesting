# De-identification procedure

## Public transformations

1. Project, block, demand, stock-group, physical-stock, batch, run and remnant-pool identifiers are replaced with consistent surrogate identifiers.
2. Surrogate assignment preserves lexicographic ordering within identifier domains where possible. The same physical resource retains the same public ID across scenarios and runs.
3. Free-text business-source fields, original entity origins, source-file references, private paths, database/application identifiers and timestamps are excluded unless a scientific output explicitly requires an elapsed duration.
4. Lengths, grades, cross-sections, quantities, nominal densities, seeds, actual algorithm budgets and recorded outcomes remain unchanged. Demand attributes are checked against the frozen demand-unit table. Selected frozen computational source bytes remain unchanged.
5. Public representative crosswalks connect already-surrogate paper `E`/`Q` aliases to release IDs; no original identifier is included in those crosswalks.
6. Structured identifier columns, original UUID patterns, absolute paths, common credential patterns and unexpected binary/oversized files are scanned before packaging. All payload files receive hashes. The archive allowlist excludes original databases, mappings, caches, private scripts and generated local outputs.

## Retained scientific attributes

The release retains cross-sectional geometry, detailed cutting lengths, grades, block groupings and allocation relationships because they support the scientific evidence. Their combination may be distinctive. This procedure removes direct identifiers; it is **not a proof of irreversible anonymization or immunity to linkage attacks**. Sharing permission and a qualified engineering-data review are required before public release. Removing or aggregating additional geometry/length fields would change the available reproduction scope and should be a documented author decision, not a silent numeric perturbation.

The original-to-surrogate mapping is kept privately by the author, outside the repository and ZIP. Do not upload private preparation folders or the original archive. Public Git history should start from the reviewed candidate, not from a private working repository that previously contained sensitive files. The release candidate contains no uploaded Git history.
