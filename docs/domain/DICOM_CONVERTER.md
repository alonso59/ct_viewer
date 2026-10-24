# DICOM converter (`dicom.convert`)

Scope: the DICOM → NIfTI task: stages, settings, output layout, metadata fidelity, PHI, incremental runs, geometry safety.
Read when: working on `plugins/dicom/`, DICOM sources, or DICOM metadata.
Depends: ADR-0014, ADR-0017, ADR-0025 (reconstructed sidecars), TASKS.md, SOURCES.md (identity), ANALYZERS.md, INPUT_METADATA.md (contract v1).

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
| DCM-04 | Metadata fidelity: one sidecar per converted series, `sidecars/{filename}.dicom.json`, in the DICOM JSON Model (PS3.18 §F.2) with all header attributes except PixelData and bulk values > 64 KiB (omitted, and listed in `_omitted`). The row references it as `dicom_sidecar` (a `DERIVED:` ref). This is the only **full-fidelity** sidecar; a `metadata-v1` import may instead offer a **reconstructed** one (IMP-15, ADR-0025), which reuses this same file location and DICOM JSON Model shape but carries a `_provenance: {source: "metadata-v1-import", fidelity: "partial"}` marker and only the fields the source row already had — never to be read as equivalent to this one. | M |
| DCM-05 | PHI: sidecars and rows can contain PHI. They stay in the derived root, are never in bundles (PRJ-08), exports or logs, and are shown only in the Image view's "DICOM tags" section on demand. Setting `anonymize: basic` removes the PS3.15 Basic Profile attributes from sidecars and rows and replaces `patient_id` with `case_id` (NFR-17). Rows converted **without** `anonymize` stay as they are in the project, but a bundle export applies `basic` to them (PROJECT_FORMAT §Bundles); the rule lives in `plugins/dicom/sidecar.py`. Reconstructed sidecars (IMP-15) follow the same PHI handling unchanged. | M |
| DCM-06 | Dry run = the task estimate (TSK-05): series found / selected / skipped with reasons, and storage per series: one `series[]` row per series `{case_id, scan_idx, patient, description, modality, n_files, action: convert\|skip, reason, bytes}` (`patient` empty with `anonymize: basic`; `bytes` = estimated `.nii.gz`, 0 when skipped; at most 1000 rows, `series_truncated`). A source without DICOM files, or a dry run with no series, is refused (`unsupported-format`, e.g. "No DICOM files in X; 11 NIfTI files found" with `open`, `import_as:nifti-files`, `choose_another_path`); a run is refused the same way before any dataset folder is made, and a run that still finds no series ends `failed` (AUD-A2-07, AUD-A2-13). | M |
| DCM-07 | Incremental: volumes accumulate in `dataset/` (append-only; existing files are never rewritten). Each run writes the **full current** row set to `runs/{run_id}/metadata.jsonl`, which the backend imports as a new snapshot (IMP-06). Reuse requires a verified DCM-17 commit; an existing file alone is a conflict. Incomplete run rows remain recoverable state and are not automatically imported as a finished snapshot. | M |
| DCM-08 | Manual decisions are curation events (Curation & QC plugin); the converter never writes `curation.csv` or `curated_*` fields. An existing legacy `curation.csv` is imported once as events (CUR-15). | M |
| DCM-09 | A standalone CLI in `plugins/dicom/` (same YAML config as the legacy one) keeps its own resume registry and writes the same clean `metadata.jsonl` as the app (DCM-13); its output folder is imported as a `source` root through `metadata-v1`. | S |
| DCM-10 | A single file: multi-frame (Enhanced CT/MR) → one 3D volume; a classic single slice → a 1-slice volume. | S |
| DCM-11 | DICOM SEG → NIfTI label map registered as a segmentation set (`kind: imported`). | C |
| DCM-12 | Modality values are DICOM codes (`CT`, `MR`, …); the CLI's `MRI` is emitted as `MR`. | M |
| DCM-13 | `metadata.jsonl` is the converter's artifact (ADR-0020): contract v1 core fields + DICOM facts only. No `phase_guess*`, `curated_*`, `group`, `include_guess`, `target_match_*` or other study logic; phase, organ match and readiness are analyzer layers. `analyzer.target` still selects series in-process, but its result is not written to rows. | M |
| DCM-14 | The converter is a workspace task (TSK-13) with its own overlay window (UI-25); inside a project it writes to the project's derived root as today (DCM-07); without one, to `{derived root}/_datasets/{name}/`. The overlay chains `analyzer.phase` after conversion by default (its output is the phase layer). | M |
| DCM-15 | Versioned bounded inventories are shared by discovery, dry run and conversion. Changed source/settings/scanner generations invalidate affected plans; cursors bind to a generation. No slice is removed by a UI page/file limit. | M |
| DCM-16 | Discovery and dry run are durable background operations (TSK-16) with complete paged series/plan reads, stage-specific counters, provisional totals and explicit diagnostics. Dry run never decodes pixels or produces final image artifacts. | M |
| DCM-17 | Interrupted/cancelled/partially failed conversions resume under the same logical run and original output allocation using a fresh fenced attempt after verified cleanup. Validate pinned strong inputs/settings/reader versions and committed output hashes/geometry/sidecars; skip only verified commits, reconcile partial commits and register each output/import once. Changed inputs or corrupt outputs require an actionable conflict. Completed datasets remain sealed. | M |
| DCM-18 | Cancel is durable and idempotent, stops dispatch, and acknowledges terminal cancellation only after owned DICOM execution stops and temporaries are reconciled. Uncertain cleanup blocks replacement/resume. Unrelated pool jobs/processes are unaffected (BE-16). | M |
| DCM-19 | ETA reports compatible local measurements, range, basis and sample confidence; without sufficient history it is unknown. Update from committed series, exclude completed work on resume and interruption downtime, and account for analyzer time separately. Estimate performs no hidden pixel calibration. | M |

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

For DCM-17, **Retry failed series** selects the latest recorded failures across native attempts.
It verifies existing commits and processes only those failures; unattempted series remain pending.
**Resume pending work** continues the original selection. Both preserve the run, output allocation
and strong plan pins. A retry with pending series ends `interrupted`; it neither advertises a
completed workspace dataset nor starts phase analysis or project registration. The window reports
completed/failed/pending counts and the original destination. Phase retry requires completed conversion.

## Output layout

```text
{DERIVED}/{project_id}/dicom.convert/
├── dataset/                      # append-only (ADR-0014)
│   ├── nifti/{filename}.nii.gz
│   ├── nifti/.checkpoints/{filename}/  # DCM-17 prepared/committed manifests and owned staging
│   └── sidecars/{filename}.dicom.json
└── runs/{run_id}/
    ├── metadata.jsonl            # full current contract-v1 rows → imported (DCM-07)
    ├── conversion-pin.json      # strong selected inputs, settings/reader and identity allocation
    ├── diagnostics.jsonl         # DiagnosticRecord per issue
    └── summary.json              # counts, storage, versions (pydicom, SimpleITK)
```

## Row fields (contract v1 + converter extras)

Core fields as INPUT_METADATA. Converter extras (kept in `extra`, profiled as variables per VAR-08): `patient_folder`, `study_uid`, `series_uid`, `series_number`, `series_description`, `protocol_name`, `body_part`, `dicom_category`, `scan_type`, dates and times, geometry status and codes, `contrast_delay_*`, `spacing_quality`, `dicom_sidecar`. No study guesses or selection results (`output_role`, `exclude_reason` are readiness-analyzer layers; DCM-13).

## Implementation notes

- Rows are cleaned at the end of `pipeline.run` (`clean_row`: `STUDY_FIELDS` = `target_match_level`, `output_role`, `include_guess`, `exclude_reason`, `analysis_readiness`, `group`, `notes`, plus every `phase_guess*`, `curated_*`, `target_match*` key), also for legacy rows carried over from a previous run (DCM-07). The analyzers still run in-process for selection; their results leave only as annotations. Converter version 1.1.0. Rows also carry `window_center` / `window_width` (first values of the header's multi-values, VW-22).
- Setting `phase_analyzer` (default on): phase rules execute only after successful native commits; off invokes no phase rules (DCM-14). Checkpoint ownership and layer activation live in ANALYZERS.md (ANZ-02/04). Contrast delay is a metadata fact shared with the analyzer; phase vocabulary no longer pins native conversion settings. The CLI writes the same clean `metadata.jsonl` and `.rw_identity.json`; it no longer writes `curation.csv` (an old one is left untouched for CUR-15).
- Workspace runs (`scope: workspace`, TSK-13): output `{first ALLOWED_DERIVED_ROOTS}/_datasets/{name}/` = `metadata.jsonl` (paths relative to the dataset: `nifti/…`, `sidecars/…`; an import turns a relative `dicom_sidecar` into a ref under its alias like `relative_path`, INPUT_METADATA, AUD-A2-04), `nifti/`, `sidecars/`, `diagnostics.jsonl`, `summary.json`, `annotations.jsonl` (the analyzer layers) and `dataset.json` (`{dataset: 1, name, task, run_id, source, settings, created_at, counts}`). Identity starts empty (`case_00000`, …); `anonymize` salts with an empty project id. Without a `name` the dataset is `dataset-{YYYY-MM-DD}` (the overlay suggests the same), never the source folder's name, which is often a patient name (NFR-17, AUD-A5-16). A taken name gets `-1`, `-2` …; the overlay says so in its settings step, and the workspace home lists the completed datasets (UI-04, AUD-A2-14).
- The import wizard's in-project conversion (detect → "DICOM → NIfTI conversion") offers the same `anonymize` checkbox and PHI notice as the overlay (DCM-05).
- Scan cost (DCM-06): bounded doubling reads from `HEAD_BYTES` to `MAX_HEADER_BYTES` (currently 16 KiB / 8 MiB), parsed with pydicom `stop_before_pixels`, retaining `SCAN_TAGS`. A PixelData byte pattern inside a private value triggers bounded parser retries, never a whole-file fallback. Four header threads group by folder and SeriesInstanceUID; inspection reuses those facts. Inventory-backed Estimate restats cached facts and reads a full header only for each series' sidecar facts. Unknown/absent suffixes share image-header validation through the task boundary.
- Inventory reuse pins scanner/guard code, reader version, selected tags and effective header budget in each cached signature; changed contracts invalidate facts and plan-page generations during scanning. Historical reads alone do not invalidate records. Quota/batch deployment behavior is owned by DEPLOYMENT.md; partial folders never expose a slice prefix as a complete series.
- DCM-16 progress counts committed selected series, including verified reused commits; skipped/failed units never increment it.
  Header/verification/analyzer stages retain their own counters and units. Records retain the last confirmed progress after completion/restart.
  Late native callbacks are fenced by the active job ID and cannot rewrite a later attempt's status, counters or cleanup proof.
- Pixel reads use the complete pinned member list in physical slice order. On Linux OCI, native GDCM receives file descriptors opened through the guarded source chain; a later pathname/symlink replacement cannot redirect the read. A series exceeding the available descriptor budget fails actionably. The native writer preserves ITK geometry (DCM-02).
- DCM-17 commits: `nifti/.checkpoints/{filename}/commit.json` pins strong input digests, settings/reader versions, output hashes and world geometry. Image and required sidecar are staged and fsynced before a prepared record, published without overwrite, then marked committed before progress. Recovery verifies matching published/staged artifacts before adopting a prepared commit. API conversion runs additionally pin all selected input content and case/scan allocations before pixels in `conversion-pin.json`. Existing outputs without a checkpoint are preserved and reported as a conflict; no automatic legacy adoption is claimed.
- Staging directory entries are synced before the prepared record; adopted image/sidecar parent directories are synced before the commit. Project registration completion additionally verifies successful indexing. An older completion receipt without that proof is reconciled once. Restart recovery uses an existing job-service metadata job, preserving the conversion attempt, output allocation and images; polling stays responsive and reports registration separately. A failed index remains actionable until registration is retried.
- Registration Cancel fences generated-import dispatch, records its intent and drains the existing index workers before reporting cancelled. It preserves committed images/imports and the completed native attempt. A metadata-only Resume is refused during draining and becomes available once registration stops; restart reconciles an acknowledged cancellation without converting pixels. An unfinished shutdown drain is not completion evidence.
- Control replay reconfirms its metadata write before acknowledgment. A creation receipt reserves one operation before discovery dispatch; retry recovers an unlaunched discovery/Estimate or conversion handoff in the same attempt and refuses retained execution evidence or lost committed state. Write-error semantics are owned by PROJECT_FORMAT.md §Write rules. Reads reconcile stopped source jobs whose final publication failed, retaining `cleanup_pending` until cleanup is verified.
- Native completion records pending registration in the same write, before entering the finalizer. The operation cannot advertise a completed import during that handoff; analyzer failure remains independent.
- DCM-18 execution: inventory, async Estimate and project/workspace converter tasks use owned in-image processes with a parent-death/dispatch handshake. One durable workspace admission lease serializes these attempts, including synchronous estimate adapters; unknown cleanup retains the lease. Attempt evidence lives with the run/operation. A private participating allocation now serializes DICOM (including lazy Open conversion) with the configured runner; pool identity is checked before launches. Explicit memory admission, native-process CPU affinity and address-space limits are applied only to the owned child; oversized work releases the slot and waits. Configuration/defaults and limitations live in DEPLOYMENT.md; complete BE-16 acceptance, including all shared-worker/multi-workspace and cross-container recovery cases, remains in progress.
- Workspace resume (API-62) retains its unfinished run and dataset allocation, increases the attempt generation, and checks prior cleanup. Completed datasets remain sealed. `dataset.json` is emitted only after conversion completes without failed series or cancellation; partially failed metadata is retained without advertising a ready dataset. Full restart/finalization/registration crash acceptance remains tracked by the test plan.

- Stages (`pipeline.Stage`, `Job.stage` → `{"t": "stage", stage, done, total}` in `progress.jsonl`, at most every 0.25 s): `listing` folders → `reading` headers (files) → `planning` (dry run) or `converting` series. API-62 serves a named dry run's last stage; a run carries it in `progress` (UI-25).
- pydicom and SimpleITK are core dependencies; the plugin never imports `app`.
- `job.json` extras: `source {path}`, `dataset_dir`, `dataset_ref` (`DERIVED:{project_id}/dicom.convert/dataset`), `identity` (the project registry), `previous_metadata` (the last completed run's rows), `project_id`, `context` (phase vocabulary and preset target profile, ANZ-05). `result.json` adds `identity` (merged back, append-only) and `estimate` (the dry run's counts and storage, DCM-06; API-44 `detail`; a dry run adds `series_plan`, returned as `series[]`; shared by project and workspace estimates in `backend/app/tasks/dry_run.py`).
- The run's rows are imported as the source `task:dicom.convert` (SOURCES §Imports), so a converted DICOM folder sits next to other imports. Case indices start at 0 (`case_00000`) like the CLI; scan indices are two digits per case in series order (study time, series number, UID).
- Series the readiness analyzer marks `EXCLUDED` (localizer, intervention, < 10 slices, wrong anatomy or modality) are rows with `status: skipped` → `excluded_upstream` items (IMP-07). DICOM SEG series are skipped with the diagnostic `DICOM_SEG_NOT_SUPPORTED` (DCM-11).
- `anonymize: basic` covers a subset of PS3.15 Table E.1-1 (listed in `plugins/dicom/sidecar.py`): identifying and date attributes removed, private tags removed, UIDs replaced by deterministic `2.25.` UIDs (salted with the project id, so reruns keep identity), `PatientID`/`PatientName` = `case_id`; identity keys in `sources/identity.json` become salted hashes. The PHI review of a sidecar remains a human check (ROADMAP §P7b).
- The CLI (`python -m plugins.dicom.cli config.yaml`, needs PyYAML) retains the existing YAML keys, `.rw_identity.json` and clean `metadata.jsonl`; an existing `curation.csv` is preserved for CUR-15. The app imports its output with `metadata-v1`.
- CLI conversion holds an exclusive kernel file lock for its output root and persists a versioned `.rw_active.json` journal with logical run ID and fresh attempt identity. Private `.rw-runs/{id}/pin.json` uses the pipeline's DCM-17 input/settings/reader/identity pins; its hash is journaled before pixel dispatch. Reinvocation resumes an unfinished run; after completion it starts a new incremental run using the existing identity registry. Missing/corrupt/incompatible pins or changed unfinished source/settings require recovery or a new output root. Source/output overlap and escaping output paths are refused before pipeline entry.
- CLI success is exit code 0; failed series, incomplete work, conflicts or another writer return 1. Configuration/access errors omit file paths and YAML values from stderr. Dry run does not create or modify output state and never reads pixels. Metadata and identity writes finish durably before the journal reports completion.
- CLI `mode: retry_failed` selects failures from the unfinished run's private, fsynced `outcomes.jsonl`. It leaves unattempted series pending (exit 1, `interrupted`); ordinary conversion resumes them. Empty failure selections and completed runs refuse this mode. Missing/legacy histories require normal resume; complete corrupt records require recovery. A torn final fragment is retained privately before repairing the append boundary. Output locking and DCM-17 verification still apply.
