# Radiomics

Scope: extraction engine, configurable settings, profiles, runs, outputs, IBSI alignment.
Read when: building the radiomics engine, settings form, run jobs, or feature exports.
Depends: DATA_MODEL.md, ADR-0006. Dashboard: frontend/DASHBOARD.md.

## Principles

- Extraction starts **only** from the Run button. Nothing is computed automatically.
- **Every** engine option is configurable in the UI (checkboxes, numbers, text/lists), and the form opens pre-filled with engine defaults.
- IBSI is the reference standard. It is enforced in the engine metadata and in tests, but **IBSI names and codes are never shown in the GUI**. They appear only in exports and metadata.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| RAD-01 | The settings form is generated from `GET /radiomics/schema` (API-30), which lists every option with type, default, constraints and group. No options are hard-coded in the frontend. | M |
| RAD-02 | Filters (image types) and feature classes are checkboxes, and each class expands to per-feature checkboxes. Parameters use number, text, list or select inputs. | M |
| RAD-03 | Profiles: save, load, rename, duplicate. `profile_hash` = SHA-256 of canonical JSON (sorted keys, normalized numbers) of settings + engine name + engine major version. | M |
| RAD-04 | Validation (§Rules) runs live in the UI and authoritatively on the server; the Run button is disabled while errors exist. | M |
| RAD-05 | Selection: items (all active / current Explorer filter on any variable (VAR-10) / explicit list), scope (`complete`, `voi`), labels (multi-select from label map, one extraction per label), segmentation set `seg_id` (default `default_seg`; ADR-0015). | M |
| RAD-06 | Run is a background job (BE-06): per-item progress, ETA, cancel. | M |
| RAD-07 | Per-item failures are logged to `errors.jsonl` and do not stop the run; the final status is `completed_with_errors`. | M |
| RAD-08 | Interrupted runs can resume, skipping items that already have a part file. | S |
| RAD-09 | Reproducibility record in `run.json` (§Run record). | M |
| RAD-10 | Outputs: `features.parquet` (long) + `diagnostics.parquet`; CSV export in long or wide shape. | M |
| RAD-11 | Pre-run estimate: `n_items × n_labels` and time per item measured on a 3-item sample. | S |
| RAD-12 | Engine adapter interface allows replacing the engine without UI changes (ADR-0006). | S |
| RAD-13 | Radiomics runs as the builtin task `radiomics.pyradiomics` (TSK-*, ADR-0016). API-30..37 stay as aliases of the task endpoints during P7b; run records stay in `radiomics/runs/`. | M |
| RAD-13 | Voxel-based feature maps. | C (v3.1) |

## Engine adapter

```python
class RadiomicsEngine(Protocol):
    name: str; version: str
    def schema(self) -> SettingsSchema: ...           # options, defaults, constraints, ibsi metadata
    def validate(self, settings: dict) -> list[Issue]: ...
    def extract(self, image_path: str, mask_path: str, label: int,
                settings: dict) -> ExtractionResult: ...   # features + diagnostics
    def dependency_versions(self) -> dict[str, str]: ...
```

Default engine: **PyRadiomics** (+ SimpleITK, PyWavelets). The inputs are the original files, read directly by the engine; there is no reorientation copy.

## Settings groups (defaults = engine defaults, shown on open)

| Group | Options (PyRadiomics names) | Defaults |
|---|---|---|
| Filters / image types | `Original`, `LoG`(`sigma` list mm), `Wavelet`(`wavelet`, `start_level`, `level`), `Square`, `SquareRoot`, `Logarithm`, `Exponential`, `Gradient`(`gradientUseSpacing`), `LBP2D`(`lbp2DRadius`, `lbp2DSamples`, `lbp2DMethod`), `LBP3D`(`lbp3DLevels`, `lbp3DIcosphereRadius`, `lbp3DIcosphereSubdivision`) | Only `Original` on; `wavelet=coif1`, `level=1` |
| Feature classes | `firstorder`, `shape`, `shape2D`, `glcm`, `glrlm`, `glszm`, `gldm`, `ngtdm`, each with per-feature checkboxes | All classes except `shape2D`; all non-deprecated features |
| Discretization | `binWidth` **xor** `binCount` | `binWidth=25` |
| Resampling | `resampledPixelSpacing` [x,y,z] mm, `interpolator`, `padDistance`, `preCrop` | none, `sitkBSpline`, `5`, `false` |
| Intensity | `normalize`, `normalizeScale`, `removeOutliers`, `voxelArrayShift` | `false`, `1`, none, `0` |
| Re-segmentation | `resegmentRange` [min,max], `resegmentMode`, `resegmentShape` | none, `absolute`, `false` |
| Mask handling | `minimumROIDimensions`, `minimumROISize`, `geometryTolerance`, `correctMask` | `2`, none, none, `false` |
| 2D | `force2D`, `force2Ddimension` | `false`, `0` |
| Texture | `distances` list, `symmetricalGLCM`, `weightingNorm`, `gldm_a` | `[1]`, `true`, none, `0` |
| Output | `additionalInfo` | `true` (feeds diagnostics) |

The exact list and defaults come from `schema()` at runtime; this table is the design intent and must be checked against the pinned engine version.

## Validation rules

| Rule | Message (UI) |
|---|---|
| `binWidth` and `binCount` are mutually exclusive, and one is required | "Choose bin width or bin count" |
| `LoG` enabled ⇒ `sigma` has ≥1 value > 0 | "LoG needs at least one sigma" |
| `shape2D` or `LBP2D` ⇒ `force2D=true` | "Enable 2D mode for this option" |
| `resampledPixelSpacing` values > 0, or 0 to keep that axis | "Spacing must be positive" |
| `resegmentRange` min < max; `resegmentMode=sigma` ⇒ single positive value | per field |
| ≥1 feature selected, ≥1 filter enabled, ≥1 label, ≥1 item | "Nothing to extract" |
| `normalize=true` with `resegmentMode=absolute` in HU | Warning only: "HU range will be applied after normalization" |

## IBSI alignment (not shown in GUI)

- Each feature in the schema has `ibsi: {code, status}`, where status ∈ `compliant | deviates | not_defined`, from a pinned map at `backend/app/radiomics/ibsi_map.json`.
- Exports include `ibsi_code` and `ibsi_status` columns; `run.json` includes the map version.
- Compliance tests: IBSI digital phantom and the IBSI CT phantom configurations; tolerances are in ops/TESTING.md (TST-06).

## Run lifecycle

`queued → running → completed | completed_with_errors | failed | cancelled | interrupted`
(`interrupted` is set on server restart; resumable per RAD-08).

Worker output: `parts/{item_id}__{label}.parquet`, compacted into `features.parquet` when the run finishes.

## Run record (`run.json`)

```jsonc
{ "run_id": "01J…", "name": "NP tumor baseline", "status": "completed",
  "created_at": "…", "started_at": "…", "finished_at": "…", "reviewer": "Dr. AP",
  "engine": { "name": "pyradiomics", "version": "x.y.z",
              "deps": { "SimpleITK": "…", "numpy": "…", "PyWavelets": "…" } },
  "ibsi_map_version": "1",
  "profile_hash": "sha256:…", "settings": { /* full normalized snapshot */ },
  "selection": { "scope": "complete", "seg_id": "imported", "labels": [2], "filter": "phase=NP", "item_ids": ["…"] },
  "inputs": [ { "item_id": "…", "image_fp": "…", "seg_id": "imported", "mask_fp": "…" } ],
  "counts": { "items": 320, "ok": 318, "failed": 2, "features": 107 } }
```

## Output schema

`features.parquet`: `run_id, item_id, case_id, scan_idx, scope, side, phase, label, image_type, feature_class, feature, value(float64), ibsi_code, ibsi_status`.
Study variables are **not** copied into features; they are joined at analysis time from `index/variables.parquet` (ANA-03).
`diagnostics.parquet`: `run_id, item_id, label, voxel_count, bbox, spacing, image_hash, mask_hash, …` (engine diagnostics, flattened).

## Spike result

- PyRadiomics installed from pinned upstream commit `8ed57938` (no Python 3.12 wheels on PyPI); 20/20 IBSI phantom checks pass. See ADR-0006.

## Decisions

- No built-in presets beyond engine defaults; users save their own profiles.
- Engine defaults assume CT (HU; `binWidth=25`). When the selection contains non-CT modality, the form warns and the analysis raises REC-MODALITY.

## Implementation notes (P5-BE)

- Profiles stored as `profiles/{hex}.json`; saving identical settings returns the existing profile (200); DELETE returns the remaining list.
- Labels absent from a mask → `kind: "skipped"` rows in `errors.jsonl` and `counts.skipped` (not an error). `run.json` also has `job_id`, `error`, `counts.skipped`; `units.jsonl` is the per-run plan used by resume.
- One radiomics run per project at a time (409 `job-conflict`); an engine major-version change → 409 `format-version-unsupported`.
- Engine schema differs from the design table: `sigma` has no default; extra `label_channel` (mask handling); 107 default features. LBP3D is unavailable unless `trimesh` is added to `[radiomics]`.
- TST-06: IBSI digital phantom, 85 features compliant + 4 deviating within 0.6 %. **The IBSI codes and extended reference values were written by the implementing agent from memory and must be spot-checked against the IBSI manual**; the IBSI CT phantom (TST-06 part 2) has not been run.
- Without PyRadiomics installed, engine endpoints return 503 `server-busy` and its tests are skipped.

## Implementation notes (P5-FE)

- The form opens on `schema.defaults`; "Engine defaults" restores them. Duplicate = load a profile's settings and pre-fill "<name> copy". Saving unchanged settings keeps the existing profile (same hash).
- Default label = first visible label. Client rules only pre-flag; the server validation (API-31) is authoritative once it answers for the current form.
- Selection by variable sends level lists only; continuous variables must be binned into a derived variable first (VAR-06) until API-33/34 accept ranges (open decision, ROADMAP P7).
- Draft settings live in memory; a reload reopens on the engine defaults (profiles persist).
- `seg_id` (RAD-05, P7b Wave 4): masks come from that set; the selected labels are project label values, mapped to the set's own values through its `label_mapping` (ADR-0015); labels the set does not map are skipped (`label not in segmentation set`). `labels_present` checks apply to the `imported` set only. `run.json` records `selection.seg_id` and `inputs[].seg_id` + `mask_fp` of that set (NFR-15); older runs read as `imported`.
- "Use the current Explorer filter" (RAD-05) maps phase and variable levels to `filter`, or an Explorer item list to `item_ids` (API-33/34 take one or the other, so the list wins and sets the scope when all items share one). Not sent, and listed in the form: text search, curation status, warnings, has-VOI, show-excluded, continuous ranges. The Explorer's phase filter matches cases; the run selection's matches items.
