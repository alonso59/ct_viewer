# ADR-0060 The dashboard and analyses read analysis tables, not radiomics runs
Status: Accepted · Date: 2026-11-20 (owner decision, same date)
Extends: ADR-0009 (Parquet + DuckDB), ADR-0012 (guided statistics), ADR-0016 (tasks). Amends DB-01, ANA-01.

**Context.** The dashboard and every analysis read one radiomics run: `radiomics/runs/{rid}/features.parquet`.
The analytics core (filters, variable and phase joins, unit of analysis, tests, recommendations) is already generic over an observation × column matrix.
The coupling sits in five places: the run folder lookup, the PyRadiomics key (`image_type_feature_class_feature`), the observation key `(item_id, label)`, the hard-coded volume feature `original_shape_MeshVolume`, and the routes and `AnalysisSpec.run_id`.
TASKS.md says "the dashboard reads any features run", but only the radiomics task registers `features`.
On 2026-11-20 the owner asked to analyze per-lesion measurements from the VOI extractor (ADR-0061), one row per lesion, and asked that the dashboard take data sets instead of depending on radiomics features.

**Decision.**
1. An **analysis table** is the dashboard's input: a manifest (`table.json`) plus a long Parquet with the canonical columns
   `item_id, case_id, scan_idx, scope, side, phase, label, instance, group, name, value`.
   The manifest names `table_id`, `kind`, `title`, the producer (task, run), the **grain** (`label`, or `instance` with an `instance_name` such as `lesion`), the columns (name, group, unit, description), **roles** (`volume`), counts and `created_at`.
2. Tables come from **providers** that list and load them in place, without copying:
   radiomics runs and combined runs (`table_id = run_id`, `group = feature_class`, `roles.volume = original_shape_MeshVolume`);
   and task tables, a new task output type `tables`: the task declares `{kind: "table", name, path, sha256, spec}` in `result.outputs_manifest`, registration validates the schema and hash and stores it in `tasks/runs/{rid}/tables/{name}/` (`table_id = {rid}-{name}`).
   Imported CSV/Parquet tables are a later provider on the same contract.
3. An observation is `(item_id, label, instance)`; `instance` is empty for label-grain tables.
   The unit of analysis keeps ANA-03: on an instance table, `first` takes the first instance (producers order instances, e.g. largest lesion first), `mean` averages instances, `none` keeps every instance and triggers REC-NONINDEP.
4. Views and recommendations that need size use the table's `volume` role; without it they are not offered.
5. Routes move to `/projects/{pid}/tables/{tid}/…` (views, export); the radiomics routes stay as aliases for one minor release. `AnalysisSpec.table_id` accepts `run_id`, and requests accept `feature_class` for `groups` (the column groups to keep), so saved analyses keep working.
6. The `dashboard` plugin no longer requires the `radiomics` plugin; its capability becomes `analysis_table`.

**Consequences.** Radiomics becomes one producer among others; per-lesion, per-region or per-patch measurements enter without changing views or tests.
The OpenAPI, the recorded mock and the dashboard store change once (`make gen-api record-mock`).
Feature-level IBSI columns stay in the radiomics features endpoint (RAD-10); tables carry values only.
Tables hold numbers only; categorical attributes (e.g. a lesion's size bin) stay in the producer's catalog until variables gain an instance level.

**Rejected alternatives.**
Writing lesion measurements as a fake radiomics run (mixes provenance, breaks RAD-09/RAD-10 and the run record).
A separate lesion dashboard (duplicates every view and test).
Several runs per view (rejected in ADR-0059; combined runs cover it).
Copying every table into one project-wide store (duplicates data and invalidates on every run).
