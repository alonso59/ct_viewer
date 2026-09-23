# Project Format

Scope: workspace, project folder layout, IDs, path aliases, sharing, file-write rules.
Read when: touching persistence, import, links, relinking, or any file under a project.
Depends: ADR-0002, ADR-0004, ADR-0005.

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
| PRJ-08 | Export a project bundle (`.zip` of the project folder without `cache/`, and never image data). | S |
| PRJ-09 | Import a bundle; the relink dialog opens if any alias fails to resolve. | S |
| PRJ-10 | Everything under `index/` and `cache/` is derived and rebuildable; deleting `cache/` is always safe. | M |
| PRJ-11 | `format_version` is checked on open; older versions migrate forward with a backup copy of `project.json`. | M |
| PRJ-12 | Study presets seed the label map, phase vocabulary and phase mapping at project creation: `ccrcc` (current defaults), `generic-ct` (NC, ART, PV, DELAYED, UNK), `none` (raw values kept). Editable afterwards. | M |

## Folder layout

```text
{WORKSPACE_ROOT}/
├── workspace.json                 # registry: [{project_id, name, created_at, last_opened_at}]
└── projects/
    ├── .archive/
    └── {project_id}/
        ├── project.json           # source of truth for config (schema below)
        ├── sources/               # snapshots of imported input metadata (read-only once written)
        │   ├── {import_id}/metadata.jsonl | phase.json | voi_catalog.jsonl
        │   └── imports.jsonl      # import history: import_id, files, sha256, row counts, at
        ├── index/                 # DERIVED from sources + project.json
        │   ├── items.jsonl        # normalized viewable items (DATA_MODEL §Item)
        │   ├── cases.jsonl        # case summaries
        │   └── qc_warnings.jsonl  # validation results (IMP-08)
        ├── curation/
        │   ├── events.jsonl       # append-only decisions — SOURCE OF TRUTH (CUR-*)
        │   └── state.json         # DERIVED latest-state snapshot
        ├── variables/
        │   └── catalog.json       # variable types/levels/tags overrides + derived definitions (VAR-11)
        ├── analyses/{analysis_id}/ # spec.json, results/descriptives parquet, recommendations.json (ANA-01)
        ├── radiomics/
        │   ├── profiles/{profile_hash}.json
        │   └── runs/{run_id}/     # run.json, parts/*.parquet, features.parquet, errors.jsonl, run.log
        ├── exports/               # user-requested outputs (CSV/Parquet/phase.json proposals)
        ├── cache/                 # DISPOSABLE: meshes, npy→nii conversions
        └── .lock                  # advisory lock held by the API process
```

## `project.json` (format_version 1)

```jsonc
{
  "format": "radiology-workbench-project",
  "format_version": 1,
  "project_id": "01JABCDEF...",            // ULID, immutable
  "name": "ccRCC Dataset820",
  "description": "",
  "created_at": "2026-09-23T10:00:00Z",
  "updated_at": "2026-09-23T10:00:00Z",
  "path_roots": [
    { "alias": "DATA", "path": "/home/alonso/data/Dataset820" }
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
  "viewer_defaults":  { "ww": 400, "wl": 50, "layout": "four-up" }
}
```

## Path aliases

| Rule | Detail |
|---|---|
| Format | `ALIAS:rel/path` — alias `[A-Z][A-Z0-9_]{0,15}`, POSIX relative path, no `..` |
| Resolution | `realpath(root.path / rel)` must stay inside `root.path` **and** inside `ALLOWED_DATA_ROOTS` (OPS-04) |
| Quick fingerprint | `size` + SHA-256 of the first and last 64 KiB. Stored per item and used by relink verification. |
| Full hash | Optional background job (IMP-09); never blocks import |
| Container paths | Recommended mirror mount (host path = container path) so aliases look the same everywhere (OPS-05) |

## Write rules

| File kind | Rule |
|---|---|
| `*.json` | Write to a temp file in the same dir, `fsync`, then atomic `rename`; keep `.bak` of previous version for `project.json` |
| `*.jsonl` (append-only) | Only the API process appends; one JSON object per line, `\n`-terminated, flushed per write |
| Run outputs | Written by workers only inside their own `runs/{run_id}/`; committed by renaming `run.json.tmp` |
| Source data | Never opened for writing (R1) |

Single-writer model and locking: BE-05.
