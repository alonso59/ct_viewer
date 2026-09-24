# Vision & Scope

Scope: purpose, users, in/out of scope, principles.
Read when: starting any work, or judging whether a feature belongs.
Depends: none.

## Purpose

A local-first, browser-based workbench for **CT dataset work**:
inspect volumes, visualize segmentations, curate datasets, extract radiomics,
and review feature quality visually. It combines the project-first layout of **QuPath**,
the shell of **VS Code** (tabs, panels, command palette) in the **GitHub Dark** theme,
and a **3D Slicer-style 2×2 CT viewer**, which QuPath lacks (ADR-0010).

Name: **Radiology Workbench**.
Version: **v3.0** (full rewrite of v2 Radiology WebUI; see ROADMAP §Migration).

## Users

| User | Goal | Main surfaces |
|---|---|---|
| Medical curator | Review scans and masks, record QC decisions, flag phase/side issues | Explorer, viewer, curation inspector |
| Researcher / data scientist | Configure and run radiomics, find outliers, export features | Radiomics view, dashboard, exports |
| Admin / data engineer | Create projects, import metadata, relink paths, run the server | Projects view, import wizard, jobs, deployment |

There are no roles. All users can reach every surface (ADR-0004).

## In scope (v3)

- Projects in the QuPath style: a folder that references image data by path alias and never copies it (PRJ-*).
- Import of `metadata.jsonl` (+ optional `phase.json`, `voi_catalog.jsonl`) and a data root path (IMP-*), or of any compatible NIfTI / DICOM / NumPy source through adapters (SRC-*).
- Open mode: a single file or folder (image, segmentation, DICOM) opens in the viewer without a project (SRC-09).
- Case-first explorer: case → phase → scan → VOI L/R.
- 2×2 MPR + 3D viewer, rendered client-side with NiiVue; multi-label overlays (VW-*).
- Segmentations are **never edited** in the app; tasks (e.g. nnU-Net) add new segmentation sets next to the imported ones (ADR-0015).
- Tasks and plugins: DICOM→NIfTI conversion with faithful metadata, metadata analyzers (phase, organ focus, readiness), radiomics and segmentation models share one contract (TSK-*, ADR-0016/0017).
- First-party plugin platform with a Plugin Library (ADR-0018): converter, analyzers, curation & QC, labeling tables, radiomics, dashboard, study packs. Projects are neutral (ID, share link, view-only link, multi-user; ADR-0019).
- Curation: QC status, comments, phase/side proposals, correction queue export (CUR-*).
- Radiomics: user-configurable extraction run by button, IBSI-aligned, versioned profiles (RAD-*).
- Study-agnostic variables: any metadata field or external table becomes a typed variable for filters and group-by (VAR-*).
- Radiomics dashboard with click-through to the viewer (DB-*) and simple guided statistics with recommendations (ANA-*).
- Multi-user access by shared project link, with live updates between browsers.
- Single OCI image; Docker locally, udocker on remote servers without sudo (OPS-*).

## Out of scope (v3)

| Excluded | Note |
|---|---|
| Mask editing, painting, voxel writes | Use 3D Slicer; hand off via the correction queue |
| Writing to source data or input metadata | `source` roots are read-only; task outputs go to a user-chosen `derived` root (R1, ADR-0014) |
| User accounts, roles, passwords | ADR-0004 |
| PACS / DICOM networking (C-STORE, DICOMweb), DICOM SEG writing | Files only; DICOM SEG reading is a later item (DCM-11) |
| Cloud upload, remote storage, PACS | Local filesystem only |
| Advanced statistics (multivariable models, ML, survival, mixed models, harmonization) | Export to Python/R; in-app stats stay simple (ADR-0012) |
| Registration / fusion, volume editing | Future |
| Electron desktop build | Phase P8, after the web app is stable (ADR-0001) |
| Clinical use | Research tool, not a medical device |
| Third-party plugins, plugin marketplace | v3 ships first-party plugins only (ADR-0018) |

## Principles

1. **Case, not file.** Users pick cases and scans; paths stay hidden unless asked for.
2. **Source is sacred.** Referenced data is opened read-only; project state is separate; generated volumes go to a derived root.
3. **Everything is reproducible.** Radiomics runs record their profile hash, engine versions and input fingerprints.
4. **Portable projects.** A project folder can be copied to another machine and relinked, as in QuPath.
5. **Quiet, dense UI.** QuPath workflow + VS Code idioms, keyboard-first, progressive disclosure.
6. **Same image everywhere.** Docker and udocker run the identical artifact.
7. **Study-agnostic.** No study-specific field names in code; ccRCC is a preset, not an assumption (ADR-0011).

## Decisions

- Label map and phase vocabulary: optional study packs applied after creation; the ccRCC pack holds the former defaults (PRJ-07, PRJ-16).
- UI language: English, i18n-ready (FE-11).
