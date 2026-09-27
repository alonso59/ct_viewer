# Glossary

Scope: terms used across docs.
Read when: a term is unclear.
Depends: none (terms point to their owning docs by ID).

| Term | Meaning |
|---|---|
| Workspace | Server directory (`WORKSPACE_ROOT`) holding all projects |
| Project | Folder with `project.json`, index, curation and radiomics state; references data by alias |
| Path alias / root | `ALIAS:rel/path` reference; the alias maps to an absolute root directory |
| Relink | Changing an alias root when data moves (QuPath "update URIs") |
| Source root / derived root | Alias role: `source` is read-only input; `derived` receives task outputs (ADR-0014) |
| Adapter | Turns a source (metadata-v1, NIfTI files, DICOM via the converter) into contract v1 rows (SRC-*) |
| Open mode | Viewing a file or folder without a project (SRC-09) |
| Identity policy | How `case_id` / `scan_idx` are assigned and kept stable (SRC-07) |
| Segmentation set | One named set of masks per project (imported, or produced by a task), `seg_id` (ADR-0015) |
| Task | A manifest-described job over a selection with typed outputs (TSK-*) |
| Plugin | A task outside the core: builtin in the image or external under `PLUGINS_ROOT` |
| Runner | Host process that executes external tasks through `WORKSPACE_ROOT/queue/` |
| Analyzer | Metadata-only task that proposes values (phase, organ focus, readiness) (ANZ-*) |
| Annotation | An analyzer's per-item proposal with confidence and evidence; never overwrites data |
| Sidecar | Per-series DICOM JSON file with the full header (DCM-04); may contain PHI |
| Plugin Library | The view listing every installed first-party plugin with its status and an Open action (PLG-05) |
| Contribution point | What a plugin can add: tasks, views, editors, overlays, panels, commands, columns, packs (PLG-) |
| Study pack | Optional plugin bundle of labels, phases and profiles applied to a project (PRJ-16) |
| Layer | Plugin-owned columns joined to the converter rows (analyzers, labeling, curation); never written into `metadata.jsonl` (ADR-0020) |
| Workspace task | A task that runs without a project and writes to `_datasets/` (TSK-13) |
| Overlay window | A modal work window a plugin opens from a button, e.g. the converter (UI-25) |
| View-only link | `/v/{token}`: read-only access to a project without revealing its id (PRJ-17) |
| Quick fingerprint | `size` + SHA-256 of the first and last 64 KiB of a file |
| Case | All data for one `case_id` |
| Scan | One acquisition `(case_id, scan_idx)`, usually one contrast phase |
| Item | Viewable unit: scan × scope × side; target of curation and radiomics |
| Scope | `complete` (full CT + SEG) or `voi` (cropped VOI + VOI mask) |
| Axis order | NumPy memory order: `xyz` (nibabel) or `zyx` (SimpleITK arrays); spacing is always listed x, y, z (SOURCES §NumPy) |
| VOI | Volume of interest: a crop around a kidney/lesion, per side L/R |
| SEG | Multi-label segmentation mask of a full scan |
| Label map | Project-defined label values → name, color, opacity |
| Phase | Contrast phase: NC (non-contrast), CMP (corticomedullary), NP (nephrographic), EP (excretory), UNK |
| Variable | Any non-core metadata field (or external/derived column), typed and levelled (VAR-*) |
| Level | `case` (constant within a case) or `scan` |
| Derived variable | Bin, recode or dominant computed from other variables |
| Confounder | Variable that may bias comparisons (scanner, kernel, kVp) |
| Unit of analysis | What one analysis row is; default one per case (ANA-03) |
| q-value | p-value corrected for multiple testing (Benjamini–Hochberg FDR) |
| Curation event | Append-only reviewer decision record |
| Rollup | Case status derived from the worst item status |
| Correction queue | Items needing external (3D Slicer) correction |
| Profile | Named, hashed radiomics settings set |
| Run | One radiomics extraction over a selection with one profile |
| IBSI | Image Biomarker Standardisation Initiative, the reference for feature definitions |
| MPR | Multi-planar reconstruction: axial, coronal, sagittal views |
| W/L | Window width / level for CT intensity display (HU) |
| RAS | Right-Anterior-Superior world coordinate convention |
| SSE | Server-Sent Events, the one-way realtime stream from server to browser |
| udocker | User-space container runner; no root needed |
