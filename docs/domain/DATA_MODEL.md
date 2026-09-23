# Data Model

Scope: entities, IDs, relations, and where each entity is persisted.
Read when: designing any schema, API payload, or UI list.
Depends: PROJECT_FORMAT.md.

## Entity map

```text
Workspace 1─* Project 1─* PathRoot
                    1─* Import
                    1─* Case 1─* Scan 1─* Item (scope=complete | voi[L/R])
                    1─* CurationEvent  *─1 Item | Case
                    1─* RadiomicsProfile 1─* RadiomicsRun 1─* FeatureValue *─1 Item
                    1─* Job
```

## Entities

| Entity | Key | Persisted in | Notes |
|---|---|---|---|
| Workspace | `WORKSPACE_ROOT` | `workspace.json` | Registry of projects |
| Project | `project_id` (ULID) | `project.json` | PRJ-01 |
| PathRoot | `alias` | `project.json.path_roots` | PRJ-04 |
| Import | `import_id` (ULID) | `sources/imports.jsonl` | IMP-04 |
| Case | `case_id` | `index/cases.jsonl` (derived) | Group of scans |
| Scan | `(case_id, scan_idx)` | implied by Items | One acquisition / phase |
| Item | `item_id` | `index/items.jsonl` (derived) | **Viewable unit**; the target of curation and radiomics |
| QCWarning | `(code, item_id/case_id)` | `index/qc_warnings.jsonl` | IMP-08 |
| CurationEvent | `event_id` (ULID) | `curation/events.jsonl` | Append-only (CUR-*) |
| RadiomicsProfile | `profile_hash` | `radiomics/profiles/` | Content hash of normalized settings (RAD-03) |
| RadiomicsRun | `run_id` (ULID) | `radiomics/runs/{run_id}/run.json` | RAD-06 |
| FeatureValue | `(run_id, item_id, label, feature)` | `features.parquet` | Long format |
| Job | `job_id` (ULID) | in memory + `run.json` / index status | BE-06 |

## `item_id`

Deterministic, URL-safe: `{case_id}.{scan_idx}.{scope}.{side}`, with `side` ∈ `L|R|-`.
Examples: `case_00001.01.complete.-`, `case_00001.01.voi.L`.

## Item (index record)

```jsonc
{
  "item_id": "case_00001.01.voi.L",
  "case_id": "case_00001", "scan_idx": "01", "scope": "voi", "side": "L",
  "patient_id": "…", "group": "A",
  "phase": { "canonical": "NP", "raw": "VEN", "source": "phase.json" },
  "image": { "ref": "DATA:voi/images/A/NP/01_case_00001_L.nii.gz", "format": "nifti", "fp": "…" },
  "mask":  { "ref": "DATA:voi/mask/A/NP/01_case_00001_L.nii.gz",  "format": "nifti", "fp": "…" },
  "geometry": { "shape": [128,128,96], "spacing": [0.8,0.8,1.0], "dtype": "int16", "orientation": "RAS" },
  "labels_present": [1, 2],
  "status": "active",              // active | excluded_upstream | missing
  "warning_codes": ["missing_seg"],
  "import_id": "01J…",
  "extra": { }                     // unknown input fields, preserved
}
```

## Case summary (derived)

`{case_id, patient_id, group, phases[], n_scans, n_items, has_seg, has_voi_L, has_voi_R, n_warnings, curation_status, last_reviewed_at}`.
The `curation_status` rollup is defined in CUR-08.

## Conventions

- Timestamps are UTC ISO-8601 with `Z`. IDs are ULIDs except `item_id`, `case_id` and `profile_hash`.
- All paths in persisted records are alias refs (PRJ-04); absolute paths only appear in API responses under `advanced`.
- Enums are lower_snake_case, except phase codes (uppercase).
