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
- Import of `metadata.jsonl` (+ optional `phase.json`, `voi_catalog.jsonl`) and a data root path (IMP-*).
- Case-first explorer: case → phase → scan → VOI L/R.
- 2×2 MPR + 3D viewer, rendered client-side with NiiVue; multi-label overlays (VW-*).
- Segmentation **visualization only**.
- Curation: QC status, comments, phase/side proposals, correction queue export (CUR-*).
- Radiomics: user-configurable extraction run by button, IBSI-aligned, versioned profiles (RAD-*).
- Radiomics QC dashboard with click-through to the viewer (DB-*).
- Multi-user access by shared project link, with live updates between browsers.
- Single OCI image; Docker locally, udocker on remote servers without sudo (OPS-*).

## Out of scope (v3)

| Excluded | Note |
|---|---|
| Mask editing, painting, voxel writes | Use 3D Slicer; hand off via the correction queue |
| Writing to source data or input metadata | Exports only (R1) |
| User accounts, roles, passwords | ADR-0004 |
| DICOM import, DICOM→NIfTI conversion | Upstream pipeline |
| Cloud upload, remote storage, PACS | Local filesystem only |
| In-app inferential statistics (tests, p-values, model training) | Export to Python/R instead |
| Registration / fusion, volume editing | Future |
| Electron desktop build | Phase P8, after the web app is stable (ADR-0001) |
| Clinical use | Research tool, not a medical device |

## Principles

1. **Case, not file.** Users pick cases and scans; paths stay hidden unless asked for.
2. **Source is sacred.** Referenced data is opened read-only; project state is separate.
3. **Everything is reproducible.** Radiomics runs record their profile hash, engine versions and input fingerprints.
4. **Portable projects.** A project folder can be copied to another machine and relinked, as in QuPath.
5. **Quiet, dense UI.** QuPath workflow + VS Code idioms, keyboard-first, progressive disclosure.
6. **Same image everywhere.** Docker and udocker run the identical artifact.

## Decisions

- Label map: project-defined, seeded with the ccRCC defaults (PRJ-07).
- UI language: English, i18n-ready (FE-11).
