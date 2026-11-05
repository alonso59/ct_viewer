# Cohort dashboard: implementation plan (P7k K1)

Status: C1–C5 implemented 2026-11-05 (the unit and component tests and the e2e journey pass); K2 and K3 followed the same day. The agent requirements of ADR-0048 are in COHORT.md §Agent requirements.
Scope: ordered, small tasks for building K1 of the Cohort dashboard (steps C1–C5), written for a smaller coding model. Facts live in the owner docs; this file only sequences work.
Read when: starting or resuming P7k implementation.
Depends: frontend/COHORT.md, ADR-0045, ADR-0046, domain/VARIABLES.md (VAR-14, §Categories), backend/AGENTS.md, frontend/AGENTS.md, skill `rw-api-change`.

## How to work (read once)

- One task at a time, in order. Finish its "Done when" before the next. After the last task of a step (C1…C5): run its gate, report, and **stop for owner confirmation**.
- Read `backend/AGENTS.md` before backend work and `frontend/AGENTS.md` before frontend work. Never open generated files (`frontend/src/api/schema.d.ts`, `openapi.json`, `mock/*.json`, `backend/tests/openapi.snapshot.json`); regenerate with `make gen-api` / `make record-mock`.
- Find code with `rg -n <symbol> <dir>`. Do not scan the repository. Do not read `docs/archive/**` or `legacy/**`.
- Requirement text is in `docs/frontend/COHORT.md` (COH-*) and `docs/domain/VARIABLES.md` (VAR-14). Do not restate or edit requirement wording; if a requirement seems wrong, stop and ask.
- Hard rules (AGENTS.md R1–R9). Most relevant: R1 never write source data; R5 no network at runtime; R8 application code (comments, docstrings, messages) cites no IDs, ADRs or doc paths.
- All user-facing text, names and docs are English. Code standards: simplest working solution, no speculative abstractions, no helper for a one-liner, comments only for non-obvious why.
- Run tests, lint and builds quietly (`run_quiet <command>` if available). Narrowest test first; `make check` only at the end of a step.
- Do not commit, push or create branches. Leave changes in the working tree. The working tree already holds uncommitted doc changes (docs/); do not revert them.
- If a task needs a decision not in the docs, or touches a file outside the task's list, stop and ask.

## Step C1: origin and category in the catalog (VAR-14)

Files: `backend/app/variables/models.py`, `schema.py`, `build.py`, `service.py`; tests `backend/tests/test_variables.py`, `test_api_variables.py`; doc row in `docs/backend/API.md` (API-16).

| Task | Work | Done when |
|---|---|---|
| C1.1 | `models.py`: add `Origin = Literal["metadata","automatic","review","clinical","derived"]` and `Category = Literal["patient","study","series","equipment","technique","contrast","geometry","intensity","dates","phase_readiness","provenance","dataset"]`. Add to `Variable`: `origin: Origin = "metadata"` and `category: Category \| None = None` (None for non-Metadata origins). Add `category: Category \| None = None` to `VariableOverride`. Defaults keep an old `catalog.json` loadable | `Catalog.model_validate` of an old-format JSON (no new fields) still passes (add this test) |
| C1.2 | `schema.py`: add `CATEGORY_BY_FIELD: Final[dict[str, Category]]` with **one explicit entry per name in `CONVERTER_FIELDS`**, assigned from the table in `docs/domain/VARIABLES.md` §Categories. Names starting with `webui_` go to `provenance`. Do not guess by substring rules. Add the raw allowlist names (`patient_sex`, `patient_age`) to `patient`. List fields you were unsure about in your report | New test: every `CONVERTER_FIELDS` name is a key of the map, and every map key is in `CONVERTER_FIELDS` or the raw allowlist |
| C1.3 | `build.py` (three construction sites: `_make_variable`, the derived `Variable(...)`, the layer one near `_make_variable(ld.name, "layer", …)`): set `origin` and `category`. Rules: source `metadata`/`raw` → origin `metadata`, category from the map (unknown name → `dataset`); `derived` → `derived`; `external` → `clinical`; `layer`: `lbl.*` → `clinical`, `phase.effective` → `review`, any other layer or annotation field → `automatic` | Unit tests for each rule on small fixtures in `test_variables.py` |
| C1.4 | `apply_override`: honor `ov.category` only for origin `metadata` (ignore otherwise); mark `overridden`. `PATCH` body already uses `VariableOverride`; make sure the category round-trips through `catalog.json` overrides | Test: PATCH category → catalog shows it; PATCH on a derived variable keeps `category` None |
| C1.5 | API: follow skill `rw-api-change` (update the API-16 row in `docs/backend/API.md`, `make gen-api`, update `frontend/src/api` hooks/types only if a hook builds `Variable` literals) | `make api-types` passes |

Gate: `cd backend && .venv/bin/python -m pytest -n 0 tests/test_variables.py tests/test_api_variables.py`, then `make lint typecheck api-types`. Report, then stop.

## Step C2: read endpoints

Files: new `backend/app/cohort/` (service, models), new router `backend/app/api/v1/cohort.py` registered like the other routers (copy the wiring of `variables`), test `backend/tests/test_api_cohort.py`. Layering: api → services → core; the module must not import `labeling` or `curation` writers.

| Task | Work | Done when |
|---|---|---|
| C2.1 | Pydantic models: `RowsRequest {columns: list[str], filters: dict[str, list[str]], q: str\|None, phase: str\|None, sort: {column, desc}\|None, offset: int=0, limit: int=100 (≤500)}`; `RowsResponse {n_cases, n_scans, rows[]}` with `rows[i] = {case_id, values: dict, differs: list[str], scans: [{scan_idx, item_id, phase, modality, values}]}`; `SummaryRequest {column, filters}`; `SummaryResponse` (categorical: counts top 20 + other + missing; numeric/date: bins + missing) | Models import; JSON schema builds |
| C2.2 | Service `rows`: read `index/variables.parquet` through `app.variables.table.read_table` with **column projection** (base columns + requested columns only). Scan unit = the scan's `complete` item (scope `complete`). Case-level variables come from the case; scan-level values in a case row: the common value if all scans agree, else `None` and the variable name appended to `differs`. Filters via `table.matching_ids` (same semantics as the cases endpoint). Sort and paginate by case in Python/pyarrow; no whole-table JSON | Unit tests on small in-memory tables: paging, sort, differs, case-level join, unknown column → 422 |
| C2.3 | Service `summary`: counts/bins over the filtered rows at the variable's level (case-level variables count once per case). Numeric: 20 equal-width bins by default | Unit tests: categorical top-20+other, numeric bins, missing count |
| C2.4 | Router: `POST /projects/{pid}/cohort/rows` and `…/cohort/summary`; read-only; allowed for view-only tokens like the other read endpoints; errors use the existing problem+json helpers (`ValidationProblem` for bad columns) | `test_api_cohort.py` on the synthetic fixture project: filters equal to the cases endpoint with the same `var.*`; view-only token works |
| C2.5 | `rw-api-change`: add API rows to `docs/backend/API.md` (next free IDs, section for Cohort), `make gen-api`, `make record-mock` if the mock needs the new calls | `make api-types lint typecheck` pass |

Gate: `pytest -n 0 tests/test_api_cohort.py tests/test_variables.py`, then `make lint typecheck api-types`. Stop.

## Step C3: Cohort view, tab, navigator, grid, filters

Files: new `frontend/src/features/cohort/` modelled on `features/variables/` (read its `index.ts` once to copy how views, editors and routes register, UI-02). Add the English strings where the existing features keep theirs (find with `rg -n "variables\." frontend/src/i18n`). Visual style: existing tokens only; no new colors.

| Task | Work | Done when |
|---|---|---|
| C3.1 | API hooks in `frontend/src/api` for the two endpoints (follow the existing hook pattern; keys in `keys.ts`) | `npx vitest run src/api` passes |
| C3.2 | Register the Cohort activity-bar view (codicon `table`), the editor type for `/p/{pid}/cohort`, and a command "Open Cohort". Mark nothing as `writes` yet | Opens an empty Cohort tab; test for the registration |
| C3.3 | Navigator (COH-02): origin groups in order (Metadata, Automatic results, Review, Clinical & labels, Derived), Metadata split into its categories, each with a visible-variable count from the catalog (`useVariables`), a field search, pin toggle. Choosing a group sets the visible columns | Component test: counts, search filter, pin persists |
| C3.4 | Grid (COH-03, COH-10): virtualized case → scans rows from `cohort/rows`, expand/collapse with `aria-expanded`, "differs" marker with a text label, sortable headers with `aria-sort`, server paging. Row keys use the shared `lib/rowKeys.ts` (`useRowKeys`) | Component test: expand, differs marker, keyboard keys |
| C3.5 | Filters (COH-05): chips for `var.*`, phase and text; Clear filters; persisted per project (follow UI-13 storage pattern used by Explorer); Send to Explorer reuses the existing Explorer filter setter | Test: chip add/remove, persistence |
| C3.6 | Cell menu (COH-04): Copy value, Filter by this value, Open scan in viewer. "Add to correction queue" reuses the existing curation action and is the only item flagged `writes` (hidden on view-only) | Test: view-only hides the queue action |
| C3.7 | Entry points (COH-01): Explorer case menu "Show in Cohort" focuses the case; Image view link | Test for the menu entry |

Gate: `cd frontend && npx vitest run src/features/cohort`, then `npm run lint && npm run typecheck`. Stop.

## Step C4: compare scans, column summary, DICOM tags

| Task | Work | Done when |
|---|---|---|
| C4.1 | Compare scans (COH-07): from a case row; variables as rows, the case's scans as columns, grouped as the navigator, "Differences only" toggle. Data comes from `cohort/rows` with all visible columns for that one case (`q` = case id) | Component test for the toggle and grouping |
| C4.2 | Column summary (COH-06): reuse `plugins/dashboard/Chart.tsx` and the `ChartOrTable` / "Show as table" pattern from `plugins/dashboard/views/common.tsx` (DB-11 rules: `role="img"`, text alternative, no animation under reduced motion). Click on a bar or bin adds a filter chip | Test: click adds the filter; table mode lists the same rows |
| C4.3 | DICOM tags panel (COH-08): reuse the on-demand tags query and the partial-sidecar badge from `features/viewer/ImageSection.tsx`; add a search box. Group by category only if a mapping exists; otherwise a flat searchable list | Test: tags load on demand only |

Gate as C3, plus `make deadcode`. Stop.

## Step C5: export, accessibility pass, view-only, e2e

| Task | Work | Done when |
|---|---|---|
| C5.1 | Grid CSV export (COH-09): visible columns, filtered rows, one row per scan; leave out `sensitive` variables unless chosen; never paths, UIDs or raw blobs | Test on a fixture grid |
| C5.2 | Chart export: add SVG and a light-background PNG next to the existing PNG in `plugins/dashboard/views/common.tsx` (used by both dashboards, DB-06). SVG needs the ECharts SVG renderer registered in `Chart.tsx`; keep bundle size within `make bundle-size` | Test: both formats offered; `make bundle-size` passes |
| C5.3 | View-only check: with a view-only token the Cohort tab opens, no `writes` action is visible | Component test |
| C5.4 | e2e journey (open Cohort → filter by a summary bar → compare scans → open in viewer) using the existing e2e harness (`docs/ops/TESTING.md` for WebGL limits) | `make e2e-one SPEC=cohort` passes, or the limitation is reported |
| C5.5 | Docs: in `docs/frontend/COHORT.md` add an Implementation notes section with only facts that are not obvious from code; tick the K1 items in `docs/product/ROADMAP.md` | `make reqs` passes |

Final gate: `make check` (bound workers on shared hosts: `PYTEST_WORKERS=2 VITEST_WORKERS=1`). Report each command with pass/fail; quote failures. Stop.

## Out of scope for this session

The analysis layer and retiring the Search view. K2 and K3 were built after K1 on the owner's go-ahead (COHORT.md §K2, §K3, ADR-0049).

## Report format after each step

1. Tasks done (IDs). 2. Files changed. 3. Commands run with pass/fail. 4. Anything uncertain or any field/category you had to guess. 5. The next step and what you need from the owner.
