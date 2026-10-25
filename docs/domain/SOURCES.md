# Sources, Open mode & identity

Scope: accepted file formats, source adapters, Open mode (no project), case identity policy, NumPy geometry and axis order.
Read when: building import detection, the NIfTI adapter, Open mode, case numbering, or any array ↔ NIfTI conversion.
Depends: ADR-0013, ADR-0024, ADR-0025 (reconstructed sidecars), ADR-0027 (attach anywhere), ADR-0036 (folder per case, mask templates and sets), INPUT_METADATA.md (contract v1), PROJECT_FORMAT.md, DICOM_CONVERTER.md.

Every source becomes **contract v1 rows** (INPUT_METADATA.md); nothing downstream knows which adapter was used.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| SRC-01 | `detect(path)` accepts a folder **or a single file** inside `ALLOWED_DATA_ROOTS`. It returns candidate adapters, each with a reason, file counts and a confidence. The wizard preselects the best one, and the user can switch. | M |
| SRC-02 | Only the formats in §Formats are accepted. Any other file is listed as ignored with its extension; a source with no accepted file is refused with the cause and a next action (SRC-11). | M |
| SRC-03 | Adapter `metadata-v1`: today's importer (IMP-02..08), unchanged; optionally offers reconstructed sidecars (IMP-15, ADR-0025). | M |
| SRC-04 | Adapter `nifti-files`: a folder (recursive) or one file. It has a filename or relative-path pattern with a live preview (§NIfTI files), mask discovery by template or convention (optional, IMP-11; a template may name a mask set folder), modality asked once (default `CT`), and phase `UNK`. Geometry comes from headers. Images that would give the same `(case_id, scan_idx)` are refused, never merged (ADR-0036). | M |
| SRC-05 | A single accepted file can become a one-item project: the parent folder is the root, and the import keeps an include list. | S |
| SRC-06 | Every snapshot has `sources/{import_id}/source.json` = `{adapter, adapter_version, options, detected_at}`, so re-import (IMP-06) reproduces the same rows. | M |
| SRC-07 | Identity policy (§Identity) assigns `case_id` / `scan_idx` for adapters that don't carry them. The registry `sources/identity.json` keeps assignments stable across incremental imports. | M |
| SRC-08 | `case_id` is a URL-safe slug `[A-Za-z0-9_-]{1,64}` (no `.`, because `item_id` uses it). The original name is kept in `extra.source_name`. | M |
| SRC-09 | Open mode (§Open mode): view one file or folder without a project, with the full CT tool set (VW-22) and a Close action (UI-24). Workspace tasks (TSK-13) such as the converter can start from it; project-bound tasks cannot. | M |
| SRC-10 | In Open mode, a segmentation exists only when attached to an open image: a NIfTI file (`.nii`, `.nii.gz`) from anywhere under `ALLOWED_DATA_ROOTS` (ADR-0027), and only if the shape matches and the affines agree within the IMP-08 tolerance. It is never resampled; a mismatch is refused with both geometries shown. An attached segmentation travels into Create project from this / Add to project… (§NIfTI files `masks`). | M |
| SRC-11 | Every refusal is a problem (API §Errors) with `detail` = the cause and `actions[]` = the suggested next steps, e.g. `{"detail": "No metadata.jsonl under the root; 11 NIfTI files found", "actions": ["import_as:nifti-files"]}`. The UI shows both, and never a bare "Validation failed". | M |
| SRC-12 | NumPy arrays are read only with explicit geometry and axis order (§NumPy). There is no silent default. | S |
| SRC-13 | DICOM sources are converted by the task `dicom.convert` (DCM-*). In Open mode, the same convert stage writes to `.scratch/` only. | M |
| SRC-14 | "Save as NIfTI…" in Open mode (API-09) writes the open volume (converted from DICOM/NumPy, or the NIfTI itself) as `.nii.gz` (+ its DICOM JSON sidecar for DICOM, DCM-04) to `{first ALLOWED_DERIVED_ROOTS}/_open/{YYYY-MM-DD}/` by default; the user may change the folder once (remembered in the browser). The destination must be inside `ALLOWED_DERIVED_ROOTS` (never next to the source, R1) and outside the write-once `_datasets/` and every project's `{project_id}/` task tree (NFR-11); names never overwrite (`-1`, `-2` …); an optional `anonymize: basic` checkbox comes with a PHI notice (NFR-17) and then names the file and the sidecar's PatientName / PatientID with a neutral pseudonym `open-{12 hex}` derived from the volume's content fingerprint, never from a folder or file name (AUD-A2-15). Written once, never modified. | M |
| SRC-15 | "Add to project…" imports the open file into an existing project as a new import (`nifti-files` for NIfTI, `dicom.convert` for a single DICOM file); it is added next to the project's other sources (§Imports). | S |
| SRC-16 | A workspace dataset (`{derived root}/_datasets/{name}/`, from a workspace task) opens in Open mode and imports through `metadata-v1` like any source root. | M |
| SRC-17 | The `nifti-files` step builds the `pattern` and `mask_template` by example (§Pattern by example and suggester): the user marks the case (scan, side, channel) in one real image path and picks that image's mask; the raw fields and a suggester of candidate regexes stay available under "Advanced". Nothing is applied without the user seeing it before Preview. | S |
| SRC-18 | DICOM recognition uses validated image headers independent of suffix; directory discovery streams recursively within guarded roots. Open mode groups complete series before applying item/page budgets, and later pages retain stable identities. Partial scans are explicit. | M |
| SRC-19 | Long source discovery/Open/import operations expose recoverable background progress, minimize/restore and cancellation with or without a project. Reconnect retrieves durable server state rather than restarting automatically (TSK-16). | M |

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
| `pattern` | `^(?P<case_id>.+)$` (one case per stem) | Named groups `case_id`, `scan_idx`, `channel`, `modality`, `phase`, `side`. Fullmatched against the stem, or against the relative path without extension when it contains `/` (folder pattern `^(?:.*/)?(?P<case_id>[^/]+)/[^/]+$`: case = the image's parent folder, scans numbered within it). Unmatched files fall back to one case per stem (per path for a `/` pattern). A `channel` group folds non-`0000` channels into the first. nnU-Net naming is the nnU-Net plugin's (ADR-0024) |
| `case_id_from` | `pattern` | `pattern` · `stem` · `sequential` (identity template, §Identity) |
| `mask_conventions` | `seg/{name}` (also `seg/{name minus _0000}`, the metadata-v1 layout), suffix `_seg` / `_mask` | First match wins; files matched as masks are not items |
| `modality` | `CT` | Applied to all rows; `MR` disables HU presets (VW-05) |
| `include` | all accepted files | Explicit file list (SRC-05) |
| `masks` | none | Explicit image → mask pairs (relative paths, both in `include`): the segmentation attached in Open mode (ADR-0027); these files are not items |
| `mask_template` | none | Mask path relative to the root from the pattern's groups plus `{stem}` and `{dir}`, e.g. `labels/{case_id}.nii.gz`; no leading `/` or `..`. Tried before the conventions; files it names are not items. A folder of NIfTI files is a **mask set** (below) |

Mask set (ADR-0036): one binary NIfTI per structure in one folder. Each structure name (file stem) gets one value across the import (sorted names → 1, 2, …), written to the row as `seg_labels` (INPUT_METADATA); the index takes `labels_present` from it without decoding, and seeds an empty label map with the names (PRJ-07). Members must share one geometry (else `unreadable_file`); composition rechecks it and refuses symbolic-link members. Viewer, meshes and radiomics read one label map composed on demand in a worker into `cache/maskset/` (PRJ-10); where structures overlap the higher value wins. Viewer and mesh cache keys use the current member fingerprint, so source edits invalidate cached compositions. Full hashing (IMP-09) skips sets.

A preview whose images give an already used `(case_id, scan_idx)` is refused (`validation`) with the colliding files in `errors[]`; when images sit in subfolders, `actions` offers `use_pattern:{folder pattern}`.

Preview shows the parsed columns for the first 50 files and every unmatched name. The wizard pre-fills `pattern` with the converter's naming `^(?P<scan_idx>\d+)_(?:(?P<modality>[A-Z]{2,3})_)?(?P<case_id>.+)_(?P<channel>\d{4})$` only when every image name being imported follows it, else the folder pattern when file names repeat across folders, with a note; the field stays editable (ADR-0027 §3, ADR-0036, AUD-A2-12). `nifti-files` rows carry phase `UNK` by design: no `ambiguous_phase` unless the pattern gave a phase, and no metadata-v1 `seg/{name}` guess (the adapter's own conventions already ran).

### Pattern by example and suggester (SRC-17)

The Detect step leads with **pattern by example**: one sampled image path (the user can switch to another) is shown as chips, its folders and the file name's `_`/`-`/`.` tokens, each with a role: case, scan, side, channel, "same in every file" or "varies". The wizard generates the `pattern` from those roles (folders all "varies" → a file-name pattern; neighbouring name tokens with one role → one group; digits → `\d+`, letters → `[A-Za-z]+`, side `[LR]`, channel `\d{4}`) and shows how many sampled images it matches, with the groups highlighted. "Choose its mask…" opens the server browser on the chosen folder; the file or folder (a mask set) picked for the example becomes the `mask_template`, with the example's group values put back as fields (a path holding none of them is refused: every image would share one mask). Images that are masks under that template leave the sample count. The raw `pattern` and `mask_template` fields, with the suggester below, stay under "Advanced"; the chips follow a pattern typed there. Code: `frontend/src/features/import/byExample.ts`, `steps/PatternByExample.tsx`.

The wizard's Detect step samples up to 50 relative image paths spread over the chosen folder (API-19 `sample`; the Data root step's listing, API-10, when detection gave none) and proposes 1-3 candidate `pattern` regexes, each shown with its named groups highlighted against a handful of real file names from this root. Picking a candidate only fills the `pattern` field for the user to review and edit before Preview; nothing is inferred or applied automatically. This keeps `nifti-files` free of hidden per-dataset defaults (ADR-0024) while still making a project-specific convention (e.g. `case_id` + `scan_idx` + a `side` laterality suffix, custom mask suffixes) fast to set up.

Rules: the sample is those `.nii`/`.nii.gz`/`.npy` paths without extension, minus masks by the default conventions (`_seg`/`_mask`, `seg/`/`masks/` folders); no files → no suggestion. When file names repeat across folders, the only candidate is the folder pattern, which the wizard also pre-fills (visible, editable, with a note) until the user edits the options (ADR-0036). When the sample is exactly an image folder and its label folder side by side (`ImageTr`/`LabelTr`, `imagesTr`/`labelsTr`: an `image…` and a `label…`/`mask…`/`seg…` folder with the same suffix, under one common parent), the wizard instead pre-fills both the pattern and the mask template in the same way: a case folder per image (`ImageTr/{case}/ct`) with the same mask file or mask set folder under `LabelTr/{case}/`, or flat files (`imagesTr/{case}[_0000]`) with `labelsTr/{case}.nii.gz`; otherwise candidates are built from the file names: A group is proposed only when some sampled name has its piece: a `case` literal + digits → `case_id` (otherwise `case_id` is the rest of the stem), a leading 1-3 digit token → `scan_idx`, a trailing `L`/`R` token → `side`, a trailing 4-digit token → `channel`. A candidate must match at least half of the sample; candidates rank by names matched, then by groups; the default pattern is never proposed. Candidates are Python regexes (the adapter fullmatches the stem). Code: `frontend/src/features/import/patternSuggest.ts`.

Implementation notes: the adapter reads file names only (headers are read by the index job) and writes v1 rows with `relative_path`, `seg_path` (+ `seg_labels` for a mask set), `modality`, `source_kind: nifti`, `source_name` (the stem, or the path for a `/` pattern). Only channel `0000` (or no channel) becomes an item; other channels of the same case/scan are listed in the row's `channels`. `scan_idx` comes from the pattern, else from the registry. A mask file with no image is reported in `orphan_masks`. With one file chosen explicitly, that file is the item even if it looks like a mask.

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

- `POST /open {path}` (API-07) returns an ephemeral session with item-like records (`item_id` = `open.{n}`) from headers only. Nothing is written to any project or to the workspace registry. Compatibility sessions created by this endpoint live in API memory (LRU of 32; gone after a restart); the initial response contains at most 500 complete items, with subsequent items available through API-07 pagination. The Open sidebar displays 50 images per page. Changing pages keeps the current volume; selecting a later item loads its metadata and latest attached segmentation by stable index. Mixed folders expose the converter even when their DICOM series occur after the initial response. Headers are read in a job worker. Every opened file is an image (ADR-0024).
- The UI opens files/folders through API-69 with `purpose=open`. Its owned worker persists complete header units in the inventory and publishes a session only after preparation finishes. Resume reuses unchanged NIfTI/DICOM header units; NumPy is re-probed to account for sidecars/references. The resulting session and attached masks survive API restart, with code/reader compatibility and artifact integrity checks. Close ends the preview; reopening the retained operation explicitly restores its result. This creates no project or converted dataset.
- URL: `/open/{sid}`, never the path (folder names are often patient names, NFR-17; AUD-A1-19). The app hands a path to the route in the history state; the route starts durable opening and hands its opaque operation ID to the shared work window. An unminimized completed opening enters the viewer automatically; a minimized/restored operation offers Open in viewer. Reload and back re-read the session (`GET /open/{sid}`); an ended one (Close, or a compatibility-session restart) shows the problem with "Choose another file or folder" and "Go to the workspace home" (UI-18). The path is shown on the page, from the session.
- DICOM and NumPy are converted into `WORKSPACE_ROOT/.scratch/open/{fingerprint}/`, which is disposable (inside the `CACHE_MAX_GB` budget, DEPLOYMENT) and never a source for projects.
- DICOM cache identity hashes every opened series member through guarded handles and includes reader versions/code (SRC-13).
  Owned conversion revalidates that identity after queueing and immediately before publication; changed inputs leave no new cached volume.
- Viewer: all layouts. Modality from DICOM, else from the `modality` of the `metadata.jsonl` rows of an opened dataset folder (or of the folder above an opened `nifti/`, SRC-16, AUD-A2-10); otherwise CT is assumed and the user can change it (VW-05). An attached segmentation is shown with auto colours `label_{value}`.
- Curation, project-bound tasks and share links are disabled. Workspace conversion remains available (TSK-13). Open mode also offers: **Save as NIfTI…** (SRC-14), **Add to project…** (SRC-15) and **Create project from this** (the import wizard with the path and the detected adapter). No rename, delete or edit.
- Attach (SRC-10, ADR-0027) takes a NIfTI segmentation from anywhere under `ALLOWED_DATA_ROOTS`; the browser starts in a `seg*`/`labels*`/`masks*` folder inside or next to the opened one. Anything else is `unsupported-format`; outside the shared folders it is `path-outside-root`.
- Refusals (SRC-11): a path that does not exist (`not-found`), is outside the shared folders (`path-outside-root`, worded without server settings) or holds nothing to open (`unsupported-format`) offers `choose_another_path` and `home`. The logic lives in `backend/app/sources/open_service.py`; the router only maps (AUD-A6-05).

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
- Legacy VOIs (IMP-10) are read as `xyz` with catalog spacing, which is today's behaviour. A catalog row may declare `axis_order` (`xyz` | `zyx`); any other value is the QC warning `ambiguous_axis_order` and the row stays `xyz`. The check against the v2 VOI writer is settled by the VOI extractor plugin (ROADMAP §Pending plugins); if it wrote `zyx`, the catalog gets `axis_order: zyx`.
- Writing arrays back to NumPy is out of scope.
