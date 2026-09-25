# Sources, Open mode & identity

Scope: accepted file formats, source adapters, Open mode (no project), case identity policy, NumPy geometry and axis order.
Read when: building import detection, the NIfTI adapter, Open mode, case numbering, or any array ↔ NIfTI conversion.
Depends: ADR-0013, ADR-0024, INPUT_METADATA.md (contract v1), PROJECT_FORMAT.md, DICOM_CONVERTER.md.

Every source becomes **contract v1 rows** (INPUT_METADATA.md); nothing downstream knows which adapter was used.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| SRC-01 | `detect(path)` accepts a folder **or a single file** inside `ALLOWED_DATA_ROOTS`. It returns candidate adapters, each with a reason, file counts and a confidence. The wizard preselects the best one, and the user can switch. | M |
| SRC-02 | Only the formats in §Formats are accepted. Any other file is listed as ignored with its extension; a source with no accepted file is refused with the cause and a next action (SRC-11). | M |
| SRC-03 | Adapter `metadata-v1`: today's importer (IMP-02..08), unchanged. | M |
| SRC-04 | Adapter `nifti-files`: a folder (recursive) or one file. It has a filename pattern with a live preview (§NIfTI files), mask discovery by convention (optional, IMP-11), modality asked once (default `CT`), and phase `UNK`. Geometry comes from headers. | M |
| SRC-05 | A single accepted file can become a one-item project: the parent folder is the root, and the import keeps an include list. | S |
| SRC-06 | Every snapshot has `sources/{import_id}/source.json` = `{adapter, adapter_version, options, detected_at}`, so re-import (IMP-06) reproduces the same rows. | M |
| SRC-07 | Identity policy (§Identity) assigns `case_id` / `scan_idx` for adapters that don't carry them. The registry `sources/identity.json` keeps assignments stable across incremental imports. | M |
| SRC-08 | `case_id` is a URL-safe slug `[A-Za-z0-9_-]{1,64}` (no `.`, because `item_id` uses it). The original name is kept in `extra.source_name`. | M |
| SRC-09 | Open mode (§Open mode): view one file or folder without a project, with the full CT tool set (VW-22) and a Close action (UI-24). Workspace tasks (TSK-13) such as the converter can start from it; project-bound tasks cannot. | M |
| SRC-10 | In Open mode, a segmentation exists only when attached to an open image: a NIfTI file (`.nii`, `.nii.gz`), and only if the shape matches and the affines agree within the IMP-08 tolerance. It is never resampled; a mismatch is refused with both geometries shown. | M |
| SRC-11 | Every refusal is a problem (API §Errors) with `detail` = the cause and `actions[]` = the suggested next steps, e.g. `{"detail": "No metadata.jsonl under the root; 11 NIfTI files found", "actions": ["import_as:nifti-files"]}`. The UI shows both, and never a bare "Validation failed". | M |
| SRC-12 | NumPy arrays are read only with explicit geometry and axis order (§NumPy). There is no silent default. | S |
| SRC-13 | DICOM sources are converted by the task `dicom.convert` (DCM-*). In Open mode, the same convert stage writes to `.scratch/` only. | M |
| SRC-14 | "Save as NIfTI…" in Open mode (API-09) writes the open volume (converted from DICOM/NumPy, or the NIfTI itself) as `.nii.gz` (+ its DICOM JSON sidecar for DICOM, DCM-04) to `{first ALLOWED_DERIVED_ROOTS}/_open/{YYYY-MM-DD}/` by default; the user may change the folder once (remembered in the browser). The destination must be inside `ALLOWED_DERIVED_ROOTS` (never next to the source, R1); names never overwrite (`-1`, `-2` …); an optional `anonymize: basic` checkbox comes with a PHI notice (NFR-17). Written once, never modified. | M |
| SRC-15 | "Add to project…" imports the open file into an existing project as a new import (`nifti-files` for NIfTI, `dicom.convert` for a single DICOM file); it is added next to the project's other sources (§Imports). | S |
| SRC-16 | A workspace dataset (`{derived root}/_datasets/{name}/`, from a workspace task) opens in Open mode and imports through `metadata-v1` like any source root. | M |
| SRC-17 | The `nifti-files` step offers a pattern suggester (§Pattern suggester): candidate `pattern` regexes proposed from the sampled file names, shown with their named groups, picked into the field for the user to edit — never applied without that step. | S |

## Formats

| Kind | Extensions / shape | Image | Label map | Notes |
|---|---|---|---|---|
| NIfTI | `.nii`, `.nii.gz` | ✓ | ✓ | Label map by role only: a mask convention on import (SRC-04), or attach in Open mode (SRC-10); never guessed from values |
| DICOM series | a folder with one or more series | ✓ | | One item per selected series (DCM-*) |
| DICOM single file | one `.dcm` or extension-less DICOM | ✓ | | Multi-frame (Enhanced) → 3D; a classic single slice → a 1-slice volume (2D tiles only, 3D hidden) |
| DICOM SEG | Segmentation Storage SOP class | | later (C) | Refused with "not supported yet" until DCM-11 |
| NumPy | `.npy` (3D, no pickle) | ✓ | ✓ | Needs geometry and axis order (§NumPy); label maps on import only (VOI catalog), not attachable in Open mode; `.npz` refused |

## NIfTI files adapter (SRC-04)

| Option | Default | Meaning |
|---|---|---|
| `pattern` | `^(?P<case_id>.+)$` (one case per stem) | Named groups `case_id`, `scan_idx`, `channel`, `modality`, `phase`, `side`; unmatched files fall back to one case per stem. A `channel` group folds non-`0000` channels into the first. nnU-Net naming is the nnU-Net plugin's (ADR-0024) |
| `case_id_from` | `pattern` | `pattern` · `stem` · `sequential` (identity template, §Identity) |
| `mask_conventions` | `seg/{name}` (also `seg/{name minus _0000}`, the metadata-v1 layout), suffix `_seg` / `_mask` | First match wins; files matched as masks are not items |
| `modality` | `CT` | Applied to all rows; `MR` disables HU presets (VW-05) |
| `include` | all accepted files | Explicit file list (SRC-05) |

Preview shows the parsed columns for the first 50 files and every unmatched name.

### Pattern suggester (SRC-17)

The wizard's Detect step samples the file names `detect()` already listed and proposes 1-3 candidate `pattern` regexes, each shown with its named groups highlighted against a handful of real file names from this root. Picking a candidate only fills the `pattern` field for the user to review and edit before Preview; nothing is inferred or applied automatically. This keeps `nifti-files` free of hidden per-dataset defaults (ADR-0024) while still making a project-specific convention (e.g. `case_id` + `scan_idx` + a `side` laterality suffix, custom mask suffixes) fast to set up.

Implementation notes (P7b Wave 2): the adapter reads file names only (headers are read by the index job) and writes v1 rows with `relative_path`, `seg_path`, `modality`, `source_kind: nifti`, `source_name`. Only channel `0000` (or no channel) becomes an item; other channels of the same case/scan are listed in the row's `channels`. `scan_idx` comes from the pattern, else from the registry. A mask file with no image is reported in `orphan_masks`. With one file chosen explicitly, that file is the item even if it looks like a mask.

## Imports (several sources per project)

Each import has a `source_key`: `{adapter}:{alias}` by default (a re-import of the same root replaces its previous snapshot, IMP-06), `dicom.convert` for converter runs, `add:{alias}:{file}` for SRC-15. The index is the union of the latest snapshot of every source key; when two sources produce the same `item_id`, the later import wins and the item gets `duplicate_row_identity`.

## Identity (SRC-07)

```jsonc
// sources/identity.json (project state; the API process is the only writer)
{ "strategy": "dicom_patient_id",       // dicom_patient_id | filename_pattern | table
  "template": "case_{n:05d}",            // {n} = case index; {key} = the identity key slug
  "start": 0, "next_index": 83,
  "cases": { "<identity key>": 50 },     // identity key → case index; never reused or renumbered
  "scans": { "<identity key>|<series_uid or file>": "01" } }   // 01, 02, … per case, first-seen order
```

- `table`: a CSV `key,case_id` supplied by the user, which takes precedence over the template.
- Tasks (the converter) receive the registry in `job.json` and return new assignments. The backend merges them (append-only: existing keys never change).
- Renumbering an existing project is out of scope. Mistakes are fixed by a new project or a `table` import.
- File names on disk don't have to follow the identity; nnU-Net `{case}_0000` names are produced when a task stages its inputs (TSK-08).

## Open mode (SRC-09/10)

- `POST /open {path}` (API-07) returns an ephemeral session with item-like records (`item_id` = `open.{n}`) from headers only. Nothing is written to any project or to the workspace registry. Sessions live in the API process memory (LRU of 32; gone after a restart); a folder lists at most 500 accepted files. Headers are read in a job worker. Every opened file is an image (ADR-0024).
- DICOM and NumPy are converted into `WORKSPACE_ROOT/.scratch/open/{fingerprint}/`, which is disposable, LRU-purged with `CACHE_MAX_GB`, and never a source for projects.
- Viewer: all layouts. Modality from DICOM when present; otherwise CT is assumed and the user can change it (VW-05). An attached segmentation is shown with auto colours `label_{value}`.
- Curation, tasks and share links are disabled. Open mode offers exactly three actions: **Save as NIfTI…** (SRC-14), **Add to project…** (SRC-15) and **Create project from this** (the import wizard with the path and the detected adapter). No rename, delete or edit; tasks still require a project.
- Attach (SRC-10) takes a NIfTI segmentation from inside the opened folder; anything else is `unsupported-format`, outside the folder the refusal offers `open_folder`.

## NumPy geometry and axis order (SRC-12)

An array has no geometry. The adapter needs all of the following from a sidecar `{name}.npy.json`, from catalog fields (IMP-10), or from the Open dialog:

| Field | Meaning |
|---|---|
| `axis_order` | `xyz` (nibabel convention: `arr[i,j,k]`, i→x) or `zyx` (SimpleITK `GetArrayFromImage`, most Python pipelines: `arr[k,j,i]`) |
| `spacing` | mm, **always listed as x, y, z**, whatever the axis order |
| `affine` *(optional)* | 4×4 NIfTI (RAS) affine; if absent: `diag(spacing)`, origin 0, which is enough for a VOI crop but not aligned with its parent scan |
| `reference_ref` *(optional)* | An image whose shape checks the order: `shape == ref` → `xyz`; `reversed(shape) == ref` → `zyx`; both or neither → ambiguous |

Rules:
- Conversion to NIfTI: `zyx` is transposed `(2,1,0)` before writing, then the affine is applied. Spacing is never permuted, because it is already in x, y, z. `bool` becomes `uint8`.
- Missing `axis_order` with no decisive `reference_ref`: refused (SRC-11, `ambiguous-axis-order` with actions `axis_order:xyz`, `axis_order:zyx`). In Open mode the dialog shows the middle slice in both orders (API-08 `…/preview?axis_order=`) and the user picks; the volume is then served with `?axis_order=`.
- The chosen order and geometry go into `source.json` / the item's `extra.array_geometry`, so every conversion is reproducible.
- Legacy VOIs (IMP-10) are read as `xyz` with catalog spacing, which is today's behaviour. A catalog row may declare `axis_order` (`xyz` | `zyx`); any other value is the QC warning `ambiguous_axis_order` and the row stays `xyz`. The check against the v2 VOI writer needs `legacy/` and is done in P7b Wave 3 (R9); if it wrote `zyx`, the catalog gets `axis_order: zyx`.
- Writing arrays back to NumPy is out of scope.
