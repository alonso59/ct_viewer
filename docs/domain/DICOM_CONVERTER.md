# DICOM converter (`dicom.convert`)

Scope: the DICOM → NIfTI task: stages, settings, output layout, metadata fidelity, PHI, incremental runs, geometry safety.
Read when: working on `plugins/dicom/`, DICOM sources, or DICOM metadata.
Depends: ADR-0014, ADR-0017, TASKS.md, SOURCES.md (identity), ANALYZERS.md, INPUT_METADATA.md (contract v1).

Code: `plugins/dicom/`, ported from the owner's converter kept as read-only reference in `legacy/convert/` (R9; pydicom + SimpleITK). The standalone CLI is ported with it (DCM-09).

## Stages

```text
scan (headers only) → select (analyzers, optional) → convert (pixels, selected series only) → emit (rows + sidecars)
```

| Stage | Reference in `legacy/convert/` | Notes |
|---|---|---|
| scan | `dicom_io.discover_dicom_series`, `metadata.build_metadata_row`, `series_inspection` | pydicom `stop_before_pixels`; geometry, advanced-DICOM and MRI component inspection |
| select | `policy.py` (target profiles, localizer/intervention, PRIMARY/SECONDARY, readiness), `metadata.infer_phase_guess` | Moves to `plugins/analyzers/` (ANZ-*); the converter calls them in-process |
| identity | `layout.py` (case index, scan index, resume registry) | Replaced by the project identity policy (SRC-07) when run in the app |
| convert | `writers.write_nifti_series` (SimpleITK) | The only stage that reads pixels |
| emit | `writers.write_run_outputs` (`metadata.jsonl`, `curation.csv`) | In the app: v1 rows + sidecars; no `curation.csv` (DCM-08) |

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| DCM-01 | Input is a `source` root (or one file, SRC-13), which is opened read-only (R1). Output goes only to `{DERIVED}/{project_id}/dicom.convert/` (ADR-0014). | M |
| DCM-02 | Geometry safety: volumes are written by the ITK image writer from an ITK image read by the series reader, so direction, origin and spacing are preserved (the LPS→RAS affine is written by ITK). A NIfTI is never built from `GetArrayFromImage` (ZYX) without restoring the geometry (SOURCES §NumPy). TST-13 checks orientation end to end. | M |
| DCM-03 | Geometry inspection codes (`IRREGULAR_SLICE_SPACING`, `LARGE_SLICE_GAP`, `DUPLICATE_SLICE_POSITION`, `ORIENTATION_CONFLICT`, `IN_PLANE_SPACING_CONFLICT`, `MATRIX_SIZE_CONFLICT`, `POSSIBLE_MULTIPLE_STACKS`) go into the row and the run diagnostics. `skip_unsafe_geometry` skips those series. | M |
| DCM-04 | Metadata fidelity: one sidecar per converted series, `sidecars/{filename}.dicom.json`, in the DICOM JSON Model (PS3.18 §F.2) with all header attributes except PixelData and bulk values > 64 KiB (omitted, and listed in `_omitted`). The row references it as `dicom_sidecar` (a `DERIVED:` ref). | M |
| DCM-05 | PHI: sidecars and rows can contain PHI. They stay in the derived root, are never in bundles (PRJ-08), exports or logs, and are shown only in the Image view's "DICOM tags" section on demand. Setting `anonymize: basic` removes the PS3.15 Basic Profile attributes from sidecars and rows and replaces `patient_id` with `case_id` (NFR-17). Rows converted **without** `anonymize` stay as they are in the project, but a bundle export applies `basic` to them (PROJECT_FORMAT §Bundles); the rule lives in `plugins/dicom/sidecar.py`. | M |
| DCM-06 | Dry run = the task estimate (TSK-05): series found / selected / skipped with reasons, and storage per series. | M |
| DCM-07 | Incremental: volumes accumulate in `dataset/` (append-only; existing files are never rewritten). Each run writes the **full current** row set to `runs/{run_id}/metadata.jsonl`, which the backend imports as a new snapshot (IMP-06). A series already converted (same `series_uid` and existing file) is skipped. | M |
| DCM-08 | Manual decisions are curation events (Curation & QC plugin); the converter never writes `curation.csv` or `curated_*` fields. An existing legacy `curation.csv` is imported once as events (CUR-15). | M |
| DCM-09 | A standalone CLI in `plugins/dicom/` (same YAML config as the legacy one) keeps its own resume registry and writes the same clean `metadata.jsonl` as the app (DCM-13); its output folder is imported as a `source` root through `metadata-v1`. | S |
| DCM-10 | A single file: multi-frame (Enhanced CT/MR) → one 3D volume; a classic single slice → a 1-slice volume. | S |
| DCM-11 | DICOM SEG → NIfTI label map registered as a segmentation set (`kind: imported`). | C |
| DCM-12 | Modality values are DICOM codes (`CT`, `MR`, …); the CLI's `MRI` is emitted as `MR`. | M |
| DCM-13 | `metadata.jsonl` is the converter's artifact (ADR-0020): contract v1 core fields + DICOM facts only. No `phase_guess*`, `curated_*`, `group`, `include_guess`, `target_match_*` or other study logic; phase, organ match and readiness are analyzer layers. `analyzer.target` still selects series in-process, but its result is not written to rows. | M |
| DCM-14 | The converter is a workspace task (TSK-13) with its own overlay window (UI-25); inside a project it writes to the project's derived root as today (DCM-07); without one, to `{derived root}/_datasets/{name}/`. The overlay chains `analyzer.phase` after conversion by default (its output is the phase layer). | M |

## Settings (task schema; defaults from `legacy/convert/config.py`)

| Setting | Default | Meaning |
|---|---|---|
| `target_profile` | from the project preset (ANZ-05), else `generic` | Organ focus used by `analyzer.target` |
| `convert_primary` / `convert_secondary` / `convert_excluded` | true / true / false | Which output roles are converted |
| `skip_unsafe_geometry` | false | DCM-03 |
| `mixed_folder_policy` | `split` | `split` \| `fail` when one folder holds several `PatientID`s |
| `patient_pattern`, `patient_limit` | `*`, none | Subset for tests and trials |
| `include_modality_prefix` | true | File name `{scan_idx}_{MOD}_{case_id}_0000.nii.gz` (names don't carry meaning for the app, SRC-07) |
| `sidecars` | true | DCM-04 |
| `anonymize` | `none` | `none` \| `basic` (DCM-05) |

Case identity is **not** a converter setting in the app: it comes from `sources/identity.json` (SRC-07) with strategy `dicom_patient_id` by default.

## Output layout

```text
{DERIVED}/{project_id}/dicom.convert/
├── dataset/                      # append-only (ADR-0014)
│   ├── nifti/{filename}.nii.gz
│   └── sidecars/{filename}.dicom.json
└── runs/{run_id}/
    ├── metadata.jsonl            # full current contract-v1 rows → imported (DCM-07)
    ├── diagnostics.jsonl         # DiagnosticRecord per issue
    └── summary.json              # counts, storage, versions (pydicom, SimpleITK)
```

## Row fields (contract v1 + converter extras)

Core fields as INPUT_METADATA. Converter extras (kept in `extra`, profiled as variables per VAR-08): `patient_folder`, `study_uid`, `series_uid`, `series_number`, `series_description`, `protocol_name`, `body_part`, `dicom_category`, `scan_type`, dates and times, geometry status and codes, `contrast_delay_*`, `spacing_quality`, `dicom_sidecar`. No study guesses or selection results (`output_role`, `exclude_reason` are readiness-analyzer layers; DCM-13).

## Implementation notes (P7b Wave 3)

- Code: `plugins/dicom/{scan,rows,convert,sidecar,pipeline,identity,task,cli}.py` (pydicom + SimpleITK, both core dependencies); analyzers from `plugins/analyzers/` run in-process. Nothing imports `app`.
- `job.json` extras: `source {path}`, `dataset_dir`, `dataset_ref` (`DERIVED:{project_id}/dicom.convert/dataset`), `identity` (the project registry), `previous_metadata` (the last completed run's rows), `project_id`, `context` (phase vocabulary and preset target profile, ANZ-05). `result.json` adds `identity` (merged back, append-only) and `estimate` (the dry run's counts and storage, DCM-06; API-44 `detail`).
- The run's rows are imported as the source `task:dicom.convert` (SOURCES §Imports), so a converted DICOM folder sits next to other imports. Case indices start at 0 (`case_00000`) like the CLI; scan indices are two digits per case in series order (study time, series number, UID).
- Series the readiness analyzer marks `EXCLUDED` (localizer, intervention, < 10 slices, wrong anatomy or modality) are rows with `status: skipped` → `excluded_upstream` items (IMP-07). DICOM SEG series are skipped with the diagnostic `DICOM_SEG_NOT_SUPPORTED` (DCM-11).
- `anonymize: basic` covers a subset of PS3.15 Table E.1-1 (listed in `plugins/dicom/sidecar.py`): identifying and date attributes removed, private tags removed, UIDs replaced by deterministic `2.25.` UIDs (salted with the project id, so reruns keep identity), `PatientID`/`PatientName` = `case_id`; identity keys in `sources/identity.json` become salted hashes. The PHI review of a sidecar remains a human check (ROADMAP §P7b).
- Without `anonymize`, the imported rows (snapshots in `sources/`, extras in `index/`) keep header values such as institution and dates; bundles carry them (open issue for the owner, LANE_NOTES "P7b Wave 3").
- The CLI (`python -m plugins.dicom.cli config.yaml`, needs PyYAML) keeps `.rw_identity.json`, `metadata.jsonl` and `curation.csv` (manual columns preserved) in its output folder; the app imports that folder with `metadata-v1` and its `curation.csv` with API-55 (CUR-15).
