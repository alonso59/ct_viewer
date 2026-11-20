# Analysis tables and VOI lesion profile: implementation plan (P7m)

Status: T0 accepted 2026-11-20 (ADR-0060, ADR-0061); T1 done 2026-11-20 (owner confirmed); T2 done 2026-11-20 (owner confirmed); T3 done 2026-11-20 (owner confirmed); T4 done 2026-11-20 (owner confirmed); T5.3 done; T5.2 3.7.0 deployed 2026-11-20 (`native-20261120-7fa7d6f`); T5.1 owner walkthrough pending.
Scope: ordered steps T1–T5 for analysis tables (ADR-0060) and VOI lesion measurement with the training contract (ADR-0061). Facts move to their owner docs at each step's exit; this file only sequences work.
Read when: starting or resuming P7m.
Depends: ADR-0060, ADR-0061, domain/VOI.md, domain/TASKS.md (§Outputs, §Protocol), domain/ANALYSIS.md, frontend/DASHBOARD.md, plugins/AGENTS.md, skill `rw-api-change`.

## How to work

- One step at a time; run its gate, report, and **stop for owner confirmation** before the next.
- Hard rules R1–R9 apply. Most relevant: R1 (task outputs only in derived roots; tables and profile variants in the project folder), R8 (code cites no IDs).
- Plugins never import `app`; the backend imports `plugins/voi/engine.py` and, from T3, `plugins/voi/profile.py` lazily (plugins/AGENTS.md §Boundaries).
- A refactor step (T1) changes no visible behavior: existing dashboard and analysis tests pass unchanged before new ones are added.
- Run tests quietly (`run_quiet`), narrowest first; `make check` at each step's exit.

## Current state (2026-11-20, v3.6.1)

| Area | Fact that drives the change |
|---|---|
| `plugins/voi/task.py` | One catalog row per VOI (organ side): `volume_ml`, `label_ml`, sizes; no lesions, no HU, no dataset aggregates. Catalog opened in append mode, so aggregates must be computed from the whole file at run end. |
| `plugins/voi/engine.py` `extract()` | Holds the written crop (image float32, mask uint8, affine) in memory before saving it. |
| `engine.REGIONS[*]` | `protect` already names each region's lesion labels; `organ` its organ labels. |
| `backend/app/analytics/data.py` | `run_dir` reads only `radiomics/runs/{rid}/features.parquet`; `_SQL` builds PyRadiomics keys; observation = `(item_id, label)`; `VOLUME_KEY` constant used by views and REC-VOLUME. |
| `backend/app/api/v1/dashboard.py` | Every view under `/projects/{pid}/radiomics/runs/{rid}/views/…`; `AnalysisSpec.run_id`. |
| `backend/app/tasks/` | `OutputType` has `features` but only radiomics registers it; `registration.py` handles `annotations` and `metadata` manifests. |
| Research `fingerprint.py` | Budgets and priors keyed `tiny…huge`, bins named `bin_N`: every bin gets 3 patches and 0.5/0.3/0.2. Spacing from config. |
| Research sampler | Groups lesions by `mask_path`; reads `centroid_vox`, `bbox_size_vox`, `size_bin`, per-bin budgets, priors and probabilities. Loaders expect `.npy` under `mask/`, `images/`. |

## Step T1: analysis tables in the backend (no visible change)

Files: new `backend/app/tables/` (`models.py`, `providers.py`, `service.py`); `backend/app/analytics/` (`data.py`, `models.py`, `service.py`, `views.py`, `recommend.py`); new `backend/app/api/v1/tables.py`; `backend/app/api/v1/dashboard.py`; `backend/app/tasks/models.py`, `registration.py`; `plugins/protocol.py`.

| Task | Work | Done when |
|---|---|---|
| T1.1 | `TableManifest`, `TableColumn`, canonical arrow schema; `RadiomicsProvider` (runs and combined runs, `table_id = run_id`) | Every existing run lists as a table with the same columns and counts |
| T1.2 | `data.py` loads tables through providers; observation `(item_id, label, instance)`; `group` replaces `feature_class` internally; LRU cache kept | Existing analytics, dashboard and analysis tests pass unchanged |
| T1.3 | `roles.volume` replaces `VOLUME_KEY` in views and recommendations; size views and REC-VOLUME skipped without it | Tests for a table without volume |
| T1.4 | `build_unit` orders by phase priority, scan, side, then instance | `first`/`mean`/`none` tests on a synthetic instance table; REC-NONINDEP fires on `none` |
| T1.5 | Routes `/projects/{pid}/tables`, `/tables/{tid}`, `/tables/{tid}/views/{view}`, `/tables/{tid}/export`; old routes alias them; `AnalysisSpec.table_id` with `run_id` alias; `feature_class` alias for `groups` | Old and new routes give equal bodies; a stored `spec.json` with `run_id` loads; `make gen-api record-mock` |
| T1.6 | Task output type `tables`: `Job.table(name, path)` in `protocol.py`; `registration.py` validates schema and sha256, copies to `tasks/runs/{rid}/tables/{name}/`, records the output; `TaskTableProvider` | A fixture task's table lists and opens in every view |

Gate: `make check`. Docs at exit: TASKS.md TSK-17 and §Outputs (`tables`; the `features` line corrected), ANALYSIS.md ANA-01/ANA-03, API.md rows, DASHBOARD.md DB-01.

## Step T2: lesion measurement in `voi.extract`

Files: new `plugins/voi/lesions.py`; `plugins/voi/engine.py`, `task.py`, `task.json`; tests `backend/tests/test_voi_lesions.py`, `test_voi_engine.py`, `test_voi_api.py`.

| Task | Work | Done when |
|---|---|---|
| T2.1 | `lesions.measure(mask, image, affine, lesion_values, organ_values, min_voxels)`: 26-connected components, volume, centroid (voxel, crop mm, world), bbox (voxel, mm), max extent, organ contact/overlap, HU mean/std/p5/p50/p95; largest first | Synthetic cases: two lesions, one touching the organ, one under `min_voxels`, a diagonal-only link, anisotropic zooms |
| T2.2 | `engine.extract()` also returns the written arrays; files byte-identical to 3.6.1 | Existing VOI engine tests pass; new equality test |
| T2.3 | `_extract` measures the written crop; the catalog row gains `lesions` (the measured list, largest first, each with its project `label`), `lesion_labels`, `lesions_below_min` and `hu_histogram`: the foreground 1 HU histogram as a JSON sidecar `{item}_{side}_hu.json` (deterministic bytes; NumPy's zip embeds a timestamp) | Two runs give the same measures and histogram bytes (the resumed-run check is T3.3) |
| T2.4 | Settings, group Lesions: `measure_lesions` (true), `lesion_labels` (empty = region `protect`), `organ_labels` (empty = region `organ`), `min_lesion_voxels` (10, the research CLI value); version 1.1.0 | Settings validate (the task form shows them in T4.1); a region without lesion labels still crops, writes no lesion files |
| T2.5 | Parity script (one-off, not shipped): measure Dataset421 `images_nii`+`masks_nii` and compare with `Dataset421/voi/lesion_catalog.jsonl` | Volume and extent equal on all single-lesion VOIs; differences on the others explained |

Gate: `make check` plus the parity report. Docs at exit: VOI.md VOI-14 and VOI-08 (catalog fields).

## Step T3: training contract and profile

Files: new `plugins/voi/profile.py`; `plugins/voi/task.py`, `task.json`; `backend/app/voi/` (`service.py`, `catalog.py`, `models.py`); `backend/app/api/v1/voi.py`; tests `test_voi_profile.py`, `test_voi_api.py`.

| Task | Work | Done when |
|---|---|---|
| T3.1 | `build_profile(lesions, settings)` → `sampling_profile.json` schema 2 (schema-1 keys kept; bins `b0…bN` with bounds and labels; budgets and priors per produced bin; patch recommendations in mm and voxels; `settings`, `settings_hash`) | Budgets and priors differ across bins by default (regression of the research bug); deterministic output |
| T3.2 | `build_fingerprint(catalog, histograms, settings)` → `dataset_fingerprint.json` schema 3 (foreground and windowed intensity, `window_rescale` normalization, VOI shape statistics, spacing) | Percentiles equal to `numpy.percentile` over the pooled voxels of a fixture |
| T3.3 | Run end: from the whole catalog write `lesion_catalog.jsonl` (`mask_path` = catalog `mask`, `centroid_vox`, `bbox_size_vox`, `size_bin`, …), the profile, the fingerprint (atomic) and the `lesions` table (T1.6) | Files present after a run and after a resumed run, identical |
| T3.4 | Settings `profile` group: `bin_percentiles` [20, 50, 80, 95], `balancing_alpha` 0.5; advanced: `budget_by_bin`, `role_priors_by_bin`, `hu_window` [−100, 300], `patch_size_candidates` | Schema validation tests |
| T3.5 | `POST /projects/{pid}/voi/runs/{rid}/profile` (recompute from `lesion_catalog.jsonl` only); `PUT`/`GET …/profiles/{name}` (variants in `tasks/runs/{rid}/profiles/`); lesion counts in the run summary | API tests; no volume is opened (asserted) |

Gate: `make check`. Docs at exit: VOI.md VOI-15; API.md API-85; plugins/ and backend/ AGENTS.md boundary lines.

## Step T4: frontend

Files: `frontend/src/plugins/voi/` (`Settings.tsx`, `Results.tsx`, `model.ts`), `frontend/src/plugins/dashboard/` (`DashboardsView.tsx`, `DashboardEditor.tsx`, `store.ts`, views), `plugins/dashboard/plugin.json`.

| Task | Work | Done when |
|---|---|---|
| T4.1 | VOI Settings: Lesions and Training profile sections | Vitest on the form model |
| T4.2 | VOI Results: **Lesions & profile** tab (volume histogram, log scale, bin cuts; per-bin table; live edit, Save variant, Download, Open in dashboard); scan rows show lesion count and largest volume | Vitest; manual check on a fixture run |
| T4.3 | Dashboards list tables grouped by kind; `run` editor becomes `table` (old id still opens); views use `group`; size views hidden without `roles.volume`; overview notes cases with more than one instance | Existing dashboard tests pass; new store tests |
| T4.4 | `dashboard` plugin: no `radiomics` requirement; capability `analysis_table` | PLUGINS.md updated; plugin tests |

Gate: `make check`. Docs at exit: DASHBOARD.md DB-01, VOI.md VOI-16, PLUGINS.md (capability `analysis_table`), UI_SHELL.md (editor names).

## Step T5: release and research loader

| Task | Work | Done when |
|---|---|---|
| T5.1 | End-to-end on the dev server, Kidney_ukb project: extract, Results, a variant, the lesion table in the dashboard, an analysis; existing radiomics runs and saved analyses unchanged | Owner walkthrough |
| T5.2 | Release 3.7.0 (version files, `make gen-api record-mock`, native prepare); deploy only after owner confirmation, with supervised runs paused | Production on 3.7.0 |
| T5.3 | Research repository, only what the owner approved on 2026-11-20: `src/common/data/subject_factory.py` reads ct_viewer NIfTI crops (real affine; mask and `catalog_key` from `voi_catalog.jsonl`, the key `lesion_catalog.jsonl` uses) and `src/preprocessing/voi/splits.py` builds `splits.json` from a ct_viewer catalog. The research `fingerprint.py` bin bug is left as is (ct_viewer's profile is correct) | Verified 2026-11-20 on a fixture run: splits, subjects at 1 mm, profile schema 2, lesion-centric patches with tumor in every subject |

## Requirements added

The drafts of T0 now live in their owner docs: TSK-17 (T1), VOI-14 (T2), VOI-15 (T3), VOI-16 (T4).
