# Vision & product requirements (PRD)

Scope: purpose, problem, goals, users, journeys G1..G4, in/out of scope, principles, assumptions, risks.
Read when: starting any work, or judging whether a feature belongs.
Depends: none (requirements by ID: SRS.md; release cut: MVP.md).

## Purpose

A local-first, browser-based workbench for **CT dataset work**:
inspect volumes, visualize segmentations, curate datasets, extract radiomics,
and review feature quality visually. It combines the project-first layout of **QuPath**,
the shell of **VS Code** (tabs, panels, command palette) in the **GitHub Dark** theme,
and a **3D Slicer-style 2×2 CT viewer**, which QuPath lacks (ADR-0010).

Name: **Radiology Workbench**.
Version: **v3.0** (full rewrite of v2 Radiology WebUI; see ROADMAP §Migration).

## Problem

CT dataset work is spread over tools that each cover one step: 3D Slicer for viewing, QuPath-like
project folders or spreadsheets for case lists and QC notes, scripts for DICOM conversion and radiomics,
notebooks for statistics. Provenance between a QC decision, the features extracted and the analysis is
lost on the way, and nobody can review a whole dataset in one place.

## Goals

| # | Goal | Measured by (§Success metrics) |
|---|---|---|
| 1 | One place to inspect, curate and analyse a CT dataset, from raw DICOM to an exported analysis | G1..G4 complete end to end |
| 2 | Never damage or leak source data | NFR-11, NFR-12, NFR-17 |
| 3 | Reproducible results | NFR-15, RAD-09 |
| 4 | Fast enough for daily review of 500–3,000 cases | NFR-01..05 |
| 5 | Runs the same locally and on a no-sudo server | NFR-10, OPS-* |

## Success metrics

Targets are owned elsewhere; this table only says which ones define success.

| Metric | Target | Owner |
|---|---|---|
| Each journey G1..G4 walks end to end on the fixtures, one Playwright spec per journey | pass | MVP.md (REL-02), TESTING |
| Performance and footprint | NFR-01..10 | NFR.md |
| Safety, privacy, reproducibility | NFR-11, NFR-12, NFR-14, NFR-15, NFR-17, NFR-18 | NFR.md |
| Wayfinding: every core object reachable in ≤ 3 actions from the case tab, and from the palette | audit A1 reachability matrix | archive/v3/audit/PLAN.md (closed audit) |
| Release gates | REL-* | MVP.md |

## Users

| User | Goal | Main surfaces |
|---|---|---|
| Medical curator | Review scans and masks, record QC decisions, flag phase/side issues | Explorer, viewer, curation inspector |
| Researcher / data scientist | Configure and run radiomics, find outliers, export features | Radiomics view, dashboard, exports |
| Admin / data engineer | Create projects, import metadata, relink paths, run the server | Projects view, import wizard, jobs, deployment |

There are no roles. All users can reach every surface (ADR-0004).

## Journeys

The golden paths. Each is the user's goal, not the UI's; the MVP (MVP.md) and the v3 audit (archive/v3/audit/PLAN.md, closed) were built on them.

| Path | Steps (the user's goal, not the UI's) | Refs |
|---|---|---|
| **G1 · Open & inspect** | Home → open a single NIfTI → 2×2 with the right W/L → scroll, zoom one view, fit (F) → HU probe, distance, header → attach a label map → Save as NIfTI… / Create project from this → Close | UI-17, UI-24, SRC-09/14/15, VW-* |
| **G2 · DICOM → project** | Home → Convert DICOM… (overlay) → dry run → run → Create project → import wizard → explorer with thumbnails, phase and warnings → open a case | UI-25, DCM-*, IMP-*, UI-08/09 |
| **G3 · Review & curate** | Open case → review scans/masks → one-click phase → QC status + comment → label a patient-level and a scan-level cell → **next case without the mouse** → correction queue export → second browser sees it live → view-only link can't write | CUR-*, PHS-*, LBL-*, UI-26, TST-08 |
| **G4 · Radiomics → analysis** | Radiomics settings → selection by variable + `seg_id` → estimate → run → dashboard → outlier → viewer in one click → group comparison on a derived variable → export | RAD-*, DB-*, ANA-*, VAR-06 |

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

## Assumptions

- Data sits on a local or mounted filesystem the server can read; the design envelope and reference volume are in NFR.md.
- Users have a WebGL2 browser (NFR-13) on a machine with an integrated or better GPU.
- Development and audits use synthetic fixtures only (`.fixtures/synthetic`, TST-11); no real data or PHI in the repo.
- One OCI image; Docker locally, udocker remotely (ADR-0007).

## Risks

| Risk | Mitigation (owner) |
|---|---|
| Browser memory on large volumes | `VIEWER_MAX_LOADED`, NFR-09 (VIEWER, NFR) |
| udocker behaviour not yet verified on the remote server | ROADMAP Step 4, MVP REL-07 |
| PHI leaking through exports, bundles or logs | NFR-17, DCM-05, audit A5 |
| Radiomics engine drift | pinned upstream commit, IBSI checks (ADR-0006, TST-06) |
| Docs and code drift apart | ownership table (INDEX), `make check` requirement check (SRS §1.5), `make trace` |

## Releases

v3.0 is the release cut in MVP.md; later work is ordered in ROADMAP.

## Decisions

- Label map and phase vocabulary: optional study packs applied after creation; the ccRCC pack holds the former defaults (PRJ-07, PRJ-16).
- UI language: English, i18n-ready (FE-11).
