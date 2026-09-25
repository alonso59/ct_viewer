# Data Model

Scope: entities, IDs, relations, and where each entity is persisted.
Read when: designing any schema, API payload, or UI list.
Depends: PROJECT_FORMAT.md, ADR-0019, ADR-0020, ADR-0022, ADR-0026.

## Entity map

```text
Workspace 1─* Project 1─* PathRoot (role: source | derived)
                    1─* Import 1─1 SourceSnapshot (adapter)
                    1─1 IdentityRegistry
                    1─* SegmentationSet 1─* (Item.masks)
                    1─* TaskRun 1─* Annotation *─1 Item
                    1─* Case 1─* Scan 1─* Item (scope=complete | voi[L/R])
                    1─* CurationEvent  *─1 Item | Case
                    1─* RadiomicsProfile 1─* RadiomicsRun 1─* FeatureValue *─1 Item
                    1─* Job
                    *─* Pack (applied)   1─* LabelTable 1─* LabelColumn
                    1─* EventNamespace (curation, labeling, phase, …)   Layers = analyzer runs + label columns + curation state + phase selection
                    1─* Variable (catalog)   1─* Analysis *─1 RadiomicsRun
```

## Entities

| Entity | Key | Persisted in | Notes |
|---|---|---|---|
| Workspace | `WORKSPACE_ROOT` | `workspace.json` | Registry of projects |
| Project | `project_id` (ULID) | `project.json` | PRJ-01 |
| PathRoot | `alias` | `project.json.path_roots` | PRJ-04; `role` `source` \| `derived` (ADR-0014) |
| Import | `import_id` (ULID) | `sources/imports.jsonl` + `sources/{import_id}/source.json` | IMP-04, SRC-06 |
| IdentityRegistry | — | `sources/identity.json` | SRC-07 |
| SegmentationSet | `seg_id` (slug) | `project.json.segmentations` | ADR-0015 |
| TaskRun | `run_id` (ULID) | `tasks/runs/{run_id}/run.json` (radiomics: `radiomics/runs/`) | TSK-10 |
| Annotation | `(run_id, item_id, field)` | `tasks/runs/{run_id}/annotations.jsonl` | ANZ-01; a metadata layer (ADR-0020) |
| Pack | `pack_id` | plugin manifest; applied list in `project.json.packs` | PRJ-16 |
| LabelTable | `table_id` (ULID) | `plugins/labeling/tables.json` | LBL-01/02 |
| LabelCell | `(table_id, column_id, target)` | `events/labeling.jsonl` (derived state) | LBL-04 |
| EventNamespace | name | `events/{namespace}.jsonl` (`curation` keeps `curation/events.jsonl`) | ADR-0022 |
| PhaseEvent | `(case_id, scan_idx)` latest | `events/phase.jsonl` | Append-only, native, not plugin-owned (PHS-*, ADR-0026) |
| Case | `case_id` | `index/cases.jsonl` (derived) | Group of scans |
| Scan | `(case_id, scan_idx)` | implied by Items | One acquisition / phase |
| Item | `item_id` | `index/items.jsonl` (derived) | **Viewable unit**; the target of curation and radiomics |
| QCWarning | `(code, item_id/case_id)` | `index/qc_warnings.jsonl` | IMP-08 |
| CurationEvent | `event_id` (ULID) | `curation/events.jsonl` | Append-only (CUR-*) |
| RadiomicsProfile | `profile_hash` | `radiomics/profiles/` | Content hash of normalized settings (RAD-03) |
| RadiomicsRun | `run_id` (ULID) | `radiomics/runs/{run_id}/run.json` | RAD-06 |
| FeatureValue | `(run_id, item_id, label, feature)` | `features.parquet` | Long format |
| Variable | `name` | `variables/catalog.json` + `index/variables.parquet` | VAR-* (study-agnostic, replaces a fixed `group`) |
| Analysis | `analysis_id` (ULID) | `analyses/{analysis_id}/` | ANA-* |
| Job | `job_id` (ULID) | in memory + `run.json` / index status | BE-06 |

## `item_id`

Deterministic, URL-safe: `{case_id}.{scan_idx}.{scope}.{side}`, with `side` ∈ `L|R|-`.
Examples: `case_00001.01.complete.-`, `case_00001.01.voi.L`.

## Item (index record)

```jsonc
{
  "item_id": "case_00001.01.voi.L",
  "case_id": "case_00001", "scan_idx": "01", "scope": "voi", "side": "L",
  "patient_id": "…", "modality": "CT",
  "phase": { "canonical": "NP", "raw": "VEN", "source": "phase.json" },
  "image": { "ref": "DATA:voi/images/A/NP/01_case_00001_L.nii.gz", "format": "nifti", "fp": "…", "sha256": null },
  "masks": {                       // seg_id → VolumeRef (ADR-0015); was `mask` in format_version 1
    "imported":       { "ref": "DATA:voi/mask/A/NP/01_case_00001_L.nii.gz", "format": "nifti", "fp": "…" },
    "nnunet-d820-3d": { "ref": "DERIVED:01J…/segment.nnunet/runs/01J…/case_00001_01_L.nii.gz", "format": "nifti", "fp": "…" }
  },
  "geometry": { "shape": [128,128,96], "spacing": [0.8,0.8,1.0], "dtype": "int16", "orientation": "RAS" },
  "labels_present": [1, 2],
  "status": "active",              // active | excluded_upstream | missing
  "warning_codes": ["missing_seg"],
  "import_id": "01J…",
  "extra": { }                     // unknown input fields, preserved
}
```

`modality` comes from the input `modality` field (VOIs inherit the scan's value) and is null when absent (unknown: the viewer assumes CT, VW-05). `sha256` is null until the full-hash job ran (IMP-09).
`masks` is empty when no segmentation exists (IMP-11). For one phase the API also returns `mask` = `masks[default_seg]` (deprecated, ADR-0015). `case_id` is a slug (SRC-08).

## Case summary (derived)

`{case_id, patient_id, phases[], n_scans, n_items, has_seg, has_voi_L, has_voi_R, n_warnings, curation_status, last_reviewed_at}`.
The `curation_status` rollup is defined in CUR-08. Extra columns (e.g. study variables) are chosen by the user (VAR-10).

## Conventions

- Timestamps are UTC ISO-8601 with `Z`. IDs are ULIDs except `item_id`, `case_id` and `profile_hash`.
- All paths in persisted records are alias refs (PRJ-04); absolute paths only appear in API responses under `advanced`.
- Enums are lower_snake_case, except phase codes (uppercase).
