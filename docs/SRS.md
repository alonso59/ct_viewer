# Software Requirements Specification (SRS)

## Radiology Desktop & WebUI — Medical Dataset Curation Tool

| Field       | Value                                                     |
| ----------- | --------------------------------------------------------- |
| **Version** | 2.2                                                       |
| **Date**    | 2026-08-03                                                |
| **Status**  | Active specification                                      |
| **Project** | radio-ccrcc / Radiology WebUI                             |
| **Author**  | Alonso (researcher) + GitHub Copilot / Codex-assisted SRS |

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Overall Description](#2-overall-description)
3. [Data Model & Folder Schema](#3-data-model--folder-schema)
4. [Functional Requirements](#4-functional-requirements)
5. [Non-Functional Requirements](#5-non-functional-requirements)
6. [User Interface Specification](#6-user-interface-specification)
7. [Technical Architecture](#7-technical-architecture)
8. [Deployment](#8-deployment)
9. [Future Versions (Out of Scope v2.2)](#9-future-versions-out-of-scope-v22)
10. [Acceptance Criteria](#10-acceptance-criteria)
11. [Glossary](#11-glossary)

---

## 1. Introduction

### 1.1 Purpose

This document specifies the requirements for **Radiology v2.2**, a lightweight, local-first medical dataset curation interface for the `radio-ccrcc` pipeline. It is distributed both as the existing WebUI and as a Windows x64 desktop application; both editions reuse the same React frontend, FastAPI API, inspection contracts, and clinical viewers.

The v2.0 system is no longer only an auxiliary researcher viewer. It is a **medical curation cockpit** where the medical doctor is the data-curation owner. The tool shall support case-by-case review of CT volumes, segmentation masks, VOIs, canonical metadata, QC warnings, and segmentation-focused curation decisions.

The WebUI shall allow the medical curator to:

* select a dataset;
* review cases from a case worklist;
* inspect complete scans and VOIs;
* switch anatomical plane: axial, coronal, sagittal;
* inspect SEG and VOI mask overlays;
* review all available phases and scan indices;
* review left/right VOI availability;
* see QC warnings from `database.csv` reconciliation;
* assign segmentation QC status;
* add segmentation-focused comments;
* propose phase/laterality corrections without directly mutating source data;
* add cases/items to a correction queue for external editing.

The WebUI shall not edit segmentation masks directly. Segmentation correction remains out of scope and shall be performed in specialized software such as 3D Slicer.

### 1.2 Scope

**In scope (v2.0):**

* Use `database.csv` as the primary source of truth when available.
* Treat `manifest.csv` and folder discovery as legacy fallback only.
* Browse a mounted dataset folder and validate `database.csv` status.
* Display a case-centered worklist instead of a file/folder-centered workflow.
* Show one case review interface per selected `case_id`.
* Show a compact case summary and scan inventory.
* Show all available phases, scan indices, complete scans, SEG masks, VOI images, and VOI masks for a case.
* Visualize NIfTI full volumes and NIfTI VOI volumes.
* Preserve legacy NumPy VOI support only as compatibility fallback.
* Overlay multi-label segmentation masks with per-layer visibility and opacity control.
* Support axial, coronal, and sagittal views.
* Preserve pan, zoom, window/level adjustment, slice navigation, and crosshair synchronization.
* Preserve optional 3D surface rendering where already implemented.
* Display QC warnings for missing files, duplicate mappings, incomplete VOIs, phase inconsistencies, laterality inconsistencies, and path-resolution failures.
* Allow controlled curation-state writing:

  * segmentation accepted;
  * needs minor correction;
  * needs major correction;
  * rejected;
  * missing;
  * cannot assess;
  * wrong phase suspected;
  * wrong side/laterality suspected;
  * free-text segmentation/VOI comments;
  * correction priority.
* Support phase correction proposals without directly renaming files, moving files, or overwriting canonical metadata.
* Store curation decisions separately from `database.csv`.
* Export or list a correction queue for external segmentation correction.
* Run as one web service image, compatible with `docker`, `podman`, and `udocker`.
* Run as an unprivileged Windows 10/11 x64 desktop application using Tauri 2 and a private FastAPI sidecar.
* Select a dataset through a native folder dialog in the desktop edition while retaining manual server-visible paths in the web edition.

**Out of scope (v2.0):**

* Direct segmentation editing, brush tools, or mask painting.
* Direct voxel-level modification of NIfTI, SEG, or VOI files.
* Direct destructive phase renaming or moving files across phase folders from the WebUI.
* Direct silent overwrite of `database.csv`.
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

The system shall translate `database.csv` rows and dataset paths into a simple review experience: case, phase, scan index, scope, plane, overlay, QC status, and comments.

### 2.2 Operating Environment

| Aspect         | Specification                                                                                        |
| -------------- | ---------------------------------------------------------------------------------------------------- |
| Host OS        | Linux (primary), macOS (secondary)                                                                   |
| Desktop OS     | Windows 10/11 x64                                                                                     |
| Container      | OCI image run via `udocker`, `podman`, or `docker`                                                   |
| Browser        | Chromium-based browsers or Firefox, latest 2 ESR                                                     |
| Data mount     | Host path bind-mounted at `/data`; source imaging data should be read-only whenever possible         |
| Curation state | Stored separately from source images; preferably in `.webui/` or configured external state directory |
| Network        | Localhost or trusted internal network only; no external upload                                       |

### 2.3 Constraints

* **Web runtime**: backend API and compiled frontend are served by one container process.
* **Desktop runtime**: Tauri loads local Vite assets and owns one private loopback FastAPI sidecar.
* **database.csv-first design**: when `database.csv` exists, it shall drive case, scan, VOI, path, and QC state.
* **Legacy fallback**: folder discovery and `manifest.csv` may remain as fallback, but shall not be the primary v2.0 workflow.
* **Visualization preservation**: current MPR rendering, slice navigation, overlays, pan/zoom, and W/L behavior should be reused where possible.
* **No segmentation editing**: the WebUI shall not modify voxel data.
* **No destructive phase mutation**: the WebUI may record phase correction proposals, but shall not directly rename files, move files across phase folders, or silently overwrite `database.csv`.
* **Controlled curation-state mutation**: only explicit curation decisions may be written.
* **Auditability**: all curation decisions shall include reviewer, timestamp, target, status, comment, and source row reference when available.

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
| `DELAY`         | Delayed or excretory phase               |
| `UNK`           | Unknown, ambiguous, or unavailable phase |

Legacy or source phase names may include:

| Legacy/source value         | Possible canonical mapping                       |
| --------------------------- | ------------------------------------------------ |
| `NC`                        | `NC`                                             |
| `ART`                       | `CMP`, if clinically and metadata-wise justified |
| `VEN`                       | `NP`, if clinically and metadata-wise justified  |
| `DELAY`, `EXC`, `EXCRETORY` | `DELAY`                                          |
| `UNDEFINED`, empty, unknown | `UNK`                                            |

The system shall preserve the original phase value. It shall not overwrite source phase metadata without a controlled external process.

Recommended fields:

| Field              | Purpose                                             |
| ------------------ | --------------------------------------------------- |
| `raw_phase`        | Original phase value from source                    |
| `canonical_phase`  | Normalized phase used for UI grouping               |
| `phase_source`     | Folder, manifest, protocol, manual proposal, etc.   |
| `phase_confidence` | High, medium, low, unknown                          |
| `phase_status`     | normalized, ambiguous, missing, proposed_correction |
| `proposed_phase`   | Doctor-proposed corrected phase, if any             |
| `phase_comment`    | Medical curator comment                             |

The WebUI may allow a medical curator to propose a phase correction. It shall not directly rename folders, move files, or overwrite `database.csv`.

### 3.4 Naming Conventions

| Token        | Pattern                         | Example                           | Description                            |
| ------------ | ------------------------------- | --------------------------------- | -------------------------------------- |
| `NN`         | `\d{2}`                         | `01`                              | Per-case series counter                |
| `case_YYYYY` | `case_\d{5}`                    | `case_00042`                      | Sequential case ID                     |
| `_0000`      | literal                         | `_0000`                           | nnU-Net channel suffix for image files |
| `{L,R}`      | `_L`, `_R`, `sideL`, or `sideR` | `_L`                              | Laterality / side token                |
| `{group}`    | string                          | `A`, `B`, `NG`                    | Patient classification group           |
| `{phase}`    | canonical or raw phase          | `NC`, `CMP`, `NP`, `DELAY`, `UNK` | Contrast phase label                   |

### 3.5 Mask Label Map (Multi-Label)

| Label | Structure  | Default color | Default alpha | Default visible |
| ----- | ---------- | ------------- | ------------- | --------------- |
| 0     | Background | —             | —             | —               |
| 1     | Kidney     | cyan          | 0.15          | ✓               |
| 2     | Tumor      | yellow        | 0.20          | ✓               |
| 3     | Cyst       | magenta       | 0.15          | ✗               |

### 3.6 Case-to-Scan-to-VOI Mapping

One **case** (`case_YYYYY`) may have:

* 1–N full NIfTI volumes in `nifti/` or paths specified by `database.csv`.
* 0–N corresponding segmentation masks in `seg/` or paths specified by `database.csv`.
* 0–N VOI images in `voi/images/` or paths specified by `database.csv`.
* 0–N VOI masks in `voi/mask/` or paths specified by `database.csv`.
* 0–N sides (`L`, `R`) depending on VOI availability.
* 0–N curation decisions in `curation_review.csv`.

The preferred selectable row unit for v2.0 is:

```text
case_id × canonical_phase × scan_idx × side × scope
```

Where `scope` is either:

* `complete` — full CT scan and SEG mask;
* `voi` — cropped VOI image and VOI mask.

### 3.7 Curation State Files

Curation state shall be stored separately from `database.csv`.

Recommended default:

```text
DatasetID/.webui/curation_review.csv
DatasetID/.webui/correction_queue.csv
```

Alternative for read-only dataset mounts:

```text
$WEBUI_STATE_DIR/{dataset_id}/curation_review.csv
$WEBUI_STATE_DIR/{dataset_id}/correction_queue.csv
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
| `target`          | SEG, tumor mask, kidney mask, cyst mask, VOI mask, phase issue, side issue                                                              |
| `status`          | accepted, needs_minor_correction, needs_major_correction, rejected, missing, cannot_assess, wrong_phase_suspected, wrong_side_suspected |
| `priority`        | low, medium, high                                                                                                                       |
| `comment`         | Free-text curation comment                                                                                                              |
| `reviewer`        | Reviewer name or ID                                                                                                                     |
| `reviewed_at`     | Timestamp                                                                                                                               |
| `nifti_path`      | Complete scan path at review time                                                                                                       |
| `seg_path`        | SEG path at review time                                                                                                                 |
| `voi_image_path`  | VOI image path at review time                                                                                                           |
| `voi_mask_path`   | VOI mask path at review time                                                                                                            |

---

## 4. Functional Requirements

### 4.1 Data Discovery & Navigation

| ID     | Requirement                                                                                                                                                                                                                                                      | Priority |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-01  | **Dataset Selection**: User can provide a server-side path to a single dataset root folder through the GUI before dataset browsing begins.                                                                                                                       | Must     |
| FR-01a | **Workspace Validation**: The selected dataset folder must exist on the backend server and contain at least one recognized dataset marker. For v2.0, `database.csv` is the preferred marker. Legacy markers include `nifti/`, `seg/`, `voi/`, or `manifest.csv`. | Must     |
| FR-01b | **Database Status**: After workspace activation, the system displays `database.csv` status, row count, case count, required-column status, and warning count.                                                                                                    | Must     |
| FR-01c | **Read-only Inspection**: Dataset inspection shall report type, markers, inventory counts, state-path readiness, and warnings without changing workspace state, caches, or filesystem contents.                                                                  | Must     |
| FR-01d | **Controlled Activation**: Only canonical, converter, legacy, NIfTI-collection, or VOI-collection datasets with a readable volume may be activated. Incomplete datasets remain diagnostic-only.                                                                  | Must     |
| FR-01e | **Allowed Data Roots**: Dataset roots, referenced files, and symlink targets shall remain under configured allowed roots unless an explicit development-only override is enabled.                                                                                | Must     |
| FR-01f | **Recent Datasets**: The system shall retain at most five recently activated server paths without patient or clinical metadata and re-inspect a recent path before reuse.                                                                                          | Should   |
| FR-02  | **Case Discovery**: System builds a case worklist from `database.csv`, grouped by `case_id`. If `database.csv` is absent, it may fall back to v1.2 patient discovery.                                                                                            | Must     |
| FR-03  | **Inventory Discovery**: For a selected case, the system lists all available phases, scan indices, full scans, SEG masks, VOI images, VOI masks, and sides from `database.csv`.                                                                                  | Must     |
| FR-04  | **Adaptive Content**: The viewer adapts to available data: complete scan only, complete scan + SEG, VOI only, VOI + VOI mask, or missing/partial data with QC warning.                                                                                           | Must     |
| FR-05  | **Case Search/Filter**: User can search by case ID or patient ID and filter by group, canonical phase, curation status, warning status, VOI availability, or segmentation status.                                                                                | Should   |
| FR-06  | **Inventory Selector**: The case review page provides phase, scope, scan_idx, and side controls to switch between available data without returning to the worklist.                                                                                              | Must     |
| FR-07  | **Progressive Control Display**: `scan_idx` selector appears only when multiple scans exist for the selected phase. Side selector appears only when both L/R exist or VOI mode requires side selection.                                                          | Must     |

### 4.2 2D Visualization (MPR Views)

| ID    | Requirement                                                                                                                                                                 | Priority |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-10 | **Axial View**: Display axial slice with correct orientation.                                                                                                               | Must     |
| FR-11 | **Coronal View**: Display coronal slice with correct orientation.                                                                                                           | Must     |
| FR-12 | **Sagittal View**: Display sagittal slice with correct orientation.                                                                                                         | Must     |
| FR-13 | **Slice Navigation**: Each view has a slider or scroll interaction to navigate through slices.                                                                              | Must     |
| FR-14 | **Crosshair Synchronization**: Selecting a point in one view updates the crosshair position in the other two views.                                                         | Must     |
| FR-15 | **Window/Level Control**: User can adjust HU window and level via drag interaction or numeric input. Default: W=400, L=50 unless overridden by saved settings.              | Must     |
| FR-16 | **W/L Presets**: Quick-select presets: Soft Tissue, Bone, Lung, Brain.                                                                                                      | Should   |
| FR-17 | **Pan & Zoom**: User can pan and zoom within any 2D view.                                                                                                                   | Must     |
| FR-18 | **RAS Reorientation**: NIfTI volumes are reoriented to RAS on load using `nibabel.as_closest_canonical`. Original files are never modified.                                 | Must     |
| FR-19 | **Legacy NumPy VOI Support**: Legacy `.npy` VOI arrays may be loaded as compatibility fallback. v2.0 primary VOI format is NIfTI when paths are provided in `database.csv`. | Should   |

### 4.3 Segmentation Overlay

| ID    | Requirement                                                                                                                                                                | Priority |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-20 | **Mask Overlay**: If a SEG mask or VOI mask exists, overlay it on the 2D views.                                                                                            | Must     |
| FR-21 | **Multi-Label Rendering**: Overlay renders labels 1 kidney, 2 tumor, 3 cyst with distinct colors and contour borders.                                                      | Must     |
| FR-22 | **Per-Layer Visibility**: Each label has an independent visibility toggle. Default: kidney=on, tumor=on, cyst=off.                                                         | Must     |
| FR-23 | **Per-Layer Opacity**: Each label has an independent opacity slider. Default: kidney=0.15, tumor=0.20, cyst=0.15.                                                          | Must     |
| FR-24 | **Mask Path Resolution**: System resolves masks from `database.csv` path fields first. Filename-derived matching is legacy fallback only.                                  | Must     |
| FR-25 | **Overlay Missing Warning**: If a selected item claims mask availability but the file is missing or unreadable, the viewer shows a QC warning instead of failing silently. | Must     |

### 4.4 3D Visualization

| ID    | Requirement                                                                                                                  | Priority |
| ----- | ---------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-30 | **3D Surface Rendering**: When a segmentation mask exists, generate and display an isosurface mesh for each visible label.   | Should   |
| FR-31 | **3D Blend Slider**: A global opacity/blend slider controls the transparency of the 3D surface rendering.                    | Should   |
| FR-32 | **3D Rotate/Zoom**: User can orbit, pan, and zoom in the 3D viewport.                                                        | Should   |
| FR-33 | **Empty 3D Panel**: When no mask is available, the 3D panel displays an informational empty-state view.                      | Should   |
| FR-34 | **3D as Secondary Tool**: 3D view is optional orientation support and shall not dominate the v2.0 medical curation workflow. | Must     |
| FR-35 | **3D Color Consistency**: Surface colors match the 2D overlay colors.                                                        | Should   |

### 4.5 Layout & Expand

| ID    | Requirement                                                                                                                                                       | Priority |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-40 | **Main Case Review Layout**: Default v2.0 layout is case worklist + central viewer + scan inventory/QC panel.                                                     | Must     |
| FR-41 | **Viewer Panel Layout**: Existing 2×2 MPR/3D layout may be preserved, but the v2.0 UI may also support a simplified single-plane focused view with plane toggles. | Should   |
| FR-42 | **Expand Panel**: Double-click or button on any panel expands it to fill the viewer area.                                                                         | Must     |
| FR-43 | **Restore Layout**: When expanded, a button or double-click restores the prior layout.                                                                            | Must     |
| FR-44 | **Minimal Default UI**: The default view shall emphasize the selected image and segmentation overlay, not large metadata tables.                                  | Must     |

### 4.6 Persistence & Settings

| ID    | Requirement                                                                                                                    | Priority |
| ----- | ------------------------------------------------------------------------------------------------------------------------------ | -------- |
| FR-50 | **Persist Last Case**: Store last viewed case ID per dataset so the user resumes where they left off.                          | Should   |
| FR-51 | **Persist W/L Settings**: Save last-used window/level values per dataset.                                                      | Should   |
| FR-52 | **Persist Layer Visibility**: Save layer on/off and opacity settings.                                                          | Should   |
| FR-53 | **Settings Storage**: Preferences are persisted in `<dataset>/.webui/settings.json` or configured external state directory.    | Should   |
| FR-54 | **No Source Data Mutation for Settings**: Viewer settings shall not modify NIfTI, SEG, VOI, `manifest.csv`, or `database.csv`. | Must     |

### 4.7 Authentication

| ID    | Requirement                                                                                                                                                                           | Priority |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-60 | **Simple Auth**: A single shared bearer token protects API routes (`/api/*`, excluding `/api/health`). Token is configured via environment variable (`RADIOLOGY_UI_TOKEN`).           | Should   |
| FR-61 | **Session Persistence**: Auth token is memory-only by default; optional browser persistence via `VITE_AUTH_TOKEN_STORAGE=local`.                                                      | Should   |
| FR-62 | **Medical Metadata Safety**: If direct identifiers or sensitive metadata are present, the UI shall hide nonessential sensitive fields by default and place them in advanced metadata. | Should   |

### 4.8 Medical Curation Workflow

| ID    | Requirement                                                                                                                                                                                                        | Priority |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- |
| FR-70 | **Case Worklist**: Viewer provides a case worklist with one row per `case_id`.                                                                                                                                     | Must     |
| FR-71 | **Case Filters**: Worklist provides filters for group, phase availability, QC warning status, curation status, and VOI availability.                                                                               | Should   |
| FR-72 | **Next Case Button**: Case review provides `Load Next Case` following the current worklist filter and sort order.                                                                                                  | Must     |
| FR-73 | **Phase Display**: The viewer displays canonical phase labels and preserves access to raw phase metadata in advanced details.                                                                                      | Must     |
| FR-74 | **Phase Correction Proposal**: The medical curator may propose a corrected phase for the selected scan/series. This writes curation state only and does not rename files, move files, or overwrite `database.csv`. | Must     |
| FR-75 | **Side/Laterality Correction Proposal**: The medical curator may flag wrong side or laterality suspicion. This writes curation state only.                                                                         | Must     |
| FR-76 | **Segmentation QC Status**: The medical curator may assign segmentation/VOI QC status for the selected item.                                                                                                       | Must     |
| FR-77 | **Segmentation Comment**: The medical curator may add a free-text comment focused on segmentation or VOI quality.                                                                                                  | Must     |
| FR-78 | **Correction Priority**: The medical curator may assign low, medium, or high correction priority.                                                                                                                  | Should   |
| FR-79 | **Correction Queue**: Items with correction-relevant statuses are added to a correction queue or made exportable as such.                                                                                          | Must     |
| FR-80 | **Curation Audit Artifacts**: Curation decisions are appended to `curation_review.csv` or equivalent audit store.                                                                                                  | Must     |
| FR-81 | **Source-Data Safety Gate**: The system shall not allow direct source-data mutation from the v2.0 medical curation workflow.                                                                                       | Must     |
| FR-82 | **Legacy Mutation Controls**: Existing reclassify/delete/recycle controls from v1.2 shall be hidden, disabled, or separated from Medical Curation Mode unless explicitly enabled in a technical/admin mode.        | Must     |

---

### 4.9 Windows Desktop Runtime

| ID     | Requirement                                                                                                                                                                   | Priority |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| FR-80  | **Native Host**: Windows 10/11 x64 uses Tauri 2 without replacing the React, FastAPI, or web distributions.                                                                  | Must     |
| FR-81  | **Single Instance**: A second launch focuses the existing window and never starts another backend.                                                                           | Must     |
| FR-82  | **Readiness Gate**: The main window remains hidden until the sidecar health check succeeds and React has configured the dynamic backend runtime.                             | Must     |
| FR-83  | **Private Sidecar**: FastAPI binds only to `127.0.0.1` on an operating-system-selected port and requires a fresh 256-bit bearer token for every API route except health.      | Must     |
| FR-84  | **Native Browse**: The desktop Open Dataset page exposes a native folder picker. Selection fills the path field but does not inspect or activate automatically.              | Must     |
| FR-85  | **Controlled Shutdown**: Closing Tauri requests authenticated sidecar shutdown, waits up to five seconds, and terminates the process only as fallback.                       | Must     |
| FR-86  | **Parent Watchdog**: The sidecar terminates when its Tauri parent exits unexpectedly.                                                                                         | Must     |
| FR-87  | **Web Compatibility**: Browser Axios remains relative to `/api`; the web server keeps allowed-root enforcement and continues serving the compiled React application.        | Must     |
| FR-88  | **Desktop Path Policy**: Only the desktop sidecar enables unrestricted local paths; source-data mutations remain disabled.                                                   | Must     |
| FR-89  | **Private Shutdown API**: `/api/desktop/shutdown` is authenticated, absent from OpenAPI, and registered only by the desktop sidecar.                                         | Must     |

## 5. Non-Functional Requirements

| ID     | Requirement                                                                                                                                                    | Target                            |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| NFR-01 | **First Slice Visible**: After selecting a case/inventory item, the first 2D slice renders in < 3 seconds for a typical volume.                                | < 3 s                             |
| NFR-02 | **Slice Navigation Latency**: Changing a single slice updates the view in < 200 ms when cached and feasible.                                                   | < 200 ms                          |
| NFR-03 | **3D Mesh Generation**: Initial marching-cubes computation completes in < 5 seconds for typical segmentation size, when 3D is used.                            | < 5 s                             |
| NFR-04 | **Memory Footprint**: Backend holds a limited number of volumes in memory simultaneously using LRU cache.                                                      | Configurable; default ≤ 2 volumes |
| NFR-05 | **Container Image Size**: Final OCI image should remain reasonably small for local/HPC deployment.                                                             | ≤ 1.5 GB target                   |
| NFR-06 | **Source-Data Read-Only**: v2.0 medical curation workflow shall not modify NIfTI, SEG, VOI, `manifest.csv`, or `database.csv` directly.                        | Mandatory                         |
| NFR-07 | **Controlled Curation Writes**: Only explicit curation-state actions may write to curation files or configured state storage.                                  | Mandatory                         |
| NFR-08 | **Auditability**: Every curation decision shall include reviewer, timestamp, target, status, and source row reference when available.                          | Mandatory                         |
| NFR-09 | **Privacy / Local-Only**: No data leaves the host. No telemetry, analytics, or external API calls.                                                             | Mandatory                         |
| NFR-10 | **Browser Compatibility**: Chrome 100+, Firefox 100+, Edge 100+.                                                                                               | Must                              |
| NFR-11 | **Maintainability**: Backend services are modular. Frontend uses typed TypeScript with component isolation.                                                    | Must                              |
| NFR-12 | **Logging**: Backend logs requests and errors to stdout. Log level configurable via env var.                                                                   | Should                            |
| NFR-13 | **Metadata Scalability**: Wide `database.csv` files shall not be fully sent to list views by default. Backend shall provide compact projections.               | Must                              |
| NFR-14 | **UX Minimalism**: The default UI shall expose only the controls needed for medical curation. Advanced metadata and technical provenance shall be collapsible. | Must                              |

---

## 6. User Interface Specification

### 6.1 Page Flow

```text
┌──────────────────────────────────────────────────────────┐
│  [1] Open Dataset Page                                    │
│   • Enter a server-visible dataset path                   │
│   • Inspect without changing the active workspace         │
│   • Show type, inventory, state readiness, and warnings   │
│   • Activate → Cases (modern) or Patients (legacy)        │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│  [2] Case Worklist Page                                   │
│   • Table: case_id | group | phases | scans | VOI | QC    │
│   • Search + filters                                      │
│   • Click case → Case Review                              │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│  [3] Case Review Page                                     │
│   • Header: case_id, curation status, warning count       │
│   • Viewer toolbar: phase, scope, plane, overlay          │
│   • Conditional controls: scan_idx, side                  │
│   • Central viewer: Complete scan or VOI                  │
│   • Scan Inventory: phase/scan_idx/full/SEG/VOI/QC        │
│   • Segmentation QC panel: status, target, priority, note │
│   • Advanced metadata collapsed by default                │
└──────────────────────────────────────────────────────────┘
```

### 6.2 Case Review Wireframe

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Dataset: Dataset320 | database.csv OK | Case: case_00042 | Warnings: 1      │
├──────────────────────┬───────────────────────────────────────────────────────┤
│ Case Worklist         │ Phase: [NC] [CMP] [NP] [DELAY]   Scope: [Complete|VOI]│
│ ──────────────────── │ Plane: [Axial] [Coronal] [Sagittal] Overlay: [SEG ✓] │
│ case_00040  OK        │ scan_idx: [0 ▼]       side: [L ▼]                   │
│ case_00041  Needs QC  │                                                       │
│ case_00042  Warning   │                VIEWER                                 │
│ case_00043  Accepted  │        2D MPR / selected panel                         │
│ ...                   │                                                       │
├──────────────────────┴───────────────────────────────────────────────────────┤
│ Scan Inventory                                                               │
│ Phase | scan_idx | Full scan | SEG | VOI L | VOI R | QC                      │
│ NP    | 0        | yes       | yes | yes   | no    | Missing VOI R          │
│ CMP   | 0        | yes       | yes | yes   | yes   | OK                     │
├──────────────────────────────────────────────────────────────────────────────┤
│ Segmentation QC                                                              │
│ Target: [Tumor mask ▼] Status: [Needs minor correction ▼] Priority: [Med ▼] │
│ Comment: [free text focused on segmentation/VOI quality] [Save QC Decision] │
│ [Accept] [Needs Correction] [Reject] [Cannot Assess] [Add to Correction Queue]│
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Viewer Interaction Model

The medical curator shall not select files directly.

The primary visible controls shall be:

| Control | Behavior                                                              |
| ------- | --------------------------------------------------------------------- |
| Case    | Selected from worklist                                                |
| Phase   | Shows canonical phase chips; raw phase available in advanced metadata |
| Scope   | `Complete` loads full CT + SEG; `VOI` loads VOI image + VOI mask      |
| Plane   | Axial, Coronal, Sagittal                                              |
| Overlay | SEG and/or VOI mask visibility                                        |

Conditional controls:

| Control           | Visibility rule                                                  |
| ----------------- | ---------------------------------------------------------------- |
| `scan_idx`        | Only visible when multiple scans exist for selected phase        |
| `side`            | Only visible when L/R distinction exists or VOI mode is selected |
| Advanced metadata | Collapsed by default                                             |
| Raw paths         | Hidden by default; visible in advanced metadata                  |

### 6.4 Default Case Opening Behavior

When a case is opened, the viewer shall default to:

| Item     | Default                                                                                      |
| -------- | -------------------------------------------------------------------------------------------- |
| Scope    | Complete scan                                                                                |
| Plane    | Axial                                                                                        |
| Overlay  | SEG on if available                                                                          |
| Phase    | Configurable project priority; default `NP`, then `CMP`, then `NC`, then `DELAY`, then `UNK` |
| scan_idx | First valid scan index for selected phase                                                    |
| side     | Only auto-selected in VOI mode if one side exists                                            |

### 6.5 Color Scheme

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
| QC warning         | amber     |
| QC rejected/error  | red       |
| QC accepted        | green     |

### 6.6 Interaction Summary

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
| Toggle layer             | Checkbox/button                      | Show/hide label in overlay              |
| Change opacity           | Slider                               | Adjust alpha for selected label         |
| Filter worklist          | Search/filter controls               | Restrict case list                      |
| Switch case              | Worklist click                       | Navigate to selected case               |
| Load next case           | Button click                         | Navigate to next filtered case          |
| Switch phase             | Phase chip                           | Load selected phase inventory item      |
| Switch scope             | Complete/VOI toggle                  | Switch source between full scan and VOI |
| Propose phase correction | Curation control                     | Write curation-state proposal only      |
| Save segmentation QC     | Save button                          | Append/update curation review record    |
| Add to correction queue  | Button                               | Mark item for external correction       |

---

### 6.7 Open Dataset Reference Surface

The root route is a standalone clinical opening surface. It hides the global AppBar and Active Context while every other route retains the established application shell. The page uses a solid background, no decorative gradients, no nested cards, compact recent rows, visible but subordinate warnings, and one primary `Open Dataset` action. It reserves stable space for progress, errors, and inspection results. `Browse…` appears only when the Tauri IPC bridge exists. `Inspect` remains read-only; activation remains a separate `PUT /api/workspace` action.

## 7. Technical Architecture

### 7.1 Stack Selection

| Layer        | Technology                                               | Rationale                                                      |
| ------------ | -------------------------------------------------------- | -------------------------------------------------------------- |
| Backend      | **Python 3.12 + FastAPI**                                | Native nibabel/numpy stack; lightweight API + static serving   |
| Frontend     | **React 19 + TypeScript + MUI**                          | Typed UI and reusable component primitives                     |
| 2D Rendering | **Server-rendered PNG slices + React interaction layer** | Preserve notebook-aligned and current viewer behavior          |
| 3D Rendering | **three.js via @react-three/fiber + GLTFLoader**         | Optional orientation support using existing approach           |
| Bundler      | **Vite 7**                                               | Fast TypeScript builds and dev-server proxy                    |
| Container    | **Multi-stage OCI image**                                | Node build stage + Python runtime stage, non-root runtime user |
| Desktop host | **Tauri 2 + Rust**                                       | Native lifecycle, single instance, folder dialog, and NSIS     |
| Sidecar      | **PyInstaller 6.21 onefile**                             | Self-contained FastAPI runtime without a console window        |

### 7.2 Backend Architecture

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
│   │   ├── cases.py           # v2.0 case summaries, dossier, inventory
│   │   ├── slices.py          # POST load + GET /api/slice/{axis}/{index}
│   │   ├── mesh.py            # GET /api/mesh/{label}
│   │   ├── curation.py        # QC decisions, phase proposals, correction queue
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
│   │   └── volume_cache.py    # LRU series cache + expiring load handles
│   │
│   └── models/
│       ├── dataset.py         # Dataset/case/series/volume response models
│       ├── database.py        # Database row projections and validation models
│       ├── curation.py        # QC decision and correction queue models
│       └── settings.py        # Per-dataset viewer settings payload
│
└── requirements.txt
```

**Key backend design decisions:**

* **database.csv-first API**: v2.0 endpoints use database-backed case summaries and inventory rows.
* **Legacy fallback**: existing discovery logic remains available when `database.csv` is absent.
* **Compact projections**: list views return only necessary fields, not every database column.
* **Advanced metadata endpoint**: full raw metadata is available on demand.
* **Path validation**: missing/unreadable files become QC warnings.
* **Load handle contract**: viewer loading may reuse existing cache/load-handle mechanism.
* **Curation-state store**: QC decisions are written separately from source metadata.
* **No destructive curation mutation**: v2.0 curation shall not move files, rename files, or overwrite `database.csv`.

### 7.3 Frontend Architecture

```text
frontend/
├── src/
│   ├── App.tsx
│   ├── main.tsx
│   │
│   ├── pages/
│   │   ├── DatasetSelectorPage.tsx
│   │   ├── CaseWorklistPage.tsx
│   │   └── CaseReviewPage.tsx
│   │
│   ├── components/
│   │   ├── LoginDialog.tsx
│   │   └── viewer/
│   │       ├── CaseWorklist.tsx
│   │       ├── CaseSummaryPanel.tsx
│   │       ├── ScanInventory.tsx
│   │       ├── CaseReviewToolbar.tsx
│   │       ├── SegmentationQcPanel.tsx
│   │       ├── QcWarningPanel.tsx
│   │       ├── AdvancedMetadataPanel.tsx
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
│   │   └── useCurationState.ts
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

* **Case-first routing**: worklist → case review.
* **Progressive disclosure**: show simple controls by default; advanced metadata collapsed.
* **Viewer reuse**: current MPR components should be reused as much as possible.
* **Inventory-driven loading**: viewer source is selected through scan inventory, not raw file browsing.
* **Curation panel**: doctor actions are structured and auditable.

### 7.4 API Contract (Summary)

| Method | Endpoint                                                             | Returns                 | Description                                 |
| ------ | -------------------------------------------------------------------- | ----------------------- | ------------------------------------------- |
| GET    | `/api/health`                                                        | `{"status":"ok"}`       | Backend health check                        |
| GET    | `/api/workspace`                                                     | `WorkspaceStatus`       | Get active dataset workspace status         |
| POST   | `/api/workspace/inspect`                                             | `WorkspaceInspection`   | Read-only dataset inspection                 |
| PUT    | `/api/workspace`                                                     | `WorkspaceStatus`       | Validate and activate one dataset folder    |
| DELETE | `/api/workspace?recent_key=...`                                      | `WorkspaceStatus`       | Clear active workspace or remove one recent |
| GET    | `/api/datasets`                                                      | `Dataset[]`             | Dataset summary for active workspace        |
| GET    | `/api/datasets/{dataset_id}/database/validation`                     | `DatabaseValidation`    | database.csv validation and warning summary |
| GET    | `/api/datasets/{dataset_id}/cases`                                   | `CaseSummary[]`         | One row per case_id                         |
| GET    | `/api/datasets/{dataset_id}/cases/{case_id}/inventory`               | `CaseInventory`         | Phase/scan/scope/side availability          |
| GET    | `/api/datasets/{dataset_id}/cases/{case_id}/dossier`                 | `CaseDossier`           | Grouped case metadata                       |
| POST   | `/api/datasets/{dataset_id}/cases/{case_id}/load?row_id=...&scope=...` | `VolumeInfo`            | Load selected inventory item into cache     |
| GET    | `/api/slice/{axis}/{index}?load_handle=...&ww=...&wl=...&layers=...` | `image/png`             | Render 2D slice from cached volume          |
| GET    | `/api/mesh/{label}?load_handle=...&smooth=true`                      | `model/gltf-binary`     | Get 3D surface mesh for one label           |
| GET    | `/api/datasets/{dataset_id}/curation/cases/{case_id}/history`        | `CurationDecision[]`    | Get curation history for case               |
| POST   | `/api/datasets/{dataset_id}/curation/decisions`                      | `CurationDecision`      | Save curation decision / phase proposal     |
| GET    | `/api/datasets/{dataset_id}/curation/correction-queue`               | `CorrectionQueue`       | List items needing external correction      |
| GET    | `/api/datasets/{dataset_id}/curation/correction-queue.csv`           | `text/csv`              | Export correction queue                     |
| GET    | `/api/settings`                                                      | `Settings`              | Get persisted viewer preferences            |
| PUT    | `/api/settings`                                                      | `Settings`              | Save persisted viewer preferences           |

Legacy endpoints for `/patients`, `/series`, and `/review/apply` may remain for compatibility or technical/admin mode, but shall not be the primary v2.0 medical curation workflow.

The desktop-only `POST /api/desktop/shutdown` endpoint is an internal lifecycle contract. It is authenticated by the ephemeral runtime token, excluded from OpenAPI, and does not exist in the normal web application process.

#### 7.4.1 Workspace inspection and activation

`POST /api/workspace/inspect` accepts `{ "dataset_path": "..." }` and returns the
normalized path, visible `dataset_id`, path-derived `dataset_key`, `valid`, and one
of these kinds: `canonical`, `converter_output`, `legacy`, `nifti_collection`,
`voi_collection`, `incomplete`, or `unsupported`. The response also contains the
detected markers; case, NIfTI, VOI, segmentation, and VOI-mask counts; the
predicted `.webui` or `WEBUI_STATE_DIR` path; and structured warnings with code,
severity, and message. At most 100 warning details are returned while the summary
preserves the complete warning count.

Inspection resolves paths strictly, rejects NUL and paths longer than 4096
characters, follows symlinks before authorization, and permits dataset and
referenced-file access only below `ALLOWED_DATA_ROOTS`. It reads metadata and
volume headers, never voxel arrays, and is bounded to 100,000 filesystem entries
or metadata rows and depth 6. Exceeding either bound is a blocking diagnostic.

`PUT /api/workspace` repeats inspection and persists only a valid result. A
successful path change atomically updates `active_dataset_path`, refreshes the
five-entry UTC MRU list by `dataset_key`, and clears runtime caches. A failed or
incomplete activation changes none of those. `WorkspaceStatus` exposes
`dataset_key`, `dataset_kind`, and `recent_datasets`. `DELETE /api/workspace`
clears only the active entry while retaining recents; `recent_key` removes only
the selected MRU entry. Database path statuses include `forbidden` when a
reference leaves the authorized roots.

### 7.5 Data Flow

```text
[Browser]                          [FastAPI Backend]                         [Filesystem]
    │                                     │                                       │
    │  POST /api/workspace/inspect        │                                       │
    │ ──────────────────────────────────► │  authorize path + inspect read-only   │
    │  ◄────── WorkspaceInspection        │                                       │
    │                                     │                                       │
    │  PUT /api/workspace                 │                                       │
    │ ──────────────────────────────────► │  re-inspect + atomically activate     │
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
    │  ◄────── saved decision             │  no source image/database mutation      │
```

---

### 7.6 Desktop Architecture

```text
Radiology Desktop (single instance)
├── Tauri 2 / Rust
│   ├── hidden native window and minimal CSP
│   ├── native folder command
│   ├── ephemeral token + sidecar ownership
│   └── readiness and shutdown coordination
├── React + TypeScript + Vite
│   ├── local compiled assets
│   ├── dynamic Axios base URL and in-memory runtime token
│   └── existing Cases, Patients, Resume, 2D and 3D routes
└── FastAPI sidecar
    ├── 127.0.0.1:dynamic-port
    ├── M14 inspection and activation
    ├── PNG and GLB rendering
    └── parent watchdog and private shutdown endpoint
```

The sidecar writes an atomic handshake containing only PID and port. Tauri stores the token exclusively in Rust memory and communicates `{baseUrl, token}` to the local frontend through the `get_backend_runtime` command. The frontend signals `frontend_ready` only after transport configuration and its first render. No general shell or filesystem permission is exposed to JavaScript.

Desktop CORS accepts exactly `http://tauri.localhost` and the local Vite development origin `http://localhost:5173`. The CSP permits local application resources, Tauri IPC, and loopback HTTP connections only.

## 8. Deployment

### 8.1 Dockerfile

v2.0 may keep the existing multi-stage image strategy:

```dockerfile
FROM node:22-slim AS frontend-build
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

### 8.2 Native Docker/Podman

```bash
cp .env.example .env
# edit DATASET_DIR and optional RADIOLOGY_UI_TOKEN
# use read-only data mount when possible and separate WEBUI_STATE_DIR for curation outputs
docker compose up -d --build
```

### 8.3 udocker Runtime Path

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

### 8.4 Configuration (Environment Variables)

| Variable                  | Default               | Description                                                               |
| ------------------------- | --------------------- | ------------------------------------------------------------------------- |
| `RADIOLOGY_UI_TOKEN`      | `""` (no auth)        | Bearer token for API protection (`/api/*`, except health)                 |
| `RADIOLOGY_DESKTOP_RUNTIME` | `false`              | Registers the private shutdown route; set only by the Tauri host          |
| `CORS_ORIGINS`            | empty                 | Exact comma-separated allow-list; set by the Tauri host for desktop       |
| `DATA_ROOT`               | `/data`               | Fallback/dev-only dataset root when workspace selection is not used       |
| `ALLOWED_DATA_ROOTS`      | `DATA_ROOT`            | Server-visible roots allowed for datasets and referenced files            |
| `ALLOW_UNRESTRICTED_DATA_PATHS` | `false`          | Development-only bypass for the allowed-root boundary                     |
| `WEBUI_STATE_DIR`         | empty                 | Optional external directory for curation/settings state                   |
| `LOG_LEVEL`               | `info`                | Python logging level                                                      |
| `ALLOW_DATA_MUTATIONS`    | `false`               | Legacy/admin mutation gate; not used by v2.0 medical curation actions    |
| `PORT`                    | `8000`                | Uvicorn bind port                                                         |
| `STATIC_ROOT`             | `/app/static`         | Frontend static build directory served by backend                         |
| `VITE_AUTH_TOKEN_STORAGE` | `memory`              | Frontend token persistence mode (`memory` or `local`)                     |
| `PHASE_PRIORITY`          | `NP,CMP,NC,DELAY,UNK` | Default phase selection order                                             |

### 8.5 Compose Host Variables (`.env`)

| Variable               | Default          | Description                                                      |
| ---------------------- | ---------------- | ---------------------------------------------------------------- |
| `DATASET_DIR`          | `./data/dataset` | Host parent directory or dataset directory mounted at `/data`    |
| `WEBUI_STATE_DIR_HOST` | `./webui_state`  | Host directory for curation outputs when data mount is read-only |
| `WEBUI_PORT`           | `8000`           | Host port mapped to container `8000`                             |

### 8.6 Windows Desktop Build

`scripts/build-desktop.ps1` is the single Windows x64 build entrypoint. It validates the pinned Python, Node, Rust, Tauri CLI, MSVC, and WebView2 toolchains; installs from hashed/committed locks; runs backend, frontend, and Rust checks; creates the target-suffixed PyInstaller sidecar; smoke-tests it without a Python runtime; and produces an unsigned per-user NSIS installer. Build outputs include the installer SHA-256, build log, and a toolchain manifest.

Pinned versions are recorded in `toolchains/desktop-windows-x64.json`, `.python-version`, `.node-version`, `src-tauri/rust-toolchain.toml`, `backend/requirements-desktop.lock`, `frontend/package-lock.json`, and `src-tauri/Cargo.lock`. Builds use `PYTHONHASHSEED=0`, a commit-derived `SOURCE_DATE_EPOCH`, PyInstaller onefile without UPX, and NSIS `currentUser` mode with the standard WebView2 download bootstrapper. The installer is intentionally unsigned in v2.2.

---

## 9. Future Versions (Out of Scope v2.2)

| Version | Feature                                                                  |
| ------- | ------------------------------------------------------------------------ |
| v2.1    | Side-by-side synchronized multi-phase comparison                         |
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

## 10. Acceptance Criteria

| #  | Criterion                                                                                                | Verified by       |
| -- | -------------------------------------------------------------------------------------------------------- | ----------------- |
| 1  | User selects a dataset folder and sees `database.csv` status, row count, case count, and warning count.  | Manual/API test   |
| 2  | User sees a case worklist with one row per `case_id`.                                                    | Manual/API test   |
| 3  | Worklist shows group, available phases, scan count, VOI availability, QC status, and warning badge.      | Manual test       |
| 4  | User selects a case and sees a case review page without manually selecting files.                        | Manual test       |
| 5  | Case review shows scan inventory grouped by phase and scan_idx.                                          | Manual test       |
| 6  | Complete scan mode loads NIfTI image from database-resolved path.                                        | Manual/API test   |
| 7  | SEG overlay loads from database-resolved path when available.                                            | Manual/API test   |
| 8  | VOI mode loads NIfTI VOI image and VOI mask from database-resolved paths when available.                 | Manual/API test   |
| 9  | Axial, coronal, and sagittal views work for complete scan and VOI sources when files are available.      | Manual test       |
| 10 | Missing SEG, missing VOI image, missing VOI mask, and unreadable paths appear as QC warnings.            | Manual/API test   |
| 11 | `scan_idx` selector appears only when multiple scans exist for the selected phase.                       | Frontend test     |
| 12 | Side selector appears only when L/R distinction is relevant.                                             | Frontend test     |
| 13 | Advanced metadata is available but collapsed by default.                                                 | Manual test       |
| 14 | User can save segmentation QC status and comment for a selected case/inventory item.                     | Manual/API test   |
| 15 | User can propose phase correction without moving files, renaming files, or overwriting `database.csv`.   | Manual/API test   |
| 16 | User can flag wrong side/laterality suspected without moving files or overwriting source metadata.       | Manual/API test   |
| 17 | Curation decisions are written to `curation_review.csv` or configured curation store.                    | File/API test     |
| 18 | Items needing correction appear in correction queue or are exportable as CSV.                            | Manual/API test   |
| 19 | Source NIfTI, SEG, VOI image, VOI mask, `manifest.csv`, and `database.csv` are unchanged after curation. | Audit / checksum  |
| 20 | Existing MPR controls, W/L, pan/zoom, overlays, and panel expansion remain functional.                   | Manual regression |
| 21 | Legacy discovery remains available only as fallback when `database.csv` is absent.                       | API test          |
| 22 | Inspecting a dataset does not change workspace state, caches, or `.webui` contents.                       | API/file test     |
| 23 | Incomplete datasets show a read-only diagnosis and cannot be activated.                                   | Frontend/API test |
| 24 | Paths, referenced files, traversal attempts, and symlinks cannot escape allowed roots by default.          | Security test     |
| 25 | The five-entry recent list is MRU-ordered, contains no clinical metadata, and re-inspects before opening.   | API/frontend test |
| 26 | Modern datasets open in Cases; legacy/NIfTI/VOI collections open in Patients.                              | Frontend test     |
| 27 | With curation writes disabled, curation save endpoint rejects writes and no curation files are changed.  | API test          |
| 28 | With `RADIOLOGY_UI_TOKEN` set, unauthenticated `/api/*` access is blocked except `/api/health`.          | Manual/API test   |
| 29 | Windows desktop starts exactly one backend bound to a dynamic `127.0.0.1` port.                              | Rust/smoke test   |
| 30 | The desktop window is hidden until health succeeds and frontend transport configuration completes.           | Rust/manual test  |
| 31 | The runtime handshake contains PID and port only; the ephemeral token is never persisted or logged.          | Backend/Rust test |
| 32 | Desktop Browse handles selection and cancellation without automatic inspection or activation.                | Frontend/manual   |
| 33 | Inspect remains read-only and Open Dataset activates through the unchanged M14 contracts.                    | API/frontend test |
| 34 | Closing desktop removes the sidecar and handshake; parent loss also terminates the sidecar.                   | Smoke/manual test |
| 35 | The web build retains relative `/api`, manual paths, allowed roots, and no Browse action.                     | Frontend/manual   |
| 36 | Cases, Patients, Resume, PNG 2D, and GLB 3D remain operational in both editions.                              | Regression test   |
| 37 | The unsigned NSIS x64 installer installs per-user without administrative privileges or a console window.      | Windows manual    |
| 38 | CI publishes installer, SHA-256, build log, and a pinned toolchain manifest.                                  | CI artifact audit |

---

## 11. Glossary

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
| **Curation state**            | Review decisions, comments, correction status, and proposed metadata corrections written separately from source data |
| **Source-data read-only**     | Policy that the WebUI shall not modify image files, masks, or canonical dataset metadata directly                    |
| **Phase correction proposal** | Doctor-authored suggestion that a scan phase may be mislabeled; does not directly rename files or overwrite metadata |
| **Correction queue**          | Exportable list of cases/items needing external correction, e.g. in 3D Slicer                                        |

---

*End of SRS v2.2*
