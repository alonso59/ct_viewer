# Project Format

Scope: workspace, project folder layout, IDs, path aliases, sharing, file-write rules.
Read when: touching persistence, import, links, relinking, or any file under a project.
Depends: ADR-0002, ADR-0004, ADR-0005, ADR-0014, ADR-0015, ADR-0019, ADR-0020, ADR-0022, ADR-0025.

## Model (QuPath-like)

- A **workspace** is one server-side directory (`WORKSPACE_ROOT`) that holds many projects.
- A **project** is a folder. It references images by **path alias** and never copies them.
- Anyone who can reach the server and has the project link can open and edit it. There is no auth (ADR-0004).

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| PRJ-01 | "New Project" creates a ULID `project_id`, a folder, and `project.json`. | M |
| PRJ-02 | Workspace home lists projects: name, case count, last opened, curation progress. | M |
| PRJ-03 | Every project has a share link `{PUBLIC_BASE_URL}/p/{project_id}`; deep links add `/case/{case_id}` and `?item={item_id}`. | M |
| PRJ-04 | Items store image paths as `ALIAS:relative/posix/path`, never as absolute paths. | M |
| PRJ-05 | "Relink" edits an alias's root path and verifies it on a sample of items via quick fingerprint. | M |
| PRJ-06 | Rename and archive a project (archive moves it to `projects/.archive/` and purges `cache/`). The UI and API **never** delete a project permanently; an admin removes archived folders on the filesystem. | M |
| PRJ-07 | Label map is project-level and editable (name, value, color, default opacity/visibility); seeded from the project preset, or auto-named `label_{value}` from mask values when no preset applies. | S |
| PRJ-08 | Export a project bundle (`.zip` of the project folder without `cache/`, and never image data or DICOM sidecars, NFR-17). | S |
| PRJ-09 | Import a bundle; the relink dialog opens if any alias fails to resolve. | S |
| PRJ-10 | Everything under `index/` and `cache/` is derived and rebuildable; deleting `cache/` is always safe. | M |
| PRJ-11 | `format_version` is checked on open; older versions migrate forward with a backup copy of `project.json` (§Migration 1 → 2). | M |
| PRJ-13 | A project may register one `derived` root (alias `DERIVED`), chosen by the user inside `ALLOWED_DERIVED_ROOTS`; tasks that write volumes require it and ask for it on first use (ADR-0014). | M |
| PRJ-12 | *Superseded by PRJ-16 (ADR-0019).* Study presets chosen at creation. | — |
| PRJ-14 | A project is neutral: "New project" asks for a name and an optional `default_modality` (`CT` default, `MR`, `mixed`), which only sets the viewer default for items without a modality (VW-05). | M |
| PRJ-15 | Settings writes (API-03) need `If-Match` with the project ETag; a stale write gets `412 conflict` and the UI offers reload + reapply. | M |
| PRJ-16 | Study packs (first-party plugin `packs`, PLG-) are applied from Project settings at any time: label map, phase vocabulary + mapping, organ profile (ANZ-05), optional radiomics profile. Applying one records it in `packs[]`; it never deletes curation, labels or data. With no pack, labels come from mask values (PRJ-07) and phases stay raw. | M |
| PRJ-17 | View-only link `/v/{view_token}`: a random, rotatable token served only by the read-only routes (API-60), which never reveal `project_id`; every editing control is hidden. | M |
| PRJ-18 | Project settings view with tabs General · Display · Labels · Data · Plugins (UI-23); `display` holds the layout, the initial W/L per modality (DICOM `WindowCenter/Width` first), editable W/L presets, interpolation and the radiological (default) / neurological convention. | M |

## Folder layout

```text
{WORKSPACE_ROOT}/
├── workspace.json                 # registry: [{project_id, name, created_at, last_opened_at}]
├── .staging/                      # scratch for bundle export/import (PRJ-08/09)
├── .scratch/                      # DISPOSABLE: Open mode conversions (SRC-09), builtin task job dirs (TSK-07)
├── queue/                         # external task jobs + runner heartbeats (TSK-11); the only dir with a second writer
├── plugins/{plugin_id}/           # workspace-level plugin state (PLG-07)
└── projects/
    ├── .archive/
    └── {project_id}/
        ├── project.json           # source of truth for config (schema below)
        ├── sources/               # snapshots of imported input metadata (read-only once written)
        │   ├── {import_id}/metadata.jsonl | phase.json | voi_catalog.jsonl | source.json (adapter, SRC-06)
        │   ├── identity.json      # case identity registry (SRC-07)
        │   └── imports.jsonl      # import history: import_id, files, sha256, row counts, at
        ├── index/                 # DERIVED from sources + project.json
        │   ├── items.jsonl        # normalized viewable items (DATA_MODEL §Item)
        │   ├── cases.jsonl        # case summaries
        │   ├── qc_warnings.jsonl  # validation results (IMP-08)
        │   └── hashes.json        # full SHA-256 per file ref, keyed with its quick fp (IMP-09)
        ├── curation/
        │   ├── events.jsonl       # append-only decisions — SOURCE OF TRUTH (CUR-*)
        │   └── state.json         # DERIVED latest-state snapshot
        ├── variables/
        │   └── catalog.json       # variable types/levels/tags overrides + derived definitions (VAR-11)
        ├── analyses/{analysis_id}/ # spec.json, results/descriptives parquet, recommendations.json (ANA-01)
        ├── radiomics/
        │   ├── profiles/{profile_hash}.json
        │   └── runs/{run_id}/     # run.json, parts/*.parquet, features.parquet, errors.jsonl, run.log
        ├── tasks/runs/{run_id}/   # other task runs: run.json, items.jsonl, log.jsonl, masks.jsonl, annotations.jsonl (TSK-10)
        ├── derived/runs.jsonl     # ledger of files written to the DERIVED root: run, task, refs, sha256 (ADR-0014)
        ├── events/{namespace}.jsonl # core event store per plugin, e.g. labeling (ADR-0022); curation keeps curation/events.jsonl
        ├── plugins/{plugin_id}/   # plugin state, e.g. labeling/tables.json (PLG-07)
        ├── exports/               # user-requested outputs (CSV/Parquet, phase_selections.json PHS-06 ADR-0026); dataset_table.* (ADR-0020) and dataset.jsonl (ADR-0025) are downloads built on demand (API-59), not stored
        ├── cache/                 # DISPOSABLE: meshes, npy→nii conversions
        └── .lock                  # advisory lock held by the API process
```

## `project.json` (format_version 3)

```jsonc
{
  "format": "radiology-workbench-project",
  "format_version": 3,
  "project_id": "01JABCDEF...",            // ULID, immutable
  "name": "ccRCC Dataset820",
  "description": "",
  "created_at": "2026-09-23T10:00:00Z",
  "updated_at": "2026-09-23T10:00:00Z",
  "path_roots": [
    { "alias": "DATA",    "path": "/home/alonso/data/Dataset820", "role": "source" },
    { "alias": "DERIVED", "path": "/home/alonso/derived",          "role": "derived" }   // PRJ-13
  ],
  "label_map": [
    { "value": 1, "name": "kidney", "color": "#00FFFF", "opacity": 0.15, "visible": true },
    { "value": 2, "name": "tumor",  "color": "#FFFF00", "opacity": 0.20, "visible": true },
    { "value": 3, "name": "cyst",   "color": "#FF00FF", "opacity": 0.15, "visible": false }
  ],
  "default_modality": "CT",                  // PRJ-14
  "packs": ["ccrcc"],                        // applied study packs (PRJ-16); [] for a neutral project
  "view_token": null,                        // PRJ-17 (random when created)
  "phase_vocabulary": ["NC", "CMP", "NP", "EP", "UNK"],
  "phase_mapping": { "ART": "CMP", "VEN": "NP", "DELAY": "EP" },   // + aliases, see INPUT_METADATA
  "phase_priority":   ["NP", "CMP", "NC", "EP", "UNK"],
  "display": {                               // PRJ-18 (was viewer_defaults)
    "layout": "four-up",                     // four-up | conventional | three-mpr | one-up-{axial,sagittal,coronal,3d}
    "wl": { "CT": { "ww": 400, "wl": 50 }, "MR": "percentile" },
    "use_dicom_window": true, "wl_presets": null, "interpolation": "linear", "convention": "radiological"
  },
  "segmentations": [                          // ADR-0015
    { "seg_id": "imported", "name": "", "kind": "imported", "producer": null, "label_mapping": { "1": 1, "2": 2, "3": 3 }, "unmatched": [], "created_at": "…" }
  ],
  "default_seg": "imported",
  "annotation_sources": { "phase": null }     // active analyzer run per field (ANZ-04)
}
```

## Path aliases

| Rule | Detail |
|---|---|
| Format | `ALIAS:rel/path` — alias `[A-Z][A-Z0-9_]{0,15}`, POSIX relative path, no `..` |
| Resolution | `realpath(root.path / rel)` must stay inside `root.path` **and** inside `ALLOWED_DATA_ROOTS` (`source`) or `ALLOWED_DERIVED_ROOTS` (`derived`) (OPS-04, OPS-12) |
| Quick fingerprint | `size` + SHA-256 of the first and last 64 KiB. Stored per item and used by relink verification. |
| Full hash | Optional background job (IMP-09); never blocks import |
| Container paths | Recommended mirror mount (host path = container path) so aliases look the same everywhere (OPS-05) |

## Write rules

| File kind | Rule |
|---|---|
| `*.json` | Write to a temp file in the same dir, `fsync`, then atomic `rename`; keep `.bak` of previous version for `project.json` |
| `*.jsonl` (append-only) | Only the API process appends; one JSON object per line, `\n`-terminated, flushed per write |
| Run outputs | Written by workers only inside their own `runs/{run_id}/`; committed by renaming `run.json.tmp` |
| `source` roots | Never opened for writing (R1) |
| `derived` roots | Written only by task runs, inside `{project_id}/{task_id}/runs/{run_id}/` or the task's append-only `dataset/`; finished files are never rewritten; deleted only by a confirmed user action (ADR-0014) |
| `{derived root}/_open/` | Open-mode "Save as NIfTI…" only (SRC-14): new files, never overwritten (`-1`, `-2` … suffixes), never modified afterwards; not part of any project |
| `{derived root}/_datasets/{name}/` | Workspace task outputs only (TSK-13): a new folder per run (`-1`, `-2` … when taken), never modified afterwards. It is readable like a source root (the source guard includes every `{ALLOWED_DERIVED_ROOTS}/_datasets`), so it opens in Open mode and imports as a `source` alias; such an alias may sit under the project's `DERIVED` root because project tasks never write under `_datasets/` |

Single-writer model and locking: BE-05.

## Bundles (PRJ-08/09)

| Rule | Detail |
|---|---|
| Layout | One zip with one top-level folder `{project_id}/` |
| Excluded | `view_token` (reset to null in the bundle, also in `project.json.bak`), `cache/`, `index/variables.parquet` (rebuilt on first access, VAR-01), `.lock`, `.*.tmp`, symlinks, image files (`.nii`, `.nii.gz`, `.npy`, `.npz`, `.nrrd`, `.mha`, `.mhd`, `.dcm`) and DICOM sidecars (`*.dicom.json`) anywhere |
| Export | Built under the project lock in `WORKSPACE_ROOT/.staging/`, deleted after sending |
| Import id | Keeps the bundle's `project_id` unless the workspace already uses it (active or archived); then a new ULID is written to `project.json` |
| Import guards | Zip-slip, symlinks, ≤ 1M entries, ≤ 50 GiB uncompressed; extracted in `.staging/` then renamed into `projects/`; migrations run on open (PRJ-11) |
| Relink | Each alias is resolved and verified (PRJ-05); failures open the relink dialog (API-06 `needs_relink`) |
| PHI | DICOM-derived rows not anonymized at conversion leave with the `basic` profile applied (DCM-05): `sources/*/metadata.jsonl`, `index/items.jsonl` (PHI fields blanked, `patient_id` → `case_id`, UIDs replaced deterministically per project), `index/cases.jsonl` (`patient_id`) and `sources/identity.json` (identity keys hashed as in anonymized runs). Always, whatever the source: `variables/catalog.json` keeps its overrides and definitions but loses profile `top`/`examples`, task `run.json` records lose `selection.source` (an absolute input path), `sources/imports.jsonl` records carry `root: "{alias}:"` instead of the absolute import root, and absolute paths in `index/qc_warnings.jsonl` messages become alias refs (other server folders are elided, `…/`; AUD-A5-02). `project.json` keeps its absolute roots (PRJ-05). The project folder is not changed; an imported copy that converts more data numbers new patients from `next_index` |

## Neutral projects, packs, If-Match, view-only links (P7c Wave 2)

| Rule | Detail |
|---|---|
| New project | Neutral defaults: `label_map: []`, `phase_vocabulary: []`, `phase_mapping: {}`, `phase_priority: ["UNK"]`, `packs: []`. API-02 also takes `packs` (scripts, tests); the UI never sends it (PRJ-14) |
| Packs | `plugins/<id>/pack.json` next to a `plugin.json` that lists the id in `contributes.packs`: `label_map`, `phase_vocabulary`, `phase_aliases` (canonical → raw values), `phase_priority`, `target_profile`, `radiomics_profile`. Shipped: `ccrcc`, `generic-ct` |
| Applying a pack | Pack labels replace the entries with the same value, other labels stay; the vocabulary and priority become the pack's, the mapping is merged; the `imported` set maps the new values; `packs[]` records it once; if the phase rules changed a reindex job starts (API-28 returns its `job_id`) |
| ETag | Strong, over the whole `project.json`; also in the body as `etag`. `If-Match` missing → `428 precondition-required`; stale → `412 precondition-failed` with `actions: ["reload"]`; `*` matches any |
| View token | `secrets.token_urlsafe(24)`; rotation replaces it (the old link is dead at once); bundles reset it to `null` |
| View mirror (API-60) | `/view/{token}` returns the project with `project_id: "view-{token}"`, `read_only: true` and blank root paths; `/view/{token}/{path}` forwards only the read routes listed in `app/api/v1/view.py` (cases, items + image/mask/thumbnail/dicom-tags/mesh, warnings, segmentations, variables, annotations, curation state/events/queue, radiomics and task runs, events, labeling tables) to `/projects/{pid}/…`; anything else is 404, other methods 405. `/view/{token}/jobs` lists the project's jobs (API-41) |
| View redaction | Nothing read through the token carries the real `project_id` or an absolute server path (AUD-A5-03): text bodies (JSON, JSON lines, CSV, problems, SSE events) are rewritten so the id becomes `view-{token}` (e.g. `DERIVED:view-{token}/segment.threshold/…`), a path under a project root its alias ref (`DATA:nifti/…`, also in `advanced` and run `output_dir`) and a path under any other server folder (workspace, allowed roots) loses that prefix (`…/`). Binary bodies (volumes, thumbnails, meshes, Parquet) are unchanged. `include_sensitive=true` stays allowed on view-only exports (owner 2026-09-26) |
| Workspace visibility | A view-only link hides editing; it is not an access control. There are no accounts (ADR-0004), so anyone who can reach the same server can list `GET /projects` and `GET /jobs` (with project ids) and use the full link (PRJ-03) |

## Migration 2 → 3 (PRJ-11)

| Change | Rule |
|---|---|
| `preset` | Becomes `packs: [preset]` (`none` → `[]`); a file without `preset` meant ccRCC, and fields it left to the old model defaults (labels, phase rules) are filled from that pack |
| `default_modality` | `CT` |
| `viewer_defaults` | Moves into `display` with the other keys at their defaults (`one-up` → `one-up-axial`, unknown layouts → `four-up`) |
| `view_token` | `null` until the user creates a view-only link |

## Migration 1 → 2 (PRJ-11)

| Change | Rule |
|---|---|
| `path_roots[].role` | Added; existing roots become `source` |
| Item `mask` | Becomes `masks.imported` at the next index rebuild (the index is derived) |
| `segmentations`, `default_seg` | Set to one `imported` set with the identity `label_mapping` |
| `annotation_sources` | `{}` |
| Curation events | Unchanged; mask targets without `seg_id` mean `imported` |

## Phase configuration (P1b)

- `phase_mapping` keys are RAW values upper-cased → canonical phase. An empty `phase_vocabulary` (preset `none`) keeps raw values.
- Phases are strings from `phase_vocabulary` (no fixed enum). A PATCHed phase configuration applies at the next import.
