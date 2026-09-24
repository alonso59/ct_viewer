# ADR-0015 Segmentation sets per item
Status: Accepted · Date: 2026-09-24
Amends: DATA_MODEL §Item (`mask`), RAD-05, PRJ-07, VISION §In scope ("visualization only")

**Context.** An item has one `mask`. Segmentation tasks (nnU-Net, ADR-0016) add more, so an item can have the imported ground truth and several predictions. Radiomics must know which mask it used, and the viewer must show and compare them.

**Decision.**
1. **`Item.masks: {seg_id: VolumeRef}` replaces `Item.mask`.** `item_id` does not change.
2. **New entity `SegmentationSet`**, stored in `project.json.segmentations`:
   - `seg_id`: slug, e.g. `imported`, `nnunet-d820-3d`;
   - `kind`: `imported` | `task` (| `manual` later);
   - `producer`: `{task_id, version, run_id, settings_hash}`;
   - `label_mapping`: set values → project label values (PRJ-07);
   - `created_at`.
3. **Imported masks and the default.** Masks found at import form the set `imported`. `project.json.default_seg` is used when nothing is picked.
4. **Label mapping.** A task's labels (e.g. nnU-Net `dataset.json`) are matched by name when the set is registered. Unmatched values create `label_{value}` entries, flagged for review.
5. **Consumers.**
   - Viewer: a set selector and one overlay per set.
   - Radiomics: the selection requires `seg_id`, which is recorded in `run.json` (NFR-15).
   - QC: warnings are per set.
   - Curation: `seg_id` in mask decisions.
   - Mask files are still never edited in the app.
6. **Migration and compatibility.**
   - `format_version` 1 → 2 moves `mask` into `masks.imported` (PRJ-11, with a backup).
   - For one phase the API also returns `mask` = the default set (deprecated).

**Consequences.**
- \+ Ground truth and predictions live side by side with provenance.
- \+ Radiomics results are traceable to their mask.
- − Every mask consumer takes a `seg_id`.
- − A format migration.
- Owners: DATA_MODEL, PROJECT_FORMAT, RADIOMICS, VIEWER, CURATION, API.

**Rejected.**
- Replacing the mask in place: loses ground truth.
- One item per mask: duplicates identity, curation and variables.
