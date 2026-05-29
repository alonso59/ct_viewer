# Software Requirements Specification (SRS)

## Radiology WebUI — Medical Dataset Curation Tool

| Field       | Value                                                     |
| ----------- | --------------------------------------------------------- |
| **Version** | 2.0                                                       |
| **Date**    | 2026-05-28                                                |
| **Status**  | Target specification for v2.0 upgrade from v1.2           |
| **Project** | radio-ccrcc / Radiology WebUI                             |
| **Author**  | Alonso (researcher) + GitHub Copilot / Codex-assisted SRS |

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Overall Description](#2-overall-description)
3. [Data Model & Folder Schema](#3-data-model--folder-schema)
4. [Functional Requirements](#4-functional-requirements)
5. [Controlled Dataset Correction](#5-controlled-dataset-correction)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [User Interface Specification](#7-user-interface-specification)
8. [Technical Architecture](#8-technical-architecture)
9. [Deployment](#9-deployment)
10. [Future Versions (Out of Scope v2.0)](#10-future-versions-out-of-scope-v20)
11. [Acceptance Criteria](#11-acceptance-criteria)
12. [Glossary](#12-glossary)

---

## 1. Introduction

### 1.1 Purpose

This document specifies the requirements for **Radiology WebUI v2.0**, a lightweight, local-first Web-based medical dataset curation interface for the `radio-ccrcc` pipeline.

The v2.0 system is no longer only an auxiliary researcher viewer. It is a **two-screen medical curation cockpit** where the medical doctor is the data-curation owner. The tool shall support case-by-case review of CT volumes, segmentation masks, VOIs, canonical metadata, QC warnings, and case-level segmentation QC decisions.

The WebUI shall allow the medical curator to:

* select a dataset;
* review cases in a Main Review Screen with an always-visible case navigator;
* inspect complete scans and VOIs;
* switch between scan, phase, scope, and side through the left review panel;
* inspect axial, coronal, sagittal, and optional 3D views in a fixed 2x2 viewer;
* inspect SEG and VOI mask overlays;
* see QC warnings from `database.csv` reconciliation;
* assign one segmentation QC decision per case;
* add optional segmentation-focused comments;
* send cases to a correction queue when needed;
* perform controlled, confirmed, auditable dataset correction operations for phase correction or scan/VOI exclusion when explicitly enabled.

The WebUI shall not edit segmentation masks directly. Segmentation correction remains out of scope and shall be performed in specialized software such as 3D Slicer.

### 1.2 Scope

**In scope (v2.0):**

* Use `database.csv` as the primary source of truth when available.
* Treat `manifest.csv` and folder discovery as legacy fallback only.
* Browse a mounted dataset folder and validate `database.csv` status.
* Present two primary screens only: Dataset Load Screen and Main Review Screen.
* Keep the `/cases` page, if present, as legacy or non-primary in v2.0.
* Show one Main Review Screen per selected `case_id`.
* Keep the left module panel and fixed 2x2 viewer workspace always visible at the target review resolution.
* Show a compact case summary and scan inventory.
* Show all available phases, scan indices, complete scans, SEG masks, VOI images, and VOI masks for a case.
* Visualize NIfTI full volumes and NIfTI VOI volumes.
* Preserve legacy NumPy VOI support only as compatibility fallback.
* Overlay multi-label segmentation masks with per-layer visibility, opacity, filled mode, and contour-only mode.
* Support axial, coronal, and sagittal views.
* Preserve pan, zoom, window/level adjustment, slice navigation, and crosshair synchronization.
* Preserve optional 3D surface rendering as an on-demand secondary orientation aid.
* Display QC warnings for missing files, duplicate mappings, incomplete VOIs, phase inconsistencies, laterality inconsistencies, and path-resolution failures.
* Allow routine curation-state writing:

  * Accepted;
  * Needs correction;
  * Rejected;
  * Cannot assess;
  * optional free-text segmentation/VOI comment.
* Distinguish case-level QC decisions from source-level flags such as wrong phase, exclude scan, exclude VOI, missing SEG, missing VOI, ambiguous phase, or wrong side.
* Support controlled dataset correction operations for phase correction and scan/VOI exclusion with explicit confirmation, audit logging, and validation refresh.
* Store curation decisions separately from `database.csv`.
* Export or list a correction queue for external segmentation correction.
* Run as one web service image, compatible with `docker`, `podman`, and `udocker`.

**Out of scope (v2.0):**

* Direct segmentation editing, brush tools, or mask painting.
* Direct voxel-level modification of NIfTI, SEG, or VOI files.
* Casual or silent phase renaming, file movement, scan exclusion, VOI exclusion, or `database.csv` overwrite from routine QC controls.
* DICOM → NIfTI conversion trigger from the UI.
* Preprocessing / VOI extraction pipeline trigger from the UI.
* Multi-series co-registration / fusion.
* Full PACS or DeepUnity-like universal viewer behavior.
* Full 3D Slicer-like module ecosystem.
* Clinical-grade certification.
* Multi-user hospital PACS workflow.
* Radiomics statistical dashboards.
* Model training dashboards.

### 1.3 Target Users

| User                     | Description                                                                   | Main Needs                                                                                        |
| ------------------------ | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **Medical Curator**      | Medical doctor responsible for dataset QC and segmentation-quality decisions. | Case-first review, intuitive viewer, segmentation comments, curation decisions, correction queue. |
| **Research Scientist**   | Researcher validating dataset consistency and downstream usability.           | Traceability, metadata provenance, QC summaries, curation outputs.                                |
| **Technical Maintainer** | Developer or data engineer maintaining the WebUI and dataset pipeline.        | Stable API, path resolution, reconciliation diagnostics, tests, safe persistence.                 |

The primary user for v2.0 is the **Medical Curator**.

### 1.4 References

| Reference                    | Description                                                                   |
| ---------------------------- | ----------------------------------------------------------------------------- |
| 3D Slicer (slicer.org)       | Open-source medical image computing platform — MPR/overlay inspiration        |
| DeepUnity / clinical viewers | Case-centered clinical workflow inspiration, not a target for feature copying |
| `database.csv`               | Reconciled canonical dataset table for v2.0                                   |
| `manifest.csv`               | Raw converter metadata; legacy fallback, not primary v2.0 source              |
| `nifti_visualizer.ipynb`     | Existing Jupyter NIfTI viewer in this project                                 |
| `voi_visualizer.ipynb`       | Existing Jupyter VOI viewer in this project                                   |
| `visualizer_utils.py`        | Shared rendering/overlay utilities                                            |
| `src/converter/`             | DICOM → NIfTI converter pipeline                                              |
| `src/preprocessor/`          | VOI preprocessing pipeline                                                    |

---

## 2. Overall Description

### 2.1 Product Perspective

Radiology WebUI v1.2 is a local researcher-oriented viewer replacing Jupyter visualizers with a persistent browser-accessible application. It provides valuable visualization functions, including MPR views, overlays, 3D surfaces, review controls, and optional mutation workflows.

Radiology WebUI v2.0 upgrades the product into a **ccRCC CT Dataset Curation WebUI**. The primary goal is not to add a heavy workstation, but to make the current viewer medically usable for doctor-led audit/QC.

The v2.0 product shall sit between two extremes:

* It shall be more structured and medically intuitive than a research notebook or raw file viewer.
* It shall remain much lighter than DeepUnity, PACS systems, or 3D Slicer.

The key product principle is:

> The medical doctor selects a case, not a file.

The product model has two primary user-facing screens:

1. **Dataset Load Screen** — choose and validate the dataset, then start or resume review.
2. **Main Review Screen** — perform routine case review, source navigation, CT/VOI comparison, warning inspection, and case-level QC.

The `/cases` page is not a primary v2.0 user-facing surface. If retained for compatibility, it shall be treated as a legacy or technical route and shall not be required for routine review.

The system shall translate `database.csv` rows and dataset paths into direct source identities:

```text
Case -> Phase -> Scan -> Scope -> Side
```

The Main Review Screen shall expose source identities through the left review panel as phase filters plus scan-grouped source cards. Each selectable source represents a complete `phase + scan + scope + side` combination, such as `NP · scan 1 · Complete CT` or `NP · scan 1 · VOI R`.

### 2.2 Operating Environment

| Aspect         | Specification                                                                                        |
| -------------- | ---------------------------------------------------------------------------------------------------- |
| Host OS        | Linux (primary), macOS (secondary)                                                                   |
| Container      | OCI image run via `udocker`, `podman`, or `docker`                                                   |
| Browser        | Chromium-based browsers or Firefox, latest 2 ESR                                                     |
| Data mount     | Host path bind-mounted at `/data`; source imaging data should be read-only whenever possible         |
| Curation state | Stored separately from source images; preferably in `.webui/` or configured external state directory |
| Network        | Localhost or trusted internal network only; no external upload                                       |

### 2.3 Constraints

* **Single service runtime**: backend API and compiled frontend are served by one container process.
* **database.csv-first design**: when `database.csv` exists, it shall drive case, scan, VOI, path, and QC state.
* **Legacy fallback**: folder discovery and `manifest.csv` may remain as fallback, but shall not be the primary v2.0 workflow.
* **Visualization preservation**: current MPR rendering, slice navigation, overlays, pan/zoom, and W/L behavior should be reused where possible.
* **No segmentation editing**: the WebUI shall not modify voxel data.
* **Two-screen product model**: the primary user-facing flow is Dataset Load Screen -> Main Review Screen. `/cases` and full-page metadata routes are not primary v2.0 surfaces.
* **Routine curation-state writing**: ordinary QC writes curation state only; it does not move files or edit `database.csv`.
* **Controlled dataset correction**: phase correction and scan/VOI exclusion are separate, confirmed, auditable operations. They may update `database.csv` and relocate VOI files only through the controlled correction workflow.
* **No silent mutation**: no routine control may silently rename files, move files, exclude data, or overwrite canonical metadata.
* **Auditability**: all curation decisions and controlled correction operations shall include reviewer, timestamp, target, status/result, comment when provided, source row reference when available, and before/after values when data changes.

### 2.4 Assumptions

* Input data follows the folder schema defined in Section 3, or the required paths are explicitly provided in `database.csv`.
* `database.csv` has already been reconciled per dataset.
* `database.csv` may be wide and contain hundreds or thousands of columns; the UI shall not display all columns by default.
* Segmentation masks use integer labels: `0`=background, `1`=kidney, `2`=tumor, `3`=cyst, unless otherwise specified by dataset metadata.
* NIfTI files may not be in RAS orientation; the backend applies `nib.as_closest_canonical()` on load. Original files are never modified.
* VOI files may be stored as NIfTI in v2.0. Legacy `.npy` VOIs may still exist and should be supported only as compatibility fallback.
* The medical doctor owns curation decisions, but segmentation correction is performed outside this WebUI.

---

## 3. Data Model & Folder Schema

The WebUI operates on one active **Dataset root** (`DatasetID/`) at a time. The user provides the server-side filesystem path to a dataset folder through the GUI, and the backend activates that folder as the current workspace.

### 3.1 Canonical Dataset Layout

v2.0 expects `database.csv` to be present at the dataset root.

```text
DatasetID/
├── database.csv                           # Canonical reconciled review database; primary v2.0 source
├── manifest.csv                           # Raw converter metadata; legacy fallback / provenance
├── conversion_summary.json                # Converter run metadata, if available
├── dataset.json                           # Preprocessor dataset summary, if available
├── dataset_fingerprint.json               # Preprocessor fingerprint, if available
├── patient_preprocess.csv                 # Preprocessor per-patient log, if available
├── splits.json                            # Train/val/test splits, if available
│
├── .webui/                                # Optional app-state folder; no source image data
│   ├── settings.json                      # Viewer settings persisted by this app
│   ├── curation_review.csv                # Segmentation QC decisions and comments
│   ├── correction_queue.csv               # Exportable queue for external correction
│   ├── decisions.json                     # Optional append-only curation audit log
│   ├── dataset_corrections.json           # Controlled correction audit log, if mutations enabled
│   ├── backups/                           # Recommended pre-correction database/VOI backups
│   └── warnings_cache.json                # Optional cached database/path validation warnings
│
├── nifti/                                 # Full CT volumes
│   ├── 01_case_00001_0000.nii.gz
│   ├── 02_case_00001_0000.nii.gz
│   └── ...
│
├── seg/                                   # nnU-Net or equivalent segmentation masks
│   ├── 01_case_00001.nii.gz
│   ├── 02_case_00001.nii.gz
│   └── ...
│
└── voi/                                   # Cropped VOIs
    ├── images/{group}/{phase}/
    │   ├── NN_case_YYYYY_L.nii.gz
    │   ├── NN_case_YYYYY_R.nii.gz
    │   └── ...
    │
    └── mask/{group}/{phase}/
        ├── NN_case_YYYYY_L.nii.gz
        ├── NN_case_YYYYY_R.nii.gz
        └── ...
```

The backend shall not require the medical curator to know or navigate this structure manually.

### 3.2 database.csv Role

`database.csv` is the canonical v2.0 source of truth for WebUI navigation and file resolution.

It shall define or preserve, when available:

| Column / Field               | Description                                               |
| ---------------------------- | --------------------------------------------------------- |
| `dataset_id`                 | Dataset identifier                                        |
| `case_id`                    | Canonical case identifier, e.g. `case_00042`              |
| `patient_id`                 | Original source patient identifier, if available          |
| `group`                      | Dataset group/classification label                        |
| `scan_idx`                   | Scan/series index within case                             |
| `filename`                   | Original or canonical NIfTI filename                      |
| `raw_phase`                  | Original phase value from manifest/folder/source metadata |
| `canonical_phase` or `phase` | Normalized phase used by WebUI                            |
| `phase_source`               | How phase was assigned or normalized                      |
| `phase_confidence`           | Optional confidence level for phase normalization         |
| `side`                       | L/R side for VOI rows when applicable                     |
| `laterality`                 | Laterality metadata when available                        |
| `tumor_laterality`           | Tumor laterality when available                           |
| `nifti_path`                 | Path to complete CT scan                                  |
| `seg_path`                   | Path to complete-scan segmentation mask                   |
| `voi_image_path`             | Path to VOI image                                         |
| `voi_mask_path`              | Path to VOI mask                                          |
| `has_seg`                    | Boolean or derived availability flag                      |
| `has_voi_image`              | Boolean or derived availability flag                      |
| `has_voi_mask`               | Boolean or derived availability flag                      |
| `preprocess_status`          | Preprocessing status when available                       |
| `validation`                 | Validation flag when available                            |
| `source_row_id`              | Stable row reference, if provided                         |
| `database_build_version`     | Version of canonical database builder                     |
| `updated_at`                 | Timestamp of database generation/update                   |

The WebUI shall preserve access to all additional columns through advanced metadata, but shall not expose all columns by default.

### 3.3 Phase Convention and Normalization

v2.0 shall support canonical phase naming without destructive renaming.

Recommended canonical phase vocabulary:

| Canonical phase | Meaning                                  |
| --------------- | ---------------------------------------- |
| `NC`            | Non-contrast phase                       |
| `CMP`           | Corticomedullary phase                   |
| `NP`            | Nephrographic phase                      |
| `EXC`           | Excretory/delayed phase                  |
| `UNK`           | Unknown, ambiguous, or unavailable phase |

Legacy or source phase names may include:

| Legacy/source value         | Possible canonical mapping                       |
| --------------------------- | ------------------------------------------------ |
| `NC`                        | `NC`                                             |
| `ART`                       | `CMP`, if clinically and metadata-wise justified |
| `VEN`                       | `NP`, if clinically and metadata-wise justified  |
| `DELAY`, `EXC`, `EXCRETORY` | `EXC`                                            |
| `UNDEFINED`, empty, unknown | `UNK`                                            |

The system shall preserve the original phase value. Routine QC shall never overwrite phase metadata. A confirmed Controlled Dataset Correction operation may update the canonical phase in `database.csv` and relocate affected VOI files according to Section 5.

Recommended fields:

| Field              | Purpose                                             |
| ------------------ | --------------------------------------------------- |
| `raw_phase`        | Original phase value from source                    |
| `canonical_phase`  | Normalized phase used for UI grouping               |
| `phase_source`     | Folder, manifest, protocol, manual proposal, etc.   |
| `phase_confidence` | High, medium, low, unknown                          |
| `phase_status`     | normalized, ambiguous, missing, proposed_correction |
| `proposed_phase`   | Doctor-proposed corrected phase before controlled apply, if any |
| `corrected_phase`  | Applied corrected phase after controlled correction, if any |
| `phase_comment`    | Medical curator comment                             |

The WebUI may allow a medical curator to flag or apply a phase correction. A flag writes curation state only. An applied correction is not a casual toggle: it requires explicit confirmation, audit logging, optional backup, controlled `database.csv` update, controlled VOI relocation when needed, and validation refresh.

### 3.4 Naming Conventions

| Token        | Pattern                         | Example                           | Description                            |
| ------------ | ------------------------------- | --------------------------------- | -------------------------------------- |
| `NN`         | `\d{2}`                         | `01`                              | Per-case series counter                |
| `case_YYYYY` | `case_\d{5}`                    | `case_00042`                      | Sequential case ID                     |
| `_0000`      | literal                         | `_0000`                           | nnU-Net channel suffix for image files |
| `{L,R}`      | `_L`, `_R`, `sideL`, or `sideR` | `_L`                              | Laterality / side token                |
| `{group}`    | string                          | `A`, `B`, `NG`                    | Patient classification group           |
| `{phase}`    | canonical or raw phase          | `NC`, `CMP`, `NP`, `EXC`, `UNK` | Contrast phase label                   |

### 3.5 Mask Label Map (Multi-Label)

| Label | Structure  | Default color | Default alpha | Default visible |
| ----- | ---------- | ------------- | ------------- | --------------- |
| 0     | Background | —             | —             | —               |
| 1     | Kidney     | light blue    | 0.15          | ✓               |
| 2     | Tumor      | orange/red    | 0.20          | ✓               |
| 3     | Cyst       | green         | 0.15          | ✗               |

### 3.6 Case-to-Scan-to-VOI Mapping

One **case** (`case_YYYYY`) may have:

* 1–N full NIfTI volumes in `nifti/` or paths specified by `database.csv`.
* 0–N corresponding segmentation masks in `seg/` or paths specified by `database.csv`.
* 0–N VOI images in `voi/images/` or paths specified by `database.csv`.
* 0–N VOI masks in `voi/mask/` or paths specified by `database.csv`.
* 0–N sides (`L`, `R`) depending on VOI availability.
* 0–N curation decisions in `curation_review.csv`.

The Main Review Screen source identity model for v2.0 is:

```text
Case -> Phase -> Scan -> Scope -> Side
```

Where `scope` is either:

* `complete` — full CT scan and SEG mask;
* `voi` — cropped VOI image and VOI mask.

### 3.7 Curation State Files

Routine curation state shall be stored separately from `database.csv`.

Recommended default:

```text
DatasetID/.webui/curation_review.csv
DatasetID/.webui/correction_queue.csv
DatasetID/.webui/dataset_corrections.json
```

Alternative for read-only dataset mounts:

```text
$WEBUI_STATE_DIR/{dataset_id}/curation_review.csv
$WEBUI_STATE_DIR/{dataset_id}/correction_queue.csv
$WEBUI_STATE_DIR/{dataset_id}/dataset_corrections.json
```

Minimum fields for `curation_review.csv`:

| Column            | Description                                                                                                                             |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `review_id`       | Unique review decision ID                                                                                                               |
| `dataset_id`      | Dataset identifier                                                                                                                      |
| `case_id`         | Case identifier                                                                                                                         |
| `patient_id`      | Source patient ID, if available                                                                                                         |
| `source_row_id`   | Reference to `database.csv` row if available                                                                                            |
| `scan_idx`        | Scan index                                                                                                                              |
| `raw_phase`       | Original phase                                                                                                                          |
| `canonical_phase` | Current normalized phase                                                                                                                |
| `proposed_phase`  | Doctor-proposed phase correction, if any                                                                                                |
| `side`            | L/R if applicable                                                                                                                       |
| `scope`           | complete or voi                                                                                                                         |
| `target`          | case-level segmentation/VOI QC                                                                                                          |
| `status`          | accepted, needs_correction, rejected, cannot_assess                                                                                     |
| `source_flags`    | Optional source-level flags: wrong_phase, exclude_scan, exclude_voi, missing_seg, missing_voi, ambiguous_phase, wrong_side              |
| `priority`        | Optional correction priority: low, medium, high                                                                                         |
| `comment`         | Free-text curation comment                                                                                                              |
| `reviewer`        | Reviewer name or ID                                                                                                                     |
| `reviewed_at`     | Timestamp                                                                                                                               |
| `nifti_path`      | Complete scan path at review time                                                                                                       |
| `seg_path`        | SEG path at review time                                                                                                                 |
| `voi_image_path`  | VOI image path at review time                                                                                                           |
| `voi_mask_path`   | VOI mask path at review time                                                                                                            |

### 3.8 Case QC vs Source Flags

v2.0 separates the medical QC decision from source-specific review flags.

**Case-level QC decision** is one decision per case:

| Decision | Meaning |
| -------- | ------- |
| `accepted` | Segmentation/VOI quality is acceptable for this case. |
| `needs_correction` | Case requires external correction and is automatically added to the correction queue. |
| `rejected` | Case should not be used as acceptable review data. |
| `cannot_assess` | Reviewer cannot make a reliable determination from the loaded source. |

**Source-level flags** describe issues with scans, phases, VOIs, paths, or source mapping. They do not replace the case-level QC decision.

| Flag | Meaning | v2.0 behavior |
| ---- | ------- | ------------- |
| `wrong_phase` | Active scan or VOI appears mislabeled. | May trigger controlled phase correction. |
| `exclude_scan` | Scan should be excluded from downstream use. | Controlled dataset correction only. |
| `exclude_voi` | VOI should be excluded from downstream use. | Controlled dataset correction only. |
| `missing_seg` | Required SEG is missing or unreadable. | Blocks QC save. |
| `missing_voi` | VOI image or mask is missing or unreadable. | Informational warning in v2.0. |
| `ambiguous_phase` | Phase cannot be confidently determined. | Informational warning in v2.0. |
| `wrong_side` | VOI laterality appears incorrect. | Informational flag unless a controlled correction is implemented. |

Routine QC writes curation state. Controlled dataset correction may mutate `database.csv` or relocate VOI files only through the workflow in Section 5.

---

## 4. Functional Requirements

### 4.1 Dataset Load, Routing & Navigation

| ID     | Requirement                                                                                                                                                                                                                                                      | Priority |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-01  | **Dataset Load Screen**: The application shall provide a Dataset Load Screen where the user can browse allowed backend roots, select a dataset folder or `database.csv`, validate readiness, and start or resume review.                                          | Must     |
| FR-01a | **Workspace Validation**: The selected dataset folder or `database.csv` must exist on the backend server. For v2.0, `database.csv` is required for activation through Dataset Discovery. Validation is lightweight and shall not recursively crawl datasets or load all image volumes. | Must     |
| FR-01b | **Database Status**: After workspace activation, the system displays `database.csv` status, row count, case count, required-column status, SEG availability, VOI availability, reviewed count when available, and warning count.                                  | Must     |
| FR-01c | **Two Primary Screens**: The primary user-facing product shall contain only Dataset Load Screen and Main Review Screen. `/cases` shall be legacy, technical, or non-primary in v2.0.                                                                             | Must     |
| FR-01d | **Safe Backend Browser**: The backend shall expose a one-level browser restricted to allowed roots from `DATASET_DIR`, `DATASET_ROOTS`, `DATA_ROOT`, and `/data` when mounted. Requests outside allowed roots shall be rejected.                                  | Must     |
| FR-01e | **Selection Validation Modal**: The frontend shall show validation progress through Checking path, Finding `database.csv`, Reading CSV, Checking columns, Sampling files, and Building summary; completion shall show Success/Warnings/Errors counts and an OK action. | Must     |
| FR-01f | **Docker Path Mapping Copy**: When `/data` is available, the Dataset Load Screen shall explain that host `DATASET_DIR` is mounted inside the app as `/data`. Manual entry shall be labeled as a backend/server path, not a local browser path.                    | Must     |
| FR-02  | **Case Discovery**: System builds the review case navigator from `database.csv`, grouped by `case_id`. If `database.csv` is absent, it may fall back to v1.2 patient discovery.                                                                                  | Must     |
| FR-03  | **Inventory Discovery**: For a selected case, the system lists all available scans, phases, scopes, sides, complete scans, SEG masks, VOI images, and VOI masks from `database.csv`.                                                                             | Must     |
| FR-04  | **Adaptive Content**: The viewer adapts to available data: complete scan only, complete scan + SEG, VOI only, VOI + VOI mask, or missing/partial data with visible warning badges.                                                                               | Must     |
| FR-05  | **Case Search/Filter**: The Main Review Screen case navigator may search by case ID or patient ID and filter by group, canonical phase, curation status, warning status, VOI availability, or segmentation status.                                                | Should   |
| FR-06  | **Direct Source Navigation**: Routine source navigation shall expose complete source choices rather than disconnected technical dropdowns. A source choice represents phase + scan + scope + side.                                                        | Must     |
| FR-07  | **Default Source Load**: When opening a case, scan `0` complete CT shall load by default when available. If scan `0` is unavailable, the system shall load the first valid complete CT source and show a warning/status cue.                                      | Must     |

### 4.2 Main Review Screen & Left Panel

| ID    | Requirement                                                                                                                                                                                                   | Priority |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-10 | **Main Review Screen**: Routine review shall happen in the Main Review Screen with an always-visible left module panel, fixed 2x2 viewer workspace, and Case Data modal. The left module panel replaces the previous right QC panel and bottom drawer. | Must     |
| FR-11 | **Left Review Panel Role**: The left panel is the main non-image control area and shall contain persistent case navigation, a direct source navigator, warning badges, and Case Data action. Overlay configuration remains in a viewer popover. | Must |
| FR-12 | **Case Navigator**: The case navigator shall remain visible in the left panel footer across all modules and shall show visible case identity, review status, queue status when relevant, and warning badges for affected cases. | Must     |
| FR-13 | **Scan/Source Navigator**: The source navigator shall use phase chips (`NP`, `CMP`, `NC`, `EXC`) and scan-grouped cards (`CT`, `VOI L`, `VOI R`) showing selected, available, missing, warning, and disabled states. Clicking a card loads that exact source. | Must     |
| FR-14 | **Inventory Detail**: Wide inventory detail shall be secondary and collapsible below the source cards. Routine source selection shall not require horizontal scrolling inside the left panel.                      | Must     |
| FR-15 | **Secondary Content in Left Panel Modules**: Inventory, warning detail, and history shall be accessible as modules in the left panel selector. A bottom drawer component may exist in the codebase but shall not be visible by default. | Should   |

### 4.3 Viewer Grid & 2D Visualization

| ID    | Requirement                                                                                                                                                       | Priority |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-20 | **Fixed Viewer Grid**: The default viewer layout shall be a fixed 2x2 grid with AXI top-left, COR top-right, SAG bottom-left, and 3D bottom-right. Panels remain present even when one panel has no data, and pane positions/geometry shall not change when switching case, scan, phase, scope, side, or VOI. | Must     |
| FR-21 | **Axial View**: Display axial slice with correct orientation.                                                                                                      | Must     |
| FR-22 | **Coronal View**: Display coronal slice with correct orientation.                                                                                                  | Must     |
| FR-23 | **Sagittal View**: Display sagittal slice with correct orientation.                                                                                                | Must     |
| FR-24 | **Display Aspect Preservation**: Complete CT slices shall preserve physical aspect ratio when spacing is available and shall never be stretched to fill a non-matching panel. VOI sources shall use viewer-effective isotropic spacing `[1,1,1]` by default in 2D and 3D. | Must     |
| FR-25 | **Fit-to-Panel Default**: Each 2D panel shall default to fit the entire slice inside the fixed panel. Panel containers shall be rectangular and fill available 2x2 grid space; image content shall be centered, contained, and fitted without changing pane geometry. Complete CT and VOI sources use independent fit by default. | Must     |
| FR-26 | **Reserved Slider Space**: Slice sliders shall have reserved fixed space so image content and controls do not shift during loading or interaction.                 | Must     |
| FR-27 | **Auto-Centering**: The active source image shall auto-center and reset to the correct physical fit when case, scan, phase, scope, or side changes.                | Must     |
| FR-28 | **Independent Pan & Zoom**: User can pan and zoom independently within each 2D view.                                                                               | Must     |
| FR-29 | **Slice Navigation**: Each view has a slider or mouse-wheel interaction to navigate through slices.                                                                | Must     |
| FR-30 | **Crosshair Synchronization**: Selecting a point in one 2D view updates the crosshair position in the other two 2D views.                                          | Must     |
| FR-31 | **Window/Level Control**: User can adjust HU window and level via right-drag interaction or numeric input. Default: W=400, L=50 unless overridden by saved settings. | Must  |
| FR-32 | **W/L Presets**: Quick-select presets: Soft Tissue, Bone, Lung, Brain.                                                                                            | Should   |
| FR-33 | **RAS Reorientation**: NIfTI volumes are reoriented to RAS on load using `nibabel.as_closest_canonical`. Original files are never modified.                        | Must     |
| FR-34 | **Legacy NumPy VOI Support**: Legacy `.npy` VOI arrays may be loaded as compatibility fallback. v2.0 primary VOI format is NIfTI when paths are provided in `database.csv`. | Should |

### 4.4 CT to VOI Comparison, Overlays & 3D

| ID    | Requirement                                                                                                                                                                  | Priority |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-40 | **CT to VOI Comparison in Main Screen**: CT to VOI comparison shall happen inside the Main Review Screen, not in a separate route.                                            | Must     |
| FR-41 | **v2.0 Comparison Mode**: v2.0 shall support fast toggling between Complete CT and VOI scope within the same fixed 2x2 viewer while preserving case/source context. Fully synchronized side-by-side CT/VOI comparison is deferred to a future version unless explicitly implemented. | Must |
| FR-42 | **Mask Overlay**: If a SEG mask or VOI mask exists, overlay it on the 2D views.                                                                                              | Must     |
| FR-43 | **Multi-Label Rendering**: Overlay renders labels 1 kidney, 2 tumor, and 3 cyst with distinct colors and contour borders.                                                    | Must     |
| FR-44 | **Per-Layer Visibility**: Each label has an independent visibility toggle. Default: kidney=on, tumor=on, cyst=off.                                                           | Must     |
| FR-45 | **Per-Layer Opacity**: Each label has an independent opacity slider. Default: kidney=0.15, tumor=0.20, cyst=0.15.                                                            | Must     |
| FR-46 | **Overlay Render Mode**: Each overlay supports filled mode and contour-only mode. Default mode is filled.                                                                    | Should   |
| FR-47 | **Overlay HUD and Settings**: The viewer shall show a compact overlay status HUD using the same colors as the rendered overlays, plus an anchored viewer popover for overlay settings. The popover shall not be moved into the left panel. | Must     |
| FR-48 | **Mask Path Resolution**: System resolves masks from `database.csv` path fields first. Filename-derived matching is legacy fallback only.                                    | Must     |
| FR-49 | **Overlay Missing Warning**: If a selected item claims mask availability but the file is missing or unreadable, the viewer shows a warning badge/detail instead of failing silently. | Must |
| FR-50 | **3D Surface Slot**: The 3D slot is on demand and secondary. It shall not dominate the routine medical curation workflow.                                                    | Must     |
| FR-51 | **3D Surface Rendering**: When a segmentation mask exists and 3D is requested, generate and display an isosurface mesh for each visible label.                               | Should   |
| FR-52 | **3D Empty State**: When no mask is available, the 3D slot displays an informational empty state.                                                                            | Should   |

### 4.5 Warnings

| ID    | Requirement                                                                                                                                                         | Priority |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-60 | **Warning Badge Placement**: Warnings shall appear as visible badges in the left case/source navigator next to affected cases or sources.                            | Must     |
| FR-61 | **Blocking Warning**: Missing SEG blocks QC save because segmentation QC cannot be completed without a loaded segmentation source.                                   | Must     |
| FR-62 | **Informational Warnings**: Missing VOI, wrong phase suspected, wrong side suspected, duplicate scan, and ambiguous phase are informational in v2.0.                 | Must     |
| FR-63 | **No Doctor Warning Resolution**: Doctors cannot mark warnings as resolved in v2.0. Warning resolution remains a technical-team or controlled correction responsibility. | Must  |
| FR-64 | **Warning Detail**: Detailed warning information may be shown in the bottom drawer or Case Data modal, but routine warnings shall not use blocking banners.          | Should   |

### 4.6 Case-Level QC Workflow

| ID    | Requirement                                                                                                                                              | Priority |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-70 | **Case-Level QC**: Segmentation QC is one decision per case, not per individual label, scan, source, overlay, or slice.                                  | Must     |
| FR-71 | **QC Module**: The QC decision interface shall be the QC module in the left panel, accessible at one click from the module selector. It shall always be reachable without page-level scroll. | Must     |
| FR-72 | **QC Actions**: Required actions are Accept, Needs correction, Reject, and Cannot assess.                                                                | Must     |
| FR-73 | **Primary Action**: Save & Next is the primary QC action. It saves the selected case-level QC decision and moves to the next case in the current order.   | Must     |
| FR-74 | **Needs Correction Queue**: Selecting Needs correction automatically adds the case to the correction queue.                                               | Must     |
| FR-75 | **Optional Comment**: A reviewer comment is optional for all QC states, including Needs correction.                                                       | Must     |
| FR-76 | **Loaded Source Gate**: Save QC shall be blocked if no source is loaded.                                                                                 | Must     |
| FR-77 | **Missing SEG Gate**: Save QC shall be blocked when Missing SEG is active for the required segmentation review context.                                  | Must     |
| FR-78 | **Curation Audit Artifacts**: Case-level QC decisions are appended to `curation_review.csv` or equivalent audit store.                                  | Must     |

### 4.7 Case Data Modal

| ID    | Requirement                                                                                                                                                 | Priority |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-80 | **Case Data Modal**: Case Data shall be an overlay modal opened from the left panel, not a full route in v2.0.                                                | Must     |
| FR-81 | **Categorized Report Style**: Case Data shall use a categorized report style and shall not present `database.csv` as a spreadsheet-like table.                | Must     |
| FR-82 | **Case Data Sections**: Required sections are Case Summary, Imaging Availability, Segmentation & VOI, and QC History.                                       | Must     |
| FR-83 | **Metadata Search**: Case Data shall provide metadata search across displayed and expandable metadata fields.                                                | Should   |
| FR-84 | **Raw Fields Hidden**: Raw `database.csv` fields are hidden by default and available only through advanced disclosure.                                      | Must     |
| FR-85 | **Technical Paths Hidden**: Technical paths are hidden by default and shall not be needed for routine review.                                                | Must     |
| FR-86 | **No Export in v2.0**: Case Data shall not provide export functionality in v2.0.                                                                            | Must     |

### 4.8 Persistence, Settings & Authentication

| ID    | Requirement                                                                                                                    | Priority |
| ----- | ------------------------------------------------------------------------------------------------------------------------------ | -------- |
| FR-90 | **Persist Last Case**: Store last viewed case ID per dataset so the user resumes where they left off.                          | Should   |
| FR-91 | **Persist W/L Settings**: Save last-used window/level values per dataset.                                                      | Should   |
| FR-92 | **Persist Layer Visibility**: Save layer on/off and opacity settings.                                                          | Should   |
| FR-93 | **Settings Storage**: Preferences are persisted in `<dataset>/.webui/settings.json` or configured external state directory.    | Should   |
| FR-94 | **No Source Data Mutation for Visualization**: Viewer settings and visualization transforms shall not modify NIfTI, SEG, VOI, masks, `manifest.csv`, or `database.csv`. | Must     |
| FR-95 | **Simple Auth**: A single shared bearer token protects API routes (`/api/*`, excluding `/api/health`). Token is configured via environment variable (`RADIOLOGY_UI_TOKEN`). | Should |
| FR-96 | **Session Persistence**: Auth token is memory-only by default; optional browser persistence via `VITE_AUTH_TOKEN_STORAGE=local`. | Should |
| FR-97 | **Medical Metadata Safety**: If direct identifiers or sensitive metadata are present, the UI shall hide nonessential sensitive fields by default and place them in Case Data advanced metadata. | Should |

---

## 5. Controlled Dataset Correction

Controlled Dataset Correction resolves the distinction between routine medical QC and data-correction operations that may mutate dataset metadata or dataset organization.

Routine QC is **curation-state writing**. It records the case-level decision, optional comment, reviewer, timestamp, and queue state without moving files or changing `database.csv`.

Phase correction and scan/VOI exclusion are **controlled dataset correction operations**. They are not casual toggles and must never occur silently.

### 5.1 Controlled Correction Scope

| Operation | Requirement | Priority |
| --------- | ----------- | -------- |
| CDC-01 | **Phase Correction**: The reviewer may request a phase change for a scan/VOI source. Applying the correction may update `database.csv` and relocate affected VOI files only through the controlled operation. | Must |
| CDC-02 | **Scan Exclusion**: The reviewer may mark a scan as excluded from downstream use. Applying the correction shall update controlled metadata/state and shall not delete image data silently. | Must |
| CDC-03 | **VOI Exclusion**: The reviewer may mark a VOI image or mask as excluded from downstream use. Applying the correction shall update controlled metadata/state and shall not delete VOI data silently. | Must |
| CDC-04 | **No Voxel Editing**: Controlled corrections shall not modify voxel data inside NIfTI, SEG, or VOI files. | Must |
| CDC-05 | **Mutation Gate**: Controlled corrections that mutate `database.csv` or relocate files require an explicit enablement gate such as `ALLOW_DATA_MUTATIONS=true`. | Must |

### 5.2 database.csv Update Policy

When a controlled correction is applied:

* `database.csv` may be updated only for fields directly affected by the confirmed operation, such as canonical phase, exclusion flags, correction status, reviewer, and timestamp.
* Original values such as `raw_phase` shall be preserved.
* Before/after values shall be written to the correction audit log before the operation is considered complete.
* The write shall be atomic where feasible, for example by writing a temporary file and replacing the original after validation.
* A pre-change backup of `database.csv` is recommended before the first correction in a session or batch.

### 5.3 VOI Relocation Policy

When a phase correction affects VOI paths:

* VOI image and mask files may be moved to the corrected phase folder only through the controlled correction operation.
* The operation shall compute all affected source and destination paths before applying changes.
* The operation shall refuse to overwrite existing files unless an explicit collision policy is implemented and audited.
* The operation shall log every moved, skipped, or failed VOI path.
* If the dataset mount is read-only, the operation shall fail safely and preserve a curation-state record explaining the failure.

### 5.4 Confirmation Model

Controlled corrections require explicit confirmation before applying.

The confirmation prompt shall summarize:

* operation type;
* case ID;
* scan index;
* scope and side when relevant;
* before and after phase values or exclusion state;
* affected `database.csv` fields;
* affected VOI paths, if any;
* reviewer identity;
* warning that the operation can change dataset metadata or relocate VOI files.

Normal QC Save & Next shall not show a confirmation modal. Confirmation is required only for controlled dataset correction operations.

### 5.5 Audit Log Fields

Each controlled correction shall append an audit record to `dataset_corrections.json` or an equivalent append-only store with at least:

| Field | Description |
| ----- | ----------- |
| `correction_id` | Unique operation ID |
| `dataset_id` | Dataset identifier |
| `case_id` | Case identifier |
| `source_row_id` | `database.csv` row reference when available |
| `operation` | phase_correction, exclude_scan, exclude_voi |
| `before` | Before values for affected fields and paths |
| `after` | Requested/applied values for affected fields and paths |
| `affected_paths` | Paths read, moved, written, skipped, or failed |
| `reviewer` | Reviewer name or ID |
| `confirmed_at` | Timestamp when reviewer confirmed |
| `applied_at` | Timestamp when operation completed or failed |
| `result` | applied, skipped, failed, partially_applied |
| `errors` | Error messages or validation failures, if any |
| `validation_before` | Validation summary before correction, if available |
| `validation_after` | Validation summary after correction refresh, if available |

### 5.6 Validation Refresh

After a controlled correction:

* backend validation shall refresh `database.csv` status, affected case inventory, source path resolution, and warning badges;
* the Main Review Screen shall reload affected case/source state;
* stale warnings shall be recomputed rather than manually marked as resolved by the doctor;
* failure to refresh validation shall be shown as a technical warning and logged.

### 5.7 Rollback and Backup Recommendation

Where feasible, the system should create or require a backup before applying corrections that mutate `database.csv` or move VOI files.

Rollback may be implemented as:

* restoring a backed-up `database.csv`;
* moving VOI files back according to the correction audit record;
* replaying the `before` values from the audit log.

If automated rollback is not implemented in v2.0, the UI and documentation shall state that correction audit logs and backups are required for manual recovery.

---

## 6. Non-Functional Requirements

| ID     | Requirement                                                                                                                                                    | Target                            |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| NFR-01 | **First Slice Visible**: After selecting a case/inventory item, the first 2D slice renders in < 3 seconds for a typical volume.                                | < 3 s                             |
| NFR-02 | **Slice Navigation Latency**: Changing a single slice updates the view in < 200 ms when cached and feasible.                                                   | < 200 ms                          |
| NFR-03 | **3D Mesh Generation**: Initial marching-cubes computation completes in < 5 seconds for typical segmentation size, when 3D is used.                            | < 5 s                             |
| NFR-04 | **Memory Footprint**: Backend holds a limited number of volumes in memory simultaneously using LRU cache.                                                      | Configurable; default ≤ 2 volumes |
| NFR-05 | **Container Image Size**: Final OCI image should remain reasonably small for local/HPC deployment.                                                             | ≤ 1.5 GB target                   |
| NFR-06 | **Routine Review Read-Only**: Routine QC workflow shall not modify NIfTI, SEG, VOI, `manifest.csv`, or `database.csv`; it writes only curation state.          | Mandatory                         |
| NFR-07 | **Controlled Curation Writes**: Only explicit curation-state actions may write to curation files or configured state storage.                                  | Mandatory                         |
| NFR-08 | **Auditability**: Every curation decision and controlled correction shall include reviewer, timestamp, target, status/result, and source row reference when available. | Mandatory                    |
| NFR-09 | **Privacy / Local-Only**: No data leaves the host. No telemetry, analytics, or external API calls.                                                             | Mandatory                         |
| NFR-10 | **Browser Compatibility**: Chrome 100+, Firefox 100+, Edge 100+.                                                                                               | Must                              |
| NFR-11 | **Maintainability**: Backend services are modular. Frontend uses typed TypeScript with component isolation.                                                    | Must                              |
| NFR-12 | **Logging**: Backend logs requests and errors to stdout. Log level configurable via env var.                                                                   | Should                            |
| NFR-13 | **Metadata Scalability**: Wide `database.csv` files shall not be fully sent to list views by default. Backend shall provide compact projections.               | Must                              |
| NFR-14 | **UX Minimalism**: The default UI shall expose only the controls needed for medical curation. Advanced metadata and technical provenance shall be collapsible. | Must                              |
| NFR-15 | **Target Desktop Layout**: At `1440x1000`, the Main Review Screen shall show the left module panel and fixed 2x2 viewer workspace without page-level scrolling. No right panel. No bottom drawer by default.   | Must                              |
| NFR-16 | **Image Geometry Safety**: UI rendering shall preserve physical CT aspect ratio when spacing is available, use viewer-effective isotropic VOI spacing by default, never stretch slices to fill panes, and keep all transforms viewer-only and non-persistent. | Must                              |

---

## 7. User Interface Specification

### 7.1 Primary Screen Flow

The v2.0 UI has two primary user-facing screens:

```text
Dataset Load Screen -> Main Review Screen -> Save & Next -> next case
```

The Main Review Screen contains persistent case navigation and all routine review actions. The `/cases` page is not a primary product surface in v2.0. Case Data is a modal, not a full route.

Routing expectations:

| Route | Role |
| ----- | ---- |
| `/` | Dataset Load Screen. |
| `/datasets/:dataset_id/review/:case_id?` | Main Review Screen with optional active case. |
| `/cases` | Legacy, technical, or non-primary surface only. |
| Case Data | Modal state inside Main Review Screen, not a standalone route. |

### 7.2 Dataset Load Screen

The Dataset Load Screen answers:

* which dataset is active;
* whether `database.csv` is ready for review;
* how many cases exist;
* how many cases have warnings or saved QC decisions;
* whether SEG and VOI data are available;
* whether the user can Start Review or Resume Review.

Dataset path setup and validation detail are available but visually secondary. The path field is a configuration control, not the routine review workflow.

The Dataset Load Screen shall provide:

* Active Dataset Card with dataset name, `database.csv` status, case count, reviewed count, warnings, SEG/VOI availability, Start Review, and Resume Review;
* Dataset Selection Card with Browse dataset folder and Browse `database.csv` actions backed by the safe backend browser;
* Manual Path Entry labeled `Backend/server path, not local browser path`;
* Validation Progress Modal with Success / Warnings / Errors summary.

Validation shall parse `database.csv`, check required columns, count rows and unique cases where possible, sample referenced CT/SEG/VOI files, and summarize basic availability. It shall not mutate CT, VOI, SEG, mask, `manifest.csv`, or `database.csv` files.

When `database.csv` is selected directly, workspace activation shall persist both the inferred dataset root and the selected `database.csv` path. Main Review database-backed endpoints shall use that selected CSV path for the active workspace.

### 7.3 Main Review Screen Layout

At `1440x1000`, the Main Review Screen shall use a two-zone layout with proportions inspired by 3D Slicer spatial architecture (no 3D Slicer assets or branding are copied):

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Compact top header (≤44px): dataset | case | source | QC status | warnings │
├───────────────────────────────────────┬───────────────────────────────────┤
│ Left Module Panel (380–440px)         │ Viewer Workspace (fills remainder)   │
│ [Module: Review ▼]                    │                                      │
│                                       │ ┌──────────────┬──────────────┐      │
│ Module content (internally scrollable)│ │ AXI          │ COR          │      │
│                                       │ ├──────────────┼──────────────┤      │
│ Footer: [Case] [Previous] [Next]       │ │ SAG          │ 3D slot      │      │
│                                       │ └──────────────┴──────────────┘      │
└───────────────────────────────────────┴───────────────────────────────────┘
```

Rules:

* left module panel is always visible and never collapsed in v1;
* target width at `1440px`: `clamp(340px, 27vw, 480px)` (~380–440px); minimum 340px; maximum 480px;
* no fixed right QC panel — QC is the QC module in the left panel;
* no bottom drawer visible by default — Inventory / Warnings / History are left panel modules;
* 2x2 viewer uses all remaining width and height without page-level scrolling;
* viewer panels are rectangular and fill available space — complete CT images preserve physical aspect ratio and VOI images use isotropic viewer spacing inside each panel using contain-fit;
* no vertical tabs and no thumbnails in v2.0.

### 7.4 Left Module Panel

The left module panel is the main non-image control area. It replaces the previous left panel + right QC panel + bottom drawer with one wider, internally scrollable panel organized by module.

Target width at `1440px`: `clamp(340px, 27vw, 480px)` (approximately 380–440px). Minimum 340px. Maximum 480px.

A module selector (dropdown) at the top switches between:

| Module | Content |
| --- | --- |
| Review | Displayed source summary, warning count, QC shortcut |
| Sources | Source matrix with phase filters and scan-grouped CT / VOI L / VOI R cards |
| QC | QC status buttons, comment, Save & Next, Save only |
| Case Data | Case/patient chips, Open Case Data modal button |
| Warnings | Warning detail (WarningsTab) |
| History | Curation history (HistoryTab) |

Sticky footer: full case selector plus Previous/Next navigation always visible. These navigation controls do not auto-save QC state.

### 7.5 Viewer Grid

Default layout:

* fixed 2x2 grid;
* AXI, COR, SAG, and 3D slot;
* panels remain stable and do not disappear;
* 3D slot is available on demand and is not dominant by default;
* the viewer is a single **unified image workspace** — panes are separated by 1 px near-invisible dividers; there are no card borders, drop shadows, or rounded corners on individual panes; the workspace feels like one continuous dark canvas subdivided into four sections.

Image rules:

* preserve complete CT physical aspect ratio when spacing is available;
* use viewer-effective isotropic spacing `[1,1,1]` for VOI sources by default in MPR and 3D;
* never stretch CT or VOI slices to fill a pane;
* default fit mode is fit entire slice inside pane using contain-fit behavior;
* use physical voxel spacing for MPR views: axial X/Y, coronal X/Z, sagittal Y/Z;
* fit complete CT and VOI sources independently by default so VOIs remain inspectable;
* viewer pane containers are rectangular and fill the available 2x2 grid space — do not force 1:1 square panes; pane shape depends on screen geometry;
* pane geometry and pane positions remain stable across case, scan, phase, scope, side, and VOI changes;
* black pane background absorbs unused space when image aspect ratio leaves empty bands;
* image content uses contain-fit inside each pane — the image itself stays proportional to physical spacing regardless of pane shape;
* reserve fixed slider space at pane bottom;
* auto-center on case, scan, phase, scope, or side change;
* zoom and pan are independent per pane;
* fitting, scaling, interpolation, zoom, and pan are viewer-only and non-persistent;
* visualization changes shall not modify CT, VOI, SEG, mask files, `manifest.csv`, or `database.csv`;
* each pane header is a minimal strip (≈22 px) showing only the axis label badge and expand toggle — no verbose captions or padding that reduce image area.

### 7.6 CT to VOI Comparison

In v2.0, CT to VOI comparison happens inside the Main Review Screen through fast toggling between Complete and VOI scope in the fixed 2x2 viewer. The left panel keeps the active scan, phase, scope, and side visible while toggling.

Fully synchronized simultaneous side-by-side CT/VOI comparison, phase comparison, L/R comparison, and dedicated comparison layouts are advanced comparison features and are out of scope for v2.0 unless explicitly added later.

### 7.7 QC Module (Left Panel)

QC is the QC module in the left panel module selector, not a fixed right panel.

Required actions:

* Accept;
* Needs correction;
* Reject;
* Cannot assess.

Primary action:

* Save & Next.

Rules:

* segmentation QC is one decision per case;
* Needs correction automatically adds the case to the correction queue;
* no confirmation modal for normal QC save;
* comment is optional in all states;
* Save QC is blocked if no source is loaded;
* Missing SEG blocks QC and shows a blocking alert inside the QC module.

### 7.8 Warnings

Warnings appear as visible badges in the left navigator.

Warning behavior:

| Warning | v2.0 behavior |
| ------- | ------------- |
| Missing SEG | Blocks QC. |
| Missing VOI | Informational. |
| Wrong phase suspected | Informational unless controlled correction is applied. |
| Wrong side suspected | Informational. |
| Duplicate scan | Informational. |
| Ambiguous phase | Informational. |

Doctors cannot mark warnings as resolved in v2.0. Warning recalculation happens through validation refresh or controlled correction.

### 7.9 Case Data Modal

Case Data replaces the old full Case Dossier page requirement.

Case Data is an overlay modal activated from the left review panel. It uses a categorized clinical report style and must not behave like a spreadsheet.

Required sections:

* Case Summary;
* Imaging Availability;
* Segmentation & VOI;
* QC History.

Required behavior:

* metadata search;
* raw fields hidden by default;
* technical paths hidden by default;
* active warnings visible;
* no export in v2.0.

### 7.10 Bottom Drawer

The bottom drawer is **not visible by default** in v2.0. Inventory, Warnings, and History have been migrated into the left module panel as dedicated modules, giving the 2x2 viewer workspace maximum screen height.

The bottom drawer component is preserved in the codebase as an optional hidden/advanced feature but must not reduce viewer height in the default review layout.

### 7.11 Default Case Opening Behavior

When a case is opened, the viewer shall default to:

| Item     | Default                                                                                      |
| -------- | -------------------------------------------------------------------------------------------- |
| Scan     | scan `0` complete CT if available                                                            |
| Scope    | Complete scan                                                                                |
| Viewer   | Fixed 2x2 grid with AXI, COR, SAG, 3D slot                                                    |
| Overlay  | SEG on if available                                                                          |
| Phase    | Configurable project priority; default `NP`, then `CMP`, then `NC`, then `EXC`, then `UNK` |
| side     | Only auto-selected in VOI mode if one side exists                                            |

### 7.12 Color Scheme

Dark theme may be preserved from v1.2.

| Element            | Color     |
| ------------------ | --------- |
| Background         | `#1e1e1e` |
| Panel background   | `#121212` |
| Panel borders      | `#333`    |
| Text primary       | `#ddd`    |
| Text secondary     | `#aaa`    |
| Axial crosshair    | `yellow`  |
| Coronal crosshair  | `red`     |
| Sagittal crosshair | `green`   |
| Kidney overlay     | light blue |
| Tumor overlay      | orange/red |
| Cyst overlay       | green     |
| QC warning         | amber     |
| QC rejected/error  | red       |
| QC accepted        | green     |

### 7.13 Interaction Summary

| Action                   | Input                                | Effect                                  |
| ------------------------ | ------------------------------------ | --------------------------------------- |
| Navigate slice           | Scroll wheel / slider                | Update slice index in current view      |
| Adjust W/L               | Right-click drag or numeric input    | Horizontal=width, vertical=level        |
| Pan                      | Middle-click drag or Shift+left      | Move viewport origin                    |
| Zoom                     | Ctrl/Cmd+scroll on panel             | Zoom in/out centered on cursor          |
| Reset view fit           | `Fit` button / double-click viewport | Reset panel pan+zoom to fitted defaults |
| Crosshair click          | Left-click on 2D view                | Sets crosshair position, syncs views    |
| Expand panel             | Expand button / header double-click  | Panel fills viewer area                 |
| Restore grid             | Restore button / Esc                 | Return to prior layout                  |
| Overlay settings         | Overlay button in viewer             | Opens anchored viewer popover           |
| Toggle layer             | Checkbox/button in overlay popover   | Show/hide label in overlay              |
| Change opacity           | Slider                               | Adjust alpha for selected label         |
| Filter case navigator    | Search/filter controls               | Restrict case list                      |
| Switch case              | Case navigator click                 | Load selected case                      |
| Load next case           | Button click                         | Navigate to next filtered case          |
| Switch scan              | Source navigator                     | Load selected scan                      |
| Switch phase             | Phase chip                           | Load selected phase source              |
| Switch scope             | Complete/VOI toggle                  | Switch source between full scan and VOI |
| Switch side              | Side chip/toggle                     | Load selected L/R VOI source            |
| Phase correction         | Controlled correction action         | Confirm, apply, log, refresh validation |
| Exclude scan/VOI         | Controlled correction action         | Confirm, apply, log, refresh validation |
| Save & Next              | Primary QC button                    | Save case-level QC and load next case   |
| Needs correction         | QC action                            | Save QC and queue case for correction   |

---

## 8. Technical Architecture

### 8.1 Stack Selection

| Layer        | Technology                                               | Rationale                                                      |
| ------------ | -------------------------------------------------------- | -------------------------------------------------------------- |
| Backend      | **Python 3.12 + FastAPI**                                | Native nibabel/numpy stack; lightweight API + static serving   |
| Frontend     | **React 19 + TypeScript + MUI**                          | Typed UI and reusable component primitives                     |
| 2D Rendering | **Server-rendered PNG slices + React interaction layer** | Preserve notebook-aligned and current viewer behavior          |
| 3D Rendering | **three.js via @react-three/fiber + GLTFLoader**         | Optional orientation support using existing approach           |
| Bundler      | **Vite 7**                                               | Fast TypeScript builds and dev-server proxy                    |
| Container    | **Multi-stage OCI image**                                | Node build stage + Python runtime stage, non-root runtime user |

### 8.2 Backend Architecture

```text
backend/
├── app/
│   ├── main.py                # FastAPI app, router mounting, static SPA serving
│   ├── config.py              # Settings from env vars
│   │
│   ├── middleware/
│   │   └── auth.py            # Bearer auth middleware for /api/*
│   │
│   ├── api/
│   │   ├── workspace.py       # Workspace activation + database status
│   │   ├── datasets.py        # Dataset summary and legacy endpoints
│   │   ├── cases.py           # v2.0 case summaries, active case, inventory
│   │   ├── case_data.py       # Case Data modal metadata payload
│   │   ├── slices.py          # POST load + GET /api/slice/{axis}/{index}
│   │   ├── mesh.py            # GET /api/mesh/{label}
│   │   ├── curation.py        # case-level QC decisions and correction queue
│   │   ├── corrections.py     # controlled phase/exclusion corrections
│   │   └── settings.py        # GET/PUT /api/settings
│   │
│   ├── services/
│   │   ├── database.py        # database.csv loading, validation, projections
│   │   ├── path_resolver.py   # Path resolution relative to dataset root
│   │   ├── qc_validator.py    # Missing files, duplicates, mismatch warnings
│   │   ├── discovery.py       # Legacy folder scanning fallback
│   │   ├── nifti_loader.py    # nibabel load + RAS reorientation + HU normalize
│   │   ├── numpy_loader.py    # Legacy .npy VOI load
│   │   ├── mask_loader.py     # Segmentation mask load + label extraction
│   │   ├── slice_renderer.py  # Extract 2D slice as PNG with overlay
│   │   ├── mesh_generator.py  # Marching cubes → GLB/OBJ mesh
│   │   ├── settings_store.py  # JSON-based persistence
│   │   ├── curation_store.py  # curation_review.csv + correction_queue.csv
│   │   ├── correction_store.py # dataset_corrections.json audit log
│   │   ├── correction_service.py # confirmed database/VOI correction operations
│   │   └── volume_cache.py    # LRU series cache + expiring load handles
│   │
│   └── models/
│       ├── dataset.py         # Dataset/case/series/volume response models
│       ├── database.py        # Database row projections and validation models
│       ├── curation.py        # case-level QC and correction queue models
│       ├── correction.py      # controlled dataset correction models
│       └── settings.py        # Per-dataset viewer settings payload
│
└── requirements.txt
```

**Key backend design decisions:**

* **database.csv-first API**: v2.0 endpoints use database-backed case summaries and inventory rows.
* **Legacy fallback**: existing discovery logic remains available when `database.csv` is absent.
* **Compact projections**: list views return only necessary fields, not every database column.
* **Case Data endpoint**: categorized metadata for the modal is available on demand; raw fields and technical paths are hidden by default in the UI.
* **Path validation**: missing/unreadable files become QC warnings.
* **Load handle contract**: viewer loading may reuse existing cache/load-handle mechanism.
* **Curation-state store**: routine QC decisions are written separately from source metadata.
* **Controlled corrections**: phase correction and scan/VOI exclusion are handled by a separate confirmed workflow with audit logging and validation refresh.

### 8.3 Frontend Architecture

```text
frontend/
├── src/
│   ├── App.tsx
│   ├── main.tsx
│   │
│   ├── pages/
│   │   ├── DatasetLoadScreen.tsx
│   │   └── MainReviewScreen.tsx
│   │
│   ├── components/
│   │   ├── LoginDialog.tsx
│   │   └── viewer/
│   │       ├── TopReviewBar.tsx
│   │       ├── LeftReviewPanel.tsx
│   │       ├── CaseNavigator.tsx
│   │       ├── SourceNavigator.tsx
│   │       ├── InventoryTab.tsx
│   │       ├── OverlayControls.tsx
│   │       ├── WarningBadges.tsx
│   │       ├── CaseDataModal.tsx
│   │       ├── BottomDrawer.tsx
│   │       ├── RightQcPanel.tsx
│   │       ├── ViewerGrid2x2.tsx
│   │       ├── ExpandablePanel.tsx
│   │       ├── SliceView.tsx
│   │       ├── Surface3DView.tsx
│   │       ├── SliceSlider.tsx
│   │       ├── WindowLevelControl.tsx
│   │       ├── LayerToggle.tsx
│   │       ├── OpacitySlider.tsx
│   │       ├── useSliceNavigation.ts
│   │       └── useWindowLevel.ts
│   │
│   ├── hooks/
│   │   ├── useSettings.ts
│   │   ├── useCaseInventory.ts
│   │   ├── useCurationState.ts
│   │   └── useControlledCorrection.ts
│   │
│   ├── services/
│   │   └── api.ts
│   │
│   └── styles/
│       └── theme.ts
│
├── package.json
├── tsconfig.json
└── vite.config.ts
```

**Key frontend design decisions:**

* **Two-screen routing**: Dataset Load Screen -> Main Review Screen.
* **Main Review Screen**: routine image review, source navigation, warning inspection, Case Data access, and QC happen in one fixed cockpit.
* **Progressive disclosure**: show simple controls by default; advanced metadata collapsed.
* **Viewer reuse**: current MPR components should be reused as much as possible.
* **Navigator-driven loading**: viewer source is selected through direct left-panel source cards representing phase + scan + scope + side, not raw file browsing or disconnected dropdown combinations.
* **Case Data modal**: categorized metadata is displayed in an overlay modal, not a full page.
* **Curation panel**: QC actions are case-level, structured, and auditable.
* **Tab discipline**: bottom drawer tabs may expose inventory, warnings, or history, but must not hide the MPR viewer or primary QC decision panel.

### 8.4 API Contract (Summary)

| Method | Endpoint                                                             | Returns                 | Description                                 |
| ------ | -------------------------------------------------------------------- | ----------------------- | ------------------------------------------- |
| GET    | `/api/health`                                                        | `{"status":"ok"}`       | Backend health check                        |
| GET    | `/api/workspace`                                                     | `WorkspaceStatus`       | Get active dataset workspace status, including selected `database_csv_path` when configured |
| PUT    | `/api/workspace`                                                     | `WorkspaceStatus`       | Validate and activate one dataset folder, optionally with a selected `database_csv_path` |
| DELETE | `/api/workspace`                                                     | `WorkspaceStatus`       | Clear active dataset workspace              |
| GET    | `/api/dataset-browser/roots`                                         | `DatasetBrowserRoots`   | Allowed backend roots for setup browsing    |
| GET    | `/api/dataset-browser/list?path=...`                                 | `DatasetBrowserList`    | One-level listing inside allowed roots      |
| POST   | `/api/workspace/validate-selection`                                  | `SelectionValidation`   | Lightweight validation and safe activation  |
| GET    | `/api/datasets`                                                      | `Dataset[]`             | Dataset summary for active workspace        |
| GET    | `/api/datasets/{dataset_id}/database/validation`                     | `DatabaseValidation`    | database.csv validation and warning summary |
| GET    | `/api/datasets/{dataset_id}/cases`                                   | `CaseSummary[]`         | One row per case_id                         |
| GET    | `/api/datasets/{dataset_id}/cases/{case_id}/inventory`               | `CaseInventory`         | Phase/scan/scope/side availability          |
| GET    | `/api/datasets/{dataset_id}/cases/{case_id}/case-data`               | `CaseData`              | Categorized metadata for Case Data modal    |
| POST   | `/api/datasets/{dataset_id}/cases/{case_id}/load?row_id=...&scope=...` | `VolumeInfo`            | Load selected inventory item into cache     |
| GET    | `/api/slice/{axis}/{index}?load_handle=...&ww=...&wl=...&layers=...` | `image/png`             | Render 2D slice from cached volume          |
| GET    | `/api/mesh/{label}?load_handle=...&smooth=true`                      | `model/gltf-binary`     | Get 3D surface mesh for one label           |
| GET    | `/api/datasets/{dataset_id}/curation/cases/{case_id}/history`        | `CurationDecision[]`    | Get curation history for case               |
| POST   | `/api/datasets/{dataset_id}/curation/decisions`                      | `CurationDecision`      | Save case-level QC decision                 |
| GET    | `/api/datasets/{dataset_id}/curation/correction-queue`               | `CorrectionQueue`       | List items needing external correction      |
| GET    | `/api/datasets/{dataset_id}/curation/correction-queue.csv`           | `text/csv`              | Export correction queue                     |
| POST   | `/api/datasets/{dataset_id}/corrections/confirm`                     | `CorrectionPreview`     | Preview controlled correction before apply  |
| POST   | `/api/datasets/{dataset_id}/corrections/apply`                       | `CorrectionResult`      | Apply confirmed phase/exclusion correction  |
| GET    | `/api/settings`                                                      | `Settings`              | Get persisted viewer preferences            |
| PUT    | `/api/settings`                                                      | `Settings`              | Save persisted viewer preferences           |

Legacy endpoints for `/patients`, `/series`, `/review/apply`, and any `/cases` page route may remain for compatibility or technical/admin mode, but shall not be the primary v2.0 medical curation workflow.

### 8.5 Data Flow

```text
[Browser]                          [FastAPI Backend]                         [Filesystem]
    │                                     │                                       │
    │  PUT /api/workspace                 │                                       │
    │ ──────────────────────────────────► │  validate dataset path                │
    │                                     │  inspect database.csv                  │
    │                                     │ ─────────────────────────────────────► │
    │  ◄────── WorkspaceStatus            │                                       │
    │                                     │                                       │
    │  GET /api/.../cases                 │                                       │
    │ ──────────────────────────────────► │  database.csv compact projection       │
    │  ◄────── CaseSummary[]              │                                       │
    │                                     │                                       │
    │  GET /api/.../cases/{id}/inventory  │                                       │
    │ ──────────────────────────────────► │  resolve rows + paths + warnings       │
    │  ◄────── CaseInventory              │                                       │
    │                                     │                                       │
    │  POST /api/.../volume/load          │                                       │
    │ ──────────────────────────────────► │  load selected scan/VOI + mask         │
    │  ◄────── VolumeInfo{load_handle,...}│                                       │
    │                                     │                                       │
    │  GET /api/slice/... ?load_handle=H  │                                       │
    │ ──────────────────────────────────► │  cache lookup + render PNG             │
    │  ◄────── image/png                  │                                       │
    │                                     │                                       │
    │  POST /api/.../curation             │                                       │
    │ ──────────────────────────────────► │  validate curation decision            │
    │                                     │  append curation_review.csv            │
    │                                     │ ─────────────────────────────────────► │
    │  ◄────── saved decision             │  routine QC: no source/database mutation│
    │                                     │                                       │
    │  POST /api/.../corrections/apply    │                                       │
    │ ──────────────────────────────────► │  confirm + audit controlled correction │
    │                                     │  update database.csv / move VOI if gated│
    │                                     │  refresh validation                     │
    │                                     │ ─────────────────────────────────────► │
    │  ◄────── CorrectionResult           │                                       │
```

---

## 9. Deployment

### 9.1 Dockerfile

v2.0 may keep the existing multi-stage image strategy:

```dockerfile
FROM node:20-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN addgroup --system app && adduser --system --ingroup app app
COPY --chown=app:app backend /app/backend
COPY --chown=app:app --from=frontend-build /build/frontend/dist /app/static
EXPOSE 8000
WORKDIR /app/backend
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status==200 else 1)"
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 9.2 Native Docker/Podman

```bash
cp .env.example .env
# edit DATASET_DIR and optional RADIOLOGY_UI_TOKEN
# use read-only data mount when possible and separate WEBUI_STATE_DIR for curation outputs
docker compose up -d --build
```

### 9.3 udocker Runtime Path

Use `udocker` when native Docker/Podman is unavailable. The runtime contract is the same image and environment variables as native OCI runtime.

```bash
python udocker.py run \
  -p 8000:8000 \
  -v /path/to/data/dataset:/data:ro \
  -v /path/to/webui_state:/state:rw \
  -e RADIOLOGY_UI_TOKEN=mysecret \
  -e WEBUI_STATE_DIR=/state \
  radiology-ui:2.0
```

### 9.4 Configuration (Environment Variables)

| Variable                  | Default               | Description                                                               |
| ------------------------- | --------------------- | ------------------------------------------------------------------------- |
| `RADIOLOGY_UI_TOKEN`      | `""` (no auth)        | Bearer token for API protection (`/api/*`, except health)                 |
| `DATA_ROOT`               | `/data`               | Fallback/dev-only dataset root when workspace selection is not used       |
| `DATASET_DIR`             | empty                 | Optional backend-visible root included in Dataset Discovery roots; in Docker Compose this host value is mounted as `/data` |
| `DATASET_ROOTS`           | empty                 | Optional comma- or path-separator-delimited list of backend roots allowed for setup browsing |
| `WEBUI_STATE_DIR`         | empty                 | Optional external directory for curation/settings state                   |
| `LOG_LEVEL`               | `info`                | Python logging level                                                      |
| `ALLOW_DATA_MUTATIONS`    | `false`               | Enables controlled dataset correction operations that may update `database.csv` or relocate VOI files; routine QC does not require it |
| `PORT`                    | `8000`                | Uvicorn bind port                                                         |
| `STATIC_ROOT`             | `/app/static`         | Frontend static build directory served by backend                         |
| `VITE_AUTH_TOKEN_STORAGE` | `memory`              | Frontend token persistence mode (`memory` or `local`)                     |
| `PHASE_PRIORITY`          | `NP,CMP,NC,EXC,UNK` | Default phase selection order                                             |

### 9.5 Compose Host Variables (`.env`)

| Variable               | Default          | Description                                                      |
| ---------------------- | ---------------- | ---------------------------------------------------------------- |
| `DATASET_DIR`          | `./data/dataset` | Host parent directory or dataset directory mounted at `/data`    |
| `WEBUI_STATE_DIR_HOST` | `./webui_state`  | Host directory for curation outputs when data mount is read-only |
| `WEBUI_PORT`           | `8000`           | Host port mapped to container `8000`                             |

---

## 10. Future Versions (Out of Scope v2.0)

| Version | Feature                                                                  |
| ------- | ------------------------------------------------------------------------ |
| v2.1    | Side-by-side synchronized multi-phase comparison                         |
| v2.1    | Fully synchronized simultaneous CT to VOI side-by-side comparison        |
| v2.1    | Improved correction queue workflow for external 3D Slicer handoff        |
| v2.1    | More detailed reviewer dashboard and curation progress summaries         |
| v2.2    | Optional structured export package for correction teams                  |
| v2.2    | Optional report generation for case review meetings                      |
| v3.0    | DICOM → NIfTI conversion trigger from UI, if still desired               |
| v3.0    | VOI preprocessing trigger from UI, if still desired                      |
| v3.0    | Raw array streaming + client-side rendering for smoother slice scrolling |
| v3.0    | Annotation / measurement tools, if medically required                    |
| v3.0    | Multi-series co-registration / overlay                                   |
| v3.0    | Volumetric rendering in addition to surface mesh                         |
| v3.0    | Multi-user sessions with role-based access                               |

---

## 11. Acceptance Criteria

| #  | Criterion                                                                                                                           | Verified by       |
| -- | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| 1  | The application presents only two primary user-facing screens: Dataset Load Screen and Main Review Screen.                          | UX/manual test    |
| 2  | The `/cases` page, if present, is not required for routine v2.0 review and is marked legacy, technical, or non-primary.             | UX/manual test    |
| 3  | User selects a dataset folder or `database.csv`, validation reaches 100%, and the user sees `database.csv` status, row count, case count, reviewed count when available, and warning count. | Manual/API test |
| 3a | Backend browsing lists allowed roots only and rejects paths outside those roots.                                                        | API test         |
| 3b | Blocking selection errors prevent activation; warnings allow activation by default.                                                     | API/frontend test |
| 4  | At `1440x1000`, the Main Review Screen shows left panel, fixed 2x2 viewer, and right QC panel without page-level scrolling.         | Screenshot test   |
| 5  | The left panel is always visible and includes case navigator, direct source navigator, warning badges, and Case Data action; overlay settings remain in the viewer popover. | Frontend test |
| 6  | The right QC panel is always visible and exposes Accept, Needs correction, Reject, Cannot assess, optional comment, and Save & Next. | Frontend test     |
| 7  | Opening a case loads scan `0` complete CT by default when available.                                                                 | Manual/API test   |
| 8  | Fixed 2x2 viewer shows AXI top-left, COR top-right, SAG bottom-left, and 3D bottom-right; pane positions and geometry stay stable across source switches. | Screenshot test   |
| 9  | Viewer defaults to fit-to-panel, reserves slider space, auto-centers on case/scan/phase/scope/side changes, preserves physical CT fit and isotropic VOI fit, and preserves independent zoom/pan per panel. | Manual regression |
| 10 | CT to VOI comparison happens inside the Main Review Screen through fast Complete/VOI toggling; no separate comparison route is required in v2.0. | Manual test |
| 11 | Overlay controls remain in a viewer popover and support show/hide, opacity, filled mode, contour-only mode, compact HUD status, and usable click targets/tooltips. | Manual test       |
| 12 | Case-level QC is one decision per case, not per scan, label, source, overlay, or slice.                                             | Manual/API test   |
| 13 | Save & Next saves the selected case-level QC decision and loads the next case.                                                       | Manual/API test   |
| 14 | Needs correction automatically adds the case to the correction queue.                                                               | Manual/API test   |
| 15 | Save QC is blocked when no source is loaded.                                                                                        | API/frontend test |
| 16 | Missing SEG blocks QC; Missing VOI, wrong phase suspected, wrong side suspected, duplicate scan, and ambiguous phase are informational in v2.0. | Manual/API test |
| 17 | Warning badges are visible in the left navigator, and doctors cannot mark warnings as resolved in v2.0.                             | Manual test       |
| 18 | Case Data opens as a modal from the left panel, is categorized and searchable, and is not spreadsheet-like.                         | Manual test       |
| 19 | Case Data includes Case Summary, Imaging Availability, Segmentation & VOI, and QC History.                                         | Manual test       |
| 20 | Raw metadata fields and technical paths are hidden by default.                                                                      | Manual test       |
| 21 | No routine review workflow requires raw path interaction.                                                                           | Manual test       |
| 22 | Phase correction requires explicit confirmation before apply.                                                                       | Manual/API test   |
| 23 | Phase correction and scan/VOI exclusion are logged with before/after values, affected paths, reviewer, timestamp, and result.       | File/API test     |
| 24 | Controlled corrections refresh validation and update affected warning badges/state after apply.                                     | Manual/API test   |
| 25 | Routine QC writes curation state only and does not mutate `database.csv` or move files.                                             | Audit/checksum    |
| 26 | With `RADIOLOGY_UI_TOKEN` set, unauthenticated `/api/*` access is blocked except `/api/health`.                                    | Manual/API test   |

---

## 12. Glossary

| Term                          | Definition                                                                                                           |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| **MPR**                       | Multi-Planar Reconstruction — axial, coronal, sagittal slice views                                                   |
| **W/L**                       | Window Width / Window Level — intensity windowing for CT display                                                     |
| **HU**                        | Hounsfield Units — standard CT intensity scale                                                                       |
| **RAS**                       | Right-Anterior-Superior — standard neuroimaging orientation convention                                               |
| **VOI**                       | Volume of Interest — cropped and resampled sub-volume around a structure                                             |
| **SEG**                       | Segmentation mask associated with a full CT scan or VOI                                                              |
| **nnU-Net**                   | Self-configuring framework for medical image segmentation                                                            |
| **NIfTI**                     | Neuroimaging Informatics Technology Initiative file format (`.nii.gz`)                                               |
| **GLB**                       | Binary glTF — compact 3D mesh format                                                                                 |
| **OCI**                       | Open Container Initiative — container image specification                                                            |
| **udocker**                   | User-space container execution tool (no root required)                                                               |
| **Marching Cubes**            | Algorithm to extract isosurface mesh from a 3D scalar field                                                          |
| **database.csv**              | Canonical reconciled dataset table used as the primary v2.0 metadata source                                          |
| **manifest.csv**              | Raw converter metadata retained for provenance and fallback use                                                      |
| **Curation state**            | Routine review decisions, comments, queue state, and flags written separately from source data                       |
| **Routine review read-only**  | Policy that normal QC controls do not modify image files, masks, `manifest.csv`, or `database.csv`                   |
| **Controlled Dataset Correction** | Confirmed, auditable operation that may update `database.csv` or relocate VOI files under a mutation gate        |
| **Case-level QC decision**    | One per-case decision: Accepted, Needs correction, Rejected, or Cannot assess                                        |
| **Source-level flag**         | Scan/source issue such as wrong phase, exclude scan, exclude VOI, missing SEG, missing VOI, ambiguous phase, or wrong side |
| **Correction queue**          | List of cases needing external correction, e.g. in 3D Slicer                                                        |

---

*End of SRS v2.0*
