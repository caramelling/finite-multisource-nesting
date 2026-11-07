# Publication status and author checks

- [x] The author confirmed sole authorship and permission to publicly share the retained engineering demand/stock attributes and derived allocations. Direct identifiers have been replaced; the scientific attributes retain their recorded values.
- [ ] Select and add a **code license** and a separate **data license**. No reuse license has been granted yet; publicly accessible files and permission to reuse them are separate matters.
- [x] Record and verify the publicly accessible repository: https://github.com/caramelling/finite-multisource-nesting . Anonymous access has been verified.
- [ ] Fill the manuscript title, formal name of the sole author, citation details and contact route. Do not fabricate a publication DOI. Synchronize the manuscript access statement with the now-public repository.
- [ ] Align manuscript configuration statements with the actual archive: S3 uses 1,000 iterations in one stage, S4 uses 500 per stage; S0–S2 use 500. Preserve the recorded outcomes.
- [ ] Use the same de-identified block/project/case references in the submitted manuscript, tables, figures and public data. Check the author's private replacement map; never upload that map.
- [ ] Confirm the scope statement and distinguish frozen computational modules from the new CSV adapter and unavailable historical drivers.
- [ ] Review metadata, documentation and any future screenshots/logs before adding them. Do not copy original databases, identity mapping files, API configuration, keys or private preparation material.
- [x] Run `python scripts/verify_release.py` and the 10 unit tests on a fresh GitHub clone. Keep `.gitattributes` and the checksum manifest intact; no optimization rerun is needed for verification.
- [x] Publish only the reviewed payload, with no original identity mapping, raw database, credentials or private preparation material.
- [ ] After upload, replace the manuscript's prospective availability statement with the actual access URL and, if chosen, a verified archived-release identifier. Check that every promised file is accessible at that location.

The author authorized public sharing on 2026-11-07. Repository visibility and anonymous access were verified; code and data reuse license grants remain pending the author's selection. Current deposition/publication status is recorded in `metadata/publication_status.json`.
