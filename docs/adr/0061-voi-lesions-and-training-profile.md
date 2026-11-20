# ADR-0061 The VOI extractor measures lesions and writes the training contract
Status: Accepted · Date: 2026-11-20 (owner decision, same date)
Extends: ADR-0050 (VOI extractor), ADR-0060 (analysis tables).

**Context.** New datasets go ct_viewer → `voi.extract` → patch-based training (autoencoders, JEPA) with a lesion-centric sampler.
The sampler needs a lesion catalog (`mask_path`, `centroid_vox`, `bbox_size_vox`, `size_bin`), a sampling profile (size bins, empirical and target bin probabilities, patch budgets and role priors per bin) and a dataset fingerprint (spacing, HU normalization).
Today only the research pipeline writes them, from `.npy` VOIs, with spacing from its config. Its budgets and priors are keyed `tiny…huge` while its bins are named `bin_N`, so every bin gets the same defaults.
`voi.extract` records only organ-level sizes (`volume_ml`, `label_ml`); it holds the written crop in memory just before saving it.
On 2026-11-20 the owner asked for this inside the VOI extractor, not as a separate plugin, with the profile set in Settings and tunable after the run.

**Decision.**
1. `voi.extract` measures lesions on the **written** crop grid (after `resample_mm`), so voxel indices match the files training loads and millimetres come from the header.
   A lesion is a 26-connected component of the lesion labels (default: the region's `protect` labels), at least `min_voxels`; contact and overlap are measured against the region's organ labels; HU statistics come from the image crop.
   Lesions are numbered by volume, largest first.
2. Measurement is fixed at extraction; the **sampling profile is a pure function** of the measured lesions and profile settings (bin percentiles, balancing α, budgets and role priors per bin, HU window, patch size candidates).
   The run writes it with its own settings; Show results recomputes it from `lesion_catalog.jsonl` without reading volumes and saves named variants in the project folder.
3. At the end of a run, from the whole `voi_catalog.jsonl` (so resume is correct), the task writes into its `output_dir`: `lesion_catalog.jsonl`, `sampling_profile.json` (schema 2, a superset of the research schema 1) and `dataset_fingerprint.json` (research schema 3).
   Dataset HU percentiles come from per-VOI foreground histograms (1 HU bins) kept as JSON sidecars next to each crop, so they are exact and resumable.
4. The task also emits the analysis table `lesions` (grain `instance`): `item_id` is the source scan, `side` the VOI's side, `label` the lesion label's project value, so variables, phase, curation and click-through work without importing the crops.
5. Budgets and priors are keyed by the bins actually produced (`b0…bN`, smallest first), each bin with a readable bound.

**Consequences.** The measurement is a port of the research `_compute_lesion_entries`, held equal by a parity test on Dataset421 (plugins cannot import the research repository, as in ADR-0059).
`voi.extract` becomes 1.1.0 and declares `outputs: ["images", "tables"]`; runs without a lesion label still crop and write no lesion files.
The backend imports `plugins/voi/profile.py` lazily for recomputation, the same exception it already makes for `engine.py`.
The research repository gains a loader for this layout (NIfTI paths from `voi_catalog.jsonl`) and reads schema 2; its own bin bug is fixed for older datasets.

**Rejected alternatives.**
A separate `lesions` plugin or task (a second pass re-reads every crop and splits one reviewed extraction into two runs).
Measuring on the source scan grid (voxel indices would not match the files training reads).
Profile settings fixed per run only (every bin or α change would re-crop the dataset).
Percentiles from per-VOI quantiles (cannot be merged exactly across VOIs or a resumed run).
