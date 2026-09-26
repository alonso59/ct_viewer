# Study Variables

Scope: study-agnostic variable catalog — profiling, types, levels, visibility, derived variables, external tables.
Read when: touching import profiling, filters, group-by, radiomics selection, or analysis inputs.
Depends: INPUT_METADATA.md, DATA_MODEL.md, ADR-0011, ADR-0020.

## Principle

The app knows **no study-specific field names**. Beyond the core imaging contract (INPUT_METADATA §Core),
every metadata field is a **variable**: profiled on import, typed, and confirmed by the user.
`group`, `hb`, `lb`, `sn`, `kvp`, `manufacturer` are all just variables.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| VAR-01 | On import, profile every non-core field: inferred type, level, missing %, distinct count, example values, confidence. | M |
| VAR-02 | Level: `case` if the value is constant within every case, else `scan`. Case-level variables join to all items of the case. | M |
| VAR-03 | Type inference (§Rules). Low-confidence inferences get a "Review" badge; the user confirms or overrides the type. | M |
| VAR-04 | Source group: fields in the known converter schema are **Acquisition** (hidden by default); unknown fields are **Study** (visible by default). This is how study labels like `hb/lb/sn` surface without knowing their names. | M |
| VAR-05 | Tags the user can set: `confounder` (scanner, kernel, kVp…), `outcome`, `sensitive`. Default `confounder` on `manufacturer`, `manufacturer_model`, `convolution_kernel`, `kvp`, `slice_thickness`, `spacing_z`, `contrast_agent`, `modality`. | S |
| VAR-06 | Derived variables, three operations only: **bin** (continuous → categorical by thresholds or quantiles), **recode** (merge/rename categories), **dominant** (name of the largest among N numeric variables). Adding one validates only the new definition; a stored one whose source is gone (re-import, deleted label table LBL-10) is kept, listed as broken with its reason (API-16 `broken[]`) and can be deleted. Deleting a label table or column names the derived variables it breaks. | M |
| VAR-07 | External table: import a CSV/TSV keyed by `case_id` (or `patient_id`) to add variables not in `metadata.jsonl`. Unmatched keys are reported. | S |
| VAR-08 | `raw_metadata` and DICOM sidecars (DCM-04) are not variables. An allowlist of useful tags is flattened: `PatientSex` → categorical, `PatientAge` → continuous years. All other raw tags are ignored. Converter extras in the row (DICOM_CONVERTER §Row fields) and analyzer `target_match` / `readiness` (ANZ) are ordinary fields and are profiled. | S |
| VAR-09 | Never exposed as variables: absolute paths, UIDs, `AccessionNumber`, blobs. `patient_id` and dates are `sensitive`. Dataset exports (API-59) leave out `sensitive` fields, UIDs and accession numbers unless chosen, and never export absolute paths or the `raw_metadata` tag blob (NFR-17). | M |
| VAR-10 | Variables drive: Explorer filters and columns (UI-08), radiomics selection (RAD-05), analysis grouping/targets (ANA-*). | M |
| VAR-12 | Active metadata layers are variables too (ADR-0020): analyzer fields (`phase` guess, `target_match`, `readiness`), the native effective `phase` (PHASE.md, ADR-0026) and labeling columns `lbl.{table}.{column}` at their table's level (LBL-06), with the layer's type. | M |
| VAR-11 | Catalog overrides and derived definitions live in the project (`variables/catalog.json`); source files are never changed (R1). | M |
| VAR-13 | `comparable` flag (ADR-0026): true for categorical, layer-sourced variables meant for side-by-side comparison (native `phase`, analyzer `phase`, `target_match`, `readiness`, other `lbl.*` columns); false for continuous/free-text variables. Drives the Labeling reference-column picker (LBL-09). | S |

## Type inference rules (non-empty values only; empty string = missing)

| Type | Rule | Example (reference dataset) |
|---|---|---|
| `continuous` | ≥ 95 % parse as numbers and ≥ 10 distinct | `hb`, `lb`, `kvp`, `spacing_z` |
| `categorical` | ≤ 20 distinct (or ≤ 5 % of rows) | `phase`, `manufacturer`, `convolution_kernel` |
| `numeric-discrete` → Review | numeric with < 10 distinct: user picks continuous or categorical | `sn` (0, 5, 7, 8, 10, 30) |
| `date` | ISO date/datetime or `YYYYMMDD` | `scan_date` |
| `identifier` | distinct ≈ rows | `acquisition_time` (UIDs are excluded outright, VAR-09) |
| `text` | anything else | `phase_guess_evidence` |
| `constant` | 1 distinct value → hidden | `status` |

## Derived variable examples

```jsonc
{ "name": "hb_dominant", "op": "bin", "source": "hb", "thresholds": [50], "labels": ["LB-dominant", "HB-dominant"] }
{ "name": "vendor", "op": "recode", "source": "manufacturer",
  "map": { "Philips Medical Systems": "Philips", "SIEMENS": "Siemens", "Siemens Healthineers": "Siemens" } }
{ "name": "dominant_component", "op": "dominant", "sources": ["hb", "lb", "sn"] }
```

## Storage

- `variables/catalog.json`: `[{name, source (metadata|derived|external|raw|layer), type, level, group, tags[], visible, confidence, overridden, comparable}]` + derived definitions.
- `index/variables.parquet` (derived, rebuildable): one row per item, all variables, case-level values joined.

## Reference dataset (2026-09-23 profile, for calibration only)

172 scans / 77 cases, ~160 fields. No `group` field. `hb`, `lb`, `sn` are case-level numeric (0–100), present for 39/77 cases,
and `hb + lb ≈ 100` in most cases (compositional). 2 of 172 scans are MRI. 7 manufacturer strings for 4 vendors.

## Implementation notes (P1b)

- Only `metadata.jsonl` rows are profiled; VOI-catalog extras are not. Core phase fields (`phase`, `curated_phase`, `canonical_phase`) are core, not variables.
- The Acquisition group is the known converter field list in `backend/app/variables/schema.py`.
- `bin`: a value `v < t` goes to the lower bin; `quantiles` on the wire are cut probabilities in (0, 1) (the UI shows a group count and converts).
- `dominant`: missing if any source is missing; `tie` on equal maxima.
- Unconfirmed `numeric-discrete` variables are rejected for tests (422) until the user confirms a type.
- VAR-12 (ADR-0026): `phase` stays a core column; the effective phase is the layer variable `phase.effective` (native selection, else the resolved value) and the active `analyzer.phase` run's guess is `phase.analyzer`, both categorical at scan level. Analyzer `target_match` / `readiness` / `output_role` arrive as input fields (joined extras) and keep `source: metadata`.
- VAR-13: `comparable` = categorical and (`source: layer`, or an active annotation field); recomputed at every build, so a type override changes it.
- API-16/17 return the full `Catalog` (`variables, excluded, derived, external, overrides`); profile fields are `distinct` and `top[{value, n}]`. API-18 returns `{table, n_rows, n_matched, n_unmatched, unmatched_keys, duplicate_keys, conflicts}`. Deleting a derived variable in use → 422 `validation`.
