# Project Format

Scope: workspace, project folder layout, IDs, path aliases, sharing, file-write rules.
Read when: touching persistence, import, links, relinking, or any file under a project.
Depends: ADR-0002, ADR-0004, ADR-0005, ADR-0014, ADR-0015.

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
| PRJ-12 | Study presets seed the label map, phase vocabulary and phase mapping at project creation: `ccrcc` (current defaults), `generic-ct` (NC, ART, PV, DELAYED, UNK), `none` (raw values kept). Editable afterwards. | M |

## Folder layout

```text
{WORKSPACE_ROOT}/
├── workspace.json                 # registry: [{project_id, name, created_at, last_opened_at}]
├── .staging/                      # scratch for bundle export/import (PRJ-08/09)
├── .scratch/                      # DISPOSABLE: Open mode conversions (SRC-09), builtin task job dirs (TSK-07)
├── queue/                         # external task jobs + runner heartbeats (TSK-11); the only dir with a second writer
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
        ├── tasks/runs/{run_id}/   # other task runs: run.json, annotations.jsonl, features, errors (TSK-10)
        ├── derived/runs.jsonl     # ledger of files written to the DERIVED root: run, task, refs, sha256 (ADR-0014)
        ├── exports/               # user-requested outputs (CSV/Parquet/phase.json proposals)
        ├── cache/                 # DISPOSABLE: meshes, npy→nii conversions
        └── .lock                  # advisory lock held by the API process
```

## `project.json` (format_version 2)

```jsonc
{
  "format": "radiology-workbench-project",
  "format_version": 2,
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
  "preset": "ccrcc",                         // PRJ-12
  "phase_vocabulary": ["NC", "CMP", "NP", "EP", "UNK"],
  "phase_mapping": { "ART": "CMP", "VEN": "NP", "DELAY": "EP" },   // + aliases, see INPUT_METADATA
  "phase_priority":   ["NP", "CMP", "NC", "EP", "UNK"],
  "viewer_defaults":  { "ww": 400, "wl": 50, "layout": "four-up" },
  "segmentations": [                          // ADR-0015
    { "seg_id": "imported", "kind": "imported", "producer": null, "label_mapping": { "1": 1, "2": 2, "3": 3 }, "created_at": "…" }
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

Single-writer model and locking: BE-05.

## Bundles (PRJ-08/09)

| Rule | Detail |
|---|---|
| Layout | One zip with one top-level folder `{project_id}/` |
| Excluded | `cache/`, `.lock`, `.*.tmp`, symlinks, image files (`.nii`, `.nii.gz`, `.npy`, `.npz`, `.nrrd`, `.mha`, `.mhd`, `.dcm`) and DICOM sidecars (`*.dicom.json`) anywhere |
| Export | Built under the project lock in `WORKSPACE_ROOT/.staging/`, deleted after sending |
| Import id | Keeps the bundle's `project_id` unless the workspace already uses it (active or archived); then a new ULID is written to `project.json` |
| Import guards | Zip-slip, symlinks, ≤ 1M entries, ≤ 50 GiB uncompressed; extracted in `.staging/` then renamed into `projects/`; migrations run on open (PRJ-11) |
| Relink | Each alias is resolved and verified (PRJ-05); failures open the relink dialog (API-06 `needs_relink`) |

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
