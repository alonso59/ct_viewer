# Input Metadata & Import

Scope: accepted input files, import wizard, normalization into items, QC warnings.
Read when: building import, indexing, phase resolution, or validation.
Depends: PROJECT_FORMAT.md, DATA_MODEL.md.

"Upload" means registering **metadata plus a data root path**. Image bytes are never uploaded or copied (ADR-0005).

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| IMP-01 | The import wizard picks a data root through a server-side folder browser limited to `ALLOWED_DATA_ROOTS`. The root becomes alias `DATA`, which the user can rename. | M |
| IMP-02 | Auto-detect `metadata.jsonl`, `phase.json`, and `voi/voi_catalog.jsonl` under the root; alternatively upload them from the browser (multipart, metadata only). | M |
| IMP-03 | Preview before commit: row counts, case count, and the first 50 parse/validation errors, plus a detected field mapping. | M |
| IMP-04 | Commit snapshots the inputs to `sources/{import_id}/` with SHA-256 and appends to `imports.jsonl`. | M |
| IMP-05 | Indexing runs as a job (progress, cancel) and builds `index/items.jsonl`, `index/cases.jsonl`, and the quick fingerprints. | M |
| IMP-06 | Re-import creates a new snapshot and rebuilds the index. `item_id` is deterministic, so curation events stay attached. | M |
| IMP-07 | Items that were skipped or excluded upstream are indexed as `excluded_upstream` and hidden by default. | S |
| IMP-08 | Validation writes `index/qc_warnings.jsonl` (codes below); warnings show in the Problems panel (UI-09). | M |
| IMP-09 | Optional "Compute full hashes" job adds SHA-256 per file, stored in `index/hashes.json` keyed by ref + quick fingerprint (a changed file loses its hash); `force` rehashes all. | C |
| IMP-10 | Legacy `.npy` VOIs are accepted; they are converted to NIfTI in `cache/` on first view, using catalog spacing. | S |
| IMP-11 | Metadata-only mode: a project may be indexed without a seg or VOI catalog; the viewer adapts (VW-12). | M |
| IMP-12 | Thumbnail job (after indexing, in workers): a 128 px mid-axial slice at the default W/L for each `complete` item, with a mask outline if one exists; stored in `cache/thumbs/{image_fp}.webp` (UI-08). | S |

## Input files (contract v1, from the v2 converter/preprocessor)

**Core** = the fields below marked ✓ plus `phase`, `seg_path`, `side`, `image_path`, `mask_path`, `modality`. Only core fields have fixed meaning.
**Every other field** (including `group` if present) is a study variable, profiled and typed on import (VARIABLES.md, ADR-0011).

### `metadata.jsonl`: one line per converted scan

| Field | Req | Use |
|---|---|---|
| `case_id` | ✓ | `case_\d{5}` |
| `scan_idx` | ✓ | Scan index within case (string, e.g. `01`) |
| `filename` or `relative_path` or `nifti_file` | ✓ | Identity: first non-empty of the three. Image location: `relative_path` → `nifti_file` (absolute legacy) → `nifti/{filename}` |
| `patient_id`, `dataset_id`, `modality` | | Display; `modality` gates CT-only defaults (VW-05, RAD); parsed into `Item.modality` and also kept in `extra` |
| `study_uid`, `series_uid` | | Provenance (advanced) |
| `phase`, `curated_phase`, `canonical_phase`, `phase_guess`, `phase_guess_confidence` | | Phase resolution (below) |
| `seg_path` | | Explicit SEG; else convention `seg/{filename minus _0000}` |
| `status`, `planned_conversion`, `curated_keep` | | Upstream skip/exclude (IMP-07) |

### `phase.json`: optional phase overrides

```jsonc
{ "schema_version": 1, "updated_at": "…",
  "phases": [ { "case_id": "case_00001", "scan_idx": "01", "phase": "NP" } ] }
// legacy form also accepted: { "phase_by_filename": { "01_case_00001_0000.nii.gz": "NP" } }
```

### `voi/voi_catalog.jsonl`: one line per VOI crop

| Field | Req | Use |
|---|---|---|
| `voi_id` | | Stable VOI ID if present |
| `case_id`, `scan_idx` | ✓ | Link to parent scan |
| `side` | ✓ | `L` / `R` (also accepts `sideL`/`sideR`, `_L`/`_R`) |
| `image_path`, `mask_path` | ✓ / | VOI image / mask, relative to data root |
| `phase` | | Informational; phase is **never** inferred from folders. `{group}` path segments are ignored |
| any metrics | | Kept in `extra` |

## Phase resolution

Resolution order: `phase.json` override → `curated_phase` → `canonical_phase` → `phase` → `phase_guess`.
The chosen value is kept as `raw_phase` and normalized with the project's `phase_vocabulary` + `phase_mapping` (PRJ-12). Table below = **ccRCC preset**: **NC · CMP · NP · EP · UNK** (NC = non-contrast, CMP = corticomedullary, NP = nephrographic, EP = excretory, UNK = unknown):

| Raw (case-insensitive) | Canonical |
|---|---|
| `NC`, `NONCONTRAST`, `NON-CONTRAST` | `NC` |
| `ART`, `ARTERIAL`, `CMP`, `CORTICOMEDULLARY` | `CMP` |
| `VEN`, `VENOUS`, `NP`, `NEPHROGRAPHIC`, `PORTAL` | `NP` |
| `EP`, `DELAY`, `DELAYED`, `EXC`, `EXCRETORY` | `EP` |
| empty, `UNDEFINED`, `UNKNOWN`, `N/A`, `NONE` | `UNK` |

Mapping ART→CMP and VEN→NP was clinically confirmed by the project owner (2026-09-23).

`phase_source` records which field won. Curator phase proposals do **not** change the index (CUR-06).

## QC warning codes

| Code | Severity | Meaning |
|---|---|---|
| `missing_path` | error | Referenced file does not exist |
| `unreadable_file` | error | Exists but cannot be opened or has an invalid header |
| `outside_root` | error | Resolves outside its alias root or `ALLOWED_DATA_ROOTS` |
| `missing_seg` | warning | Scan has no SEG |
| `missing_voi_image` / `missing_voi_mask` | warning | VOI part missing |
| `missing_affine` | warning | No usable affine |
| `affine_mismatch` / `shape_mismatch` | error | Mask geometry ≠ image geometry |
| `ambiguous_phase` | warning | Resolved to `UNK`, or conflicting sources |
| `ambiguous_side` | warning | Side unparseable, or both sides map to the same file |
| `duplicate_row_identity` | error | Two rows produce the same `item_id` |
| `fingerprint_changed` | warning | File changed since indexing |

Warning record: `{code, severity, item_id?, case_id?, field?, path_ref?, message, detected_at}`.
