# Author checks before public release

- [ ] Obtain explicit rights-holder permission to publish the retained engineering demand/stock attributes and derived allocations; review possible inference from length/geometry combinations.
- [ ] Select and add a **code license** and a separate **data license**, consistent with ownership and any institutional or industrial agreement. No license has been assigned by this candidate.
- [x] Record the actual repository URL in the repository metadata: https://github.com/caramelling/finite-multisource-nesting . The repository currently remains private; this is not evidence of public availability.
- [ ] Fill the manuscript title, authors, citation details and contact route. Do not fabricate a publication DOI. Synchronize the manuscript access statement with the repository's actual visibility when the public-release decision is made.
- [ ] Align manuscript configuration statements with the actual archive: S3 uses 1,000 iterations in one stage, S4 uses 500 per stage; S0–S2 use 500. Preserve the recorded outcomes.
- [ ] Use the same de-identified block/project/case references in the submitted manuscript, tables, figures and public data. Check the author's private replacement map; never upload that map.
- [ ] Confirm the scope statement and distinguish frozen computational modules from the new CSV adapter and unavailable historical drivers.
- [ ] Review metadata, documentation and any future screenshots/logs before adding them. Do not copy original databases, identity mapping files, API configuration, keys or private preparation material.
- [ ] Run `python scripts/verify_release.py` on a fresh unpacked checkout; keep `.gitattributes` and the checksum manifest intact. No optimization rerun is needed for this step.
- [ ] Check the repository's privacy setting and the target journal's review workflow before making it public. Use only the reviewed payload when uploading; do not upload the enclosing preparation folder.
- [ ] After upload, replace the manuscript's prospective availability statement with the actual access URL and, if chosen, a verified archived-release identifier. Check that every promised file is accessible at that location.

This checklist does not claim that files are publicly accessible or that public-distribution authorization has been granted. The user authorized upload to this private repository, not a change of visibility or a license grant. Current deposition/publication status is recorded in `metadata/publication_status.json`.
