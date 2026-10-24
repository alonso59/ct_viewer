# ADR-0036 Folder-per-case import, mask path templates and mask sets
Status: Accepted (owner 2026-10-23) · Date: 2026-10-23
Partially supersedes: ADR-0027 §3, only "the converter naming is the only pre-filled pattern".
Extends: ADR-0024 §2 (the `nifti-files` default stays one case per stem), ADR-0015 (the `imported` set).

**Context.** Public datasets often keep one folder per case with a fixed file name (`PanTS_00000001/ct.nii.gz`) and the labels in a parallel tree, sometimes as one binary file per structure (`LabelTr/{case}/segmentations/liver.nii.gz`). The `nifti-files` pattern saw only the file stem, so every `ct` became case `ct`, scan `01`: thousands of files silently collapsed into one item. The pattern suggester sampled only the top-level folder, and masks could be found only by fixed conventions next to the image.

**Decision.**
1. **A pattern with `/` matches the relative path without extension;** a pattern without `/` keeps matching the stem, so earlier imports reproduce (SRC-06). A generic folder pattern (case = the image's parent folder, scans numbered within it) is offered, not hidden: the wizard pre-fills it, visibly and editably, only when file names repeat across folders, as ADR-0027 §3 does for the converter naming.
2. **Files never collapse silently.** A preview where two images give the same `(case_id, scan_idx)` is refused with the cause and, when images sit in subfolders, the action to use the folder pattern (SRC-11).
3. **The suggester samples relative paths spread over the whole folder** (API-19 `sample`), not only its top level.
4. **`mask_template`**: an optional mask path relative to the root, built from the pattern's groups plus `{stem}` and `{dir}`. It names a file or a folder; files it names are masks, not items. It may not leave the root (R1 guard).
5. **A folder named by the template is a mask set**: one binary mask per structure. The import assigns one value per structure name across the whole import (sorted names → 1, 2, …) and stores it with the mask (`seg_labels` row field → `VolumeRef.labels`); the label map is seeded with those names. Readers (viewer, meshes, radiomics) get one label map composed on demand in a worker into the disposable `cache/maskset/` (PRJ-10); sources are never written (R1). Where structures overlap, the higher value wins.

**Consequences.**
- `nifti-files` adapter version 2. New QC-free refusal path for collisions; earlier silent `duplicate_row_identity` within one import no longer happens.
- `VolumeFormat` gains `nifti_dir`. A set's quick fingerprint uses member names, sizes and mtimes; full hashing (IMP-09) skips sets. External tasks receive a set as `{path: folder, format: "nifti_dir", labels}` (TASKS §Protocol).
- Owner changes: SOURCES (SRC-04, SRC-17), INPUT_METADATA (`seg_labels`), PROJECT_FORMAT (cache), API (API-19), TASKS (`job.json` masks).

**Rejected alternatives.**
- A per-dataset preset (PanTS, nnU-Net): hidden defaults, contrary to ADR-0024.
- A merge task writing a label map to the derived root: needs a runner and a manual step before the masks are visible.
- One segmentation set per structure: dozens of sets per project and per-set radiomics.
- Per-case values from each folder's sorted names: the same value would mean different structures in different cases.
