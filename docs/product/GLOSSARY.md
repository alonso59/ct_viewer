# Glossary

Scope: terms used across docs. Read when a term is unclear.

| Term | Meaning |
|---|---|
| Workspace | Server directory (`WORKSPACE_ROOT`) holding all projects |
| Project | Folder with `project.json`, index, curation and radiomics state; references data by alias |
| Path alias / root | `ALIAS:rel/path` reference; the alias maps to an absolute root directory |
| Relink | Changing an alias root when data moves (QuPath "update URIs") |
| Quick fingerprint | `size` + SHA-256 of the first and last 64 KiB of a file |
| Case | All data for one `case_id` |
| Scan | One acquisition `(case_id, scan_idx)`, usually one contrast phase |
| Item | Viewable unit: scan × scope × side; target of curation and radiomics |
| Scope | `complete` (full CT + SEG) or `voi` (cropped VOI + VOI mask) |
| VOI | Volume of interest: a crop around a kidney/lesion, per side L/R |
| SEG | Multi-label segmentation mask of a full scan |
| Label map | Project-defined label values → name, color, opacity |
| Phase | Contrast phase: NC (non-contrast), CMP (corticomedullary), NP (nephrographic), EP (excretory), UNK |
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
