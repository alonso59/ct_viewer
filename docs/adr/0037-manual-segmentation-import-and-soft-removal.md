# ADR-0037 Manual segmentation import and soft removal
Status: Accepted (§5 management location superseded by ADR-0038; owner 2026-10-26) · Date: 2026-10-26
Extends: ADR-0015 (segmentation sets), ADR-0036 (mask-set folders).

**Context.** Projects can receive imported masks with images and task-produced masks, but a
curator cannot attach an existing segmentation set after the image import. Public datasets use
both one multi-label NIfTI per item and one binary NIfTI per structure. Curators also need to
remove a set from the Layers panel without deleting source files, then restore or reimport it.

**Decision.**
1. A manual segmentation import names a project source folder (or one NIfTI for the active
   item) and an item path template using `case_id`, `scan_idx`, `item_id`, `side` or `scope`.
   A resolved path is either one multi-label `.nii[.gz]` or a folder of binary NIfTIs; one import
   cannot mix the two forms.
2. Header checks and combined-label discovery run as an Index job. Only masks whose shape and
   affine match their image are registered. Source files are opened read-only and never copied,
   changed or deleted.
3. The API writes an immutable alias-reference manifest and report under
   `segmentations/imports/{artifact_id}/`. A `manual` `SegmentationSet` points to the artifact;
   derived index rebuilds rejoin it like task-produced masks.
4. Removing a set is soft: `active=false` hides it from selectors and consumers but retains the
   set, manifest, source references and provenance. Restore flips it active. Reimporting the same
   ID is allowed only after removal and creates a new immutable artifact.
5. The Layers panel owns Import, Reindex, Remove/Restore and one select/deselect-all checkbox for
   label visibility. These controls are absent from view-only links.

**Consequences.** Source immutability is preserved, combined masks remain the preferred compact
form, binary folders keep their structure names, and accidental removal is reversible. The
source files must already be under a source alias registered in the project.
