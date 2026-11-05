# HTTP API (v1)

Scope: endpoint list, conventions, errors, realtime events.
Read when: adding or consuming an endpoint. Payload fields come from domain docs; they are not repeated here.
Depends: domain/DATA_MODEL.md, backend/ARCHITECTURE.md.

## Conventions

- Base path `/api/v1`. JSON bodies; `snake_case`; UTC `Z` timestamps.
- `{pid}` = `project_id`, `{iid}` = `item_id`, `{cid}` = `case_id`, `{rid}` = `run_id`, `{sid}` = Open-mode session, `{tid}` = task id, `{seg}` = `seg_id`.
- Lists: `?cursor=&limit=` (default 200, max 2000) → `{items, next_cursor, total}`.
- Filters on lists: `?q=&phase=&status=&warning=&has_voi=&scope=&sort=` plus `var.{name}=` (categorical value) or `var.{name}=min..max` (continuous).
- No auth headers (ADR-0004). Writes that record authorship require the `X-Reviewer` header (CUR-01).
- Run and source starts take an optional `X-Reviewer` (API-45, API-62, API-69 start and convert, API-70 create); their records return `reviewer` and `origin` (CTF-15). Records written before origins existed return `origin: null`.
- Long operations return `202 {job_id}`; progress arrives via SSE (API-40).

## Endpoints

| ID | Method & path | Purpose | Ref |
|---|---|---|---|
| API-01 | `GET /health` | Liveness, versions, UI runtime config (`VIEWER_MAX_LOADED`, `PUBLIC_BASE_URL`) | OPS-03/07 |
| API-02 | `GET /projects` · `POST /projects` | List / create `{name, description?, default_modality?, packs?}` (neutral; `packs` for scripts) | PRJ-01/02/14 |
| API-03 | `GET·PATCH /projects/{pid}` | Read (with `ETag`) / rename / edit label map, `default_modality`, `display`; PATCH needs `If-Match` → `428 precondition-required` when missing, `412 precondition-failed` when stale | PRJ-06/07/14/15/18 |
| API-04 | `POST /projects/{pid}/archive` · `POST /projects/{pid}/unarchive` | Archive / restore (no DELETE endpoint); archive → `409 job-conflict` while any job of the project is live | PRJ-06 |
| API-05 | `GET /projects/{pid}/roots` · `PUT /projects/{pid}/roots/{alias}` | Aliases / relink (+ verify report); body `{path, role?}`, `role: derived` registers the derived root (PRJ-13; default = the alias's current role, else `source`) | PRJ-05/13 |
| API-06 | `POST /projects/{pid}/bundle` · `POST /projects/import-bundle` | Export (`200 application/zip`, attachment) / import (multipart field `bundle` → `201` report, §Bundles) | PRJ-08/09 |
| API-07 | `POST /open` · `GET /open/{sid}?item=` · `GET /open/{sid}/items?cursor=&limit=&kind=` · `DELETE /open/{sid}` | Open mode: `{path}` → `201 {sid, path, root, kind, items[], truncated, ignored, has_dicom}` (an item carries `modality` and `image_component` as in DATA_MODEL §Item) (initial preview capped at 500 complete items; optional `item` returns that stable index and its latest attached label; the item page optionally filters `kind=image\|label` before pagination; `has_dicom` describes the full session, including omitted items; headers only, DICOM/NumPy converted into `.scratch/`); DELETE → `204`; an ended session (closed, server restarted) → `not-found` with `actions: ["choose_another_path", "home"]` | SRC-09 |
| API-08 | `GET /open/{sid}/items/{n}/image?axis_order=` · `GET …/items/{n}/preview?axis_order=` · `POST /open/{sid}/items/{n}/attach` | Open-mode bytes (Range; NumPy needs a decided or given `axis_order`, else `ambiguous-axis-order`) / NumPy middle slice PNG / attach a segmentation `{path}` from anywhere under `ALLOWED_DATA_ROOTS` (ADR-0027) → the session with the new label item (`rel` absolute when outside the session root), or `geometry-mismatch`; every Open refusal carries `actions` (`choose_another_path`, `home`); also `GET …/items/{n}/dicom-tags` (DICOM JSON of the item's first header, VW-22) | SRC-10/12 |
| API-09 | `POST /open/{sid}/items/{n}/save` | `{dest_dir?, sidecar, anonymize}` → `201 {path, sidecar_path}`; `dest_dir` inside `ALLOWED_DERIVED_ROOTS` (default `{first}/_open/{YYYY-MM-DD}/`), never overwrites; `derived-root-required` when `ALLOWED_DERIVED_ROOTS` is empty | SRC-14 |
| API-10 | `POST /fs/list` | `{path?, role}` → server folder browser (a POST, so browsed folders stay out of URLs and access logs, NFR-17), limited to `ALLOWED_DATA_ROOTS` (`role=derived`: `ALLOWED_DERIVED_ROOTS`, `derived-root-required` when empty) | IMP-01, PRJ-13 |
| API-11 | `POST /projects/{pid}/imports/preview` | Multipart files or `{root, detect: true, adapter?, options?}` → preview (`adapter`: `metadata-v1` default, `nifti-files`; a NIfTI file as `root` = single-file import, SRC-05; `metadata-v1` takes only `options.reconstruct_sidecars` (IMP-15; `derived-root-required` without a derived root)). The preview adds `adapter`, `options`, `sample`, `unmatched`, `orphan_masks`, `ignored`, and `incomplete {converted, failed, pending}` for a converter dataset that is not complete (DCM-34) | IMP-02/03/15, SRC-03..06 |
| API-12 | `POST /projects/{pid}/imports` | Commit preview (`{preview_id, allow_incomplete?}`) → `202 {job_id}` (indexing); an incomplete converter dataset without `allow_incomplete` → `409 job-conflict` with action `acknowledge:incomplete_dataset` (DCM-34) | IMP-04/05 |
| API-13 | `GET /projects/{pid}/imports` | Import history + current `index` status | IMP-04 |
| API-14 | `GET /projects/{pid}/warnings` | QC warnings (filterable) | IMP-08 |
| API-15 | `POST /projects/{pid}/hash-jobs` | Full SHA-256 job: body `{force?}` → `202 {job_id, n_files, n_skipped}`; results appear as `image.sha256` / `mask.sha256` on API-21/22 | IMP-09 |
| API-16 | `GET /projects/{pid}/variables` · `PATCH …/variables/{name}` | Catalog with profile; each variable carries `origin` and `category` (Metadata only); override type/visibility/tags/category | VAR-01..05, VAR-14 |
| API-17 | `POST /projects/{pid}/variables/derived` · `DELETE …/derived/{name}` | Bin / recode / dominant | VAR-06 |
| API-18 | `POST /projects/{pid}/variables/external` | **Deprecated** (VAR-07 retired): CSV/TSV keyed by case_id or patient_id → match report; kept for existing projects and scripts, the app no longer calls it. New clinical data: API-58 | VAR-07 |
| API-19 | `POST /sources/detect` | `{path}` (folder or file) → `{path, kind, root, candidates: [{adapter, reason, counts, confidence, options, available, unavailable_reason, sample}], counts, ignored}`; adapters `metadata-v1`, `nifti-files`, `dicom.convert`, `open`; `sample` (nifti-files): up to 50 relative NIfTI paths spread over the folder (SRC-17); nothing accepted → `unsupported-format` | SRC-01..06 |
| API-20 | `GET /projects/{pid}/cases` | Case summaries with the CUR-08 rollup (`curation_status`, `review_state`, `n_items_reviewed`, `n_items_active`); filters `q`, `phase`, `status` (item status), `curation_status` (the case rollup), `warning`, `has_voi`, `var.{name}` | DATA_MODEL, CUR-08 |
| API-21 | `GET /projects/{pid}/cases/{cid}` | Case + items tree + warnings | |
| API-22 | `GET /projects/{pid}/items/{iid}` · `GET …/items/{iid}/dicom-tags` | Item record (+ `advanced` with absolute paths) / its DICOM JSON sidecar, on demand (`not-found` without one) | DCM-04/05 |
| API-23 | `GET /projects/{pid}/items/{iid}/image` | Image bytes (Range, ETag) | BE-04 |
| API-24 | `GET /projects/{pid}/items/{iid}/mask?seg=` | Mask bytes of one segmentation set (default `default_seg`; Range, ETag) | BE-04, ADR-0015 |
| API-25 | `GET /projects/{pid}/items/{iid}/mesh/{label}?smooth=1&seg=` | Mesh of one set's label (`202` + job if not cached) | VW-09 |
| API-26 | `GET /projects/{pid}/items/{iid}/thumbnail` | Lossless WebP thumbnail (`404` until generated) | IMP-12 |
| API-27 | `GET /projects/{pid}/segmentations?removed=` · `PATCH·DELETE …/segmentations/{seg}` · `POST …/{seg}/restore` · `DELETE …/{seg}/labels/{label}` · `POST …/{seg}/labels/{label}/restore` · `POST …/segmentations/imports` · `POST …/segmentations/reindex` | Active sets by default (`removed=true` lists soft-removed sets); rename/map, reversible set or individual label removal across all cases (`removed_labels` stores set values, not project values); label actions are idempotent and preserve sources/catalog, unknown/background values get 404; attach combined NIfTI or binary-mask folders by source-root template (`202` Index job); rebuild the project index. `default_seg` via API-03. | ADR-0015, ADR-0037, ADR-0038, SRC-20 |
| API-28 | `GET /packs` · `POST /projects/{pid}/packs` `{pack_id}` | Study packs available (from plugins, each with the `clinical_tables[]` label table templates it offers: `TableCreate` bodies) / apply one → `{project, job_id}` (records `packs[]`, never deletes data; `job_id` = the reindex when phase rules changed) | PRJ-16 |
| API-29 | — | Retired (never used); the ID is not reused | — |
| API-30 | `GET /radiomics/schema` | Engine options, defaults, constraints | RAD-01 |
| API-31 | — | Retired by AUD-A4-09 (FB11): alias of API-43 for `radiomics.pyradiomics` (RAD-13); the ID is not reused | — |
| API-32 | `GET·POST /projects/{pid}/radiomics/profiles` · `PATCH·DELETE …/{hash}` | Profiles | RAD-03 |
| API-33 | — | Retired by AUD-A4-09 (FB11): alias of API-44 for `radiomics.pyradiomics` (RAD-13); the ID is not reused | — |
| API-34 | — | Retired by AUD-A4-09 (FB11): alias of API-45 for `radiomics.pyradiomics` (RAD-13); the ID is not reused | — |
| API-35 | — | Retired by AUD-A4-09 (FB11): alias of API-46 for `radiomics.pyradiomics` (RAD-13); the ID is not reused | — |
| API-36 | `GET /projects/{pid}/radiomics/runs/{rid}/features?format=json\|parquet\|csv&shape=long\|wide&item_id=` | Export; the `item_id` filter + JSON feeds the Measurements panel | RAD-10, UI-14 |
| API-37 | — | Retired by AUD-A4-09 (FB11): alias of API-47 for `radiomics.pyradiomics` (RAD-13); the ID is not reused | — |
| API-38 | `POST /projects/{pid}/radiomics/runs/{rid}/views/{view}` | Dashboard computation (body = view params) | DB-* |
| API-39 | `POST /projects/{pid}/analyses` · `GET …/analyses[/{aid}]` · `GET …/analyses/{aid}/export` | Create+run / list / results + recommendations / tidy CSV + spec | ANA-* |
| API-40 | `GET /projects/{pid}/events` (SSE) | Realtime stream | CUR-11 |
| API-41 | `GET /jobs?project={pid}` · `GET /jobs/{job_id}` · `POST /jobs/{job_id}/cancel` | Jobs panel / one job (`JobInfo`; scripts and a future job deep link, no UI caller) / cancel | BE-06 |
| API-42 | `GET /tasks` · `GET /tasks/{tid}` | `{tasks: [{manifest, source, manifest_hash, available, unavailable_reason, runner_online, settings_schema_url}], invalid: [{path, error}], runners[]}`. nnU-Net's `execution.inventory` includes `required_free_mb`; device `busy` means insufficient or unknown memory under ADR-0039. Approved GPU labels show free/total GiB. | TSK-01, TSK-11 |
| API-43 | `POST /tasks/{tid}/validate` | Settings → issues (`radiomics.pyradiomics`: optional `labels`, `n_items` checked as well) | TSK-02, RAD-04 |
| API-44 | `POST /projects/{pid}/tasks/{tid}/preflight` · `…/estimate` | Selection → readiness + suggestions / estimate (source tasks: the dry run with `series[]` + `series_truncated`, DCM-06) | TSK-04/05, RAD-11 |
| API-45 | `POST·GET /projects/{pid}/task-runs?task=&archived=` · `GET …/task-runs/{rid}` | Start (`{task_id, settings, selection, name?, allow_mixed_versions?}`; the last only for `dicom.convert`, DCM-31), optional `X-Reviewer` → `202 {run_id, job_id, status}`) / list (radiomics runs included; archived supervised runs only with `archived=true`) / detail | TSK-06/10/15, RAD-06/09 |
| API-46 | `POST …/task-runs/{rid}/cancel` · `…/resume` · `…/retry-failed` · `…/pause` · `…/archive` | Control. `retry-failed` is DICOM-only and requires `{expected_attempt}`; ordinary controls retain their contracts. `pause`/`archive` and the supervised `cancel` are idempotent and answer the detail with its `control` request; incompatible transitions → 409 | TSK-07/15, DCM-17, RAD-08 |
| API-47 | `GET …/task-runs/{rid}/errors` · `GET …/task-runs/{rid}/outputs` | Per-item failures / registered outputs | TSK-09, RAD-07 |
| API-48 | `GET /projects/{pid}/annotations?field=&run=&item_id=` · `GET …/annotation-sources` · `PUT …/annotation-sources/{field}` | Annotations with confidence/evidence and `active` / active runs / activate a run (`{run_id\|null}` → `{annotation_sources, job_id}`, the reindex job) | ANZ-01/04 |
| API-49 | `GET /plugins` · `GET /plugins/{id}` | Plugin Library: installed first-party plugins, contributions, status (`ready`, `needs runner`, `needs derived root`, `needs segmentation`, `pending`) with the reason | PLG-05/06 |
| API-50 | `GET·POST /projects/{pid}/curation/events` | History (filter by `item_id`/`case_id`) / append (`X-Reviewer`, optional `X-Session-Id`) | CUR-02/14 |
| API-51 | `GET /projects/{pid}/curation/state` | Derived latest state | CUR-08 |
| API-52 | `GET /projects/{pid}/curation/queue?format=json\|csv&status=` | Correction queue; `status` keeps only the rows with that status | CUR-09 |
| API-53 | `POST /projects/{pid}/curation/exports` | Write CUR-10 files to `exports/` | CUR-10 |
| API-54 | `POST /projects/{pid}/curation/import-v2` | Import `curation_review.csv` → `201 {n_rows, imported, phase_events, skipped[]}`; `phase_issue` rows become phase events (PHS-08) | CUR-13 |
| API-55 | `POST /projects/{pid}/curation/import-converter` | Import the converter CLI's `curation.csv` (multipart `file`, `X-Reviewer`) → `201` report as API-54 | CUR-15 |
| API-56 | `GET·POST /plugins/labeling/projects/{pid}/tables[?deleted=true]` · `PATCH …/tables/{tid}` · `GET …/tables/{tid}/history?target=&column_id=` | Label tables and column schemas (list rows carry `n_rows` + per-column `progress`; `?deleted=true` lists only deleted tables) / `PATCH {name?, hidden?, columns?}`: rename, delete or restore (`hidden`), column upserts / cell history, newest first. A deleted table answers 404 everywhere except `PATCH`. A column with `ref` mirrors a comparable variable (LBL-09, read-only). | LBL-01/02/04/08/09/10 |
| API-57 | `GET·POST /plugins/labeling/projects/{pid}/tables/{tid}/cells` | Cell state (paged, filterable) / append cell events (`X-Reviewer`) | LBL-03..05 |
| API-58 | `POST …/tables/{tid}/import` · `GET …/tables/{tid}/export?format=csv\|parquet` | CSV import with a match report / export | LBL-07 |
| API-59 | `GET /projects/{pid}/exports/dataset-table?format=csv\|parquet\|jsonl&include_sensitive=` · `GET /projects/{pid}/layers` | Merged metadata table (rows + active layers; attachment, not stored), layer columns named `{field}@{layer id}`, Parquet schema metadata `layers` = provenance; `jsonl` = `dataset.jsonl` (ADR-0025): one object per item, JSON values kept, `phase_resolved` when a selection replaced the value (PHS-03), `refs` = `dicom_sidecar` and `annotations:{field}` (`tasks/runs/{run_id}/annotations.jsonl`), never inlined. Every format leaves out `sensitive` fields, UIDs and accession numbers unless `include_sensitive=true`, and always leaves out absolute paths and `raw_metadata` (VAR-09) / the active layers `{column, id, plugin, field, level, source, n_values}` | ADR-0020, ADR-0025 |
| API-60 | `GET /view/{token}/…` · `GET /view/{token}/jobs` · `POST /view/{token}/cohort/rows` · `POST /view/{token}/cohort/summary` | Read-only mirror of the project GET endpoints (and the project's jobs) for a view-only link, plus the two cohort reads (API-76/77, whose queries travel in the body); never exposes `project_id` or an absolute server path (PROJECT_FORMAT §View redaction); no other write exists on this path (405) | PRJ-17 |
| API-61 | `POST·DELETE /projects/{pid}/view-token` | Create/rotate → `{view_token, view_url}` / revoke (`204`) the view-only link | PRJ-17 |
| API-62 | `POST·GET /task-runs` · `GET /task-runs/{rid}` · `POST /task-runs/{rid}/cancel` · `POST /task-runs/{rid}/resume` · `POST /tasks/{tid}/estimate` · `GET /task-estimates/{eid}` · `POST /task-estimates/{eid}/cancel` | Workspace tasks (`scope: workspace`, e.g. `dicom.convert` without a project) → `{destination}/{name}/`, with optional `destination` validated per ADR-0044 (absent: `{derived}/_datasets/{name}/`); the estimate is the dry run (`series[]`, DCM-06); a source without DICOM is refused before any dataset folder exists. Both estimate routes (also API-44) take `?progress_id=` (8–64 of `A-Za-z0-9_-`) to name the dry run: `GET /task-estimates/{eid}` returns its last stage `{stage, done, total}` while it runs (404 once it returned) and `…/cancel` stops it (204). A run's `progress` adds `{stage, stage_done, stage_total}` while it scans. DICOM resume reuses the unfinished logical run/dataset after verified cleanup (DCM-17); responses include `attempts`, `cleanup_verified` and `provenance` (including independent phase-checkpoint outcome when present); completed datasets refuse resume | TSK-13 |
| API-63 | `GET·POST /projects/{pid}/phase/events` | Native, not under `/plugins/`. History, newest first (filter `case_id`/`scan_idx`) / one-click selection `{case_id, scan_idx, value, source: manual\|analyzer_accept, accepted_run_id?}` (`X-Reviewer`, optional `X-Session-Id`) → `201` PhaseEvent; `accepted_run_id` must be the active `analyzer.phase` run | PHS-01/02/04/07 |
| API-64 | `GET /projects/{pid}/phase/state?case_id=` | For scripts and external clients (the UI reads items and API-63). Latest selection per scan with the value it overrides (`resolved`, `resolved_source`). Items, cases and API-59 already carry the effective phase (`phase.source = manual`, `phase.resolved` = the index-time value) | PHS-02/03 |
| API-65 | `POST /projects/{pid}/phase/exports` | Write `exports/phase_selections.json` | PHS-06 |
| API-67 | `POST /projects/open` | `{dataset_root}` → saved ProjectDetail list; registers PRJ-19 projects from a folder. API-02 accepts optional `dataset_root`; omitting it preserves global-project behavior for existing clients. | PRJ-19 |
| API-66 | `GET·POST /projects/{pid}/items/{iid}/recycle` | Preview → RecyclePlan (counts, destination, affected projects, token); POST `{confirmed: true, token}` with `X-Reviewer` → RecycleResult. `412` if preview changed, `409` for active jobs. | CUR-16 |
| API-68 | `GET /projects/{pid}/items` | Active indexed items, sorted by case/scan/item, filtered before cursor paging. `q` searches case/patient/item IDs and image reference (case-insensitive); `scope`, `phase`, `modality`, `has_mask` filter metadata. Returns `{items, next_cursor, total}` without source/header reads. Also available through API-60 redaction. | TSK-03 |
| API-69 | `POST·GET /source-operations` · `GET /source-operations/{id}` · `GET …/series` · `GET …/detection` · `GET …/plan` · `POST …/estimate` · `POST …/convert` · `POST …/cancel` · `POST …/resume` · `POST …/retry-failed` · `POST …/open` | Durable source operation start (202 after write), list/detail, generation-paged reads and revision/attempt-fenced controls; path/context in body, opaque public IDs. Start, estimate and convert of a projectless conversion take an optional `destination` (as API-62; refused with a project or another purpose), returned as `dataset_destination`. Legacy API-07/19/44/62 response contracts retained. | TSK-16, DCM-15..19 |
| API-70 | `POST·GET /source-batches` · `GET·PATCH /source-batches/{id}` · `POST …/start` · `POST …/continue` · `POST …/cancel` · `POST …/add-new-folders` · `POST …/batches/{index}/operation` | Batch plans (ADR-0040). `POST {path, batch_size=40, settings, name, destination?, auto}` → `201` plan preview with `batches[{index, name, folder_count, files_total (null while counting), operation_id, status, dataset, approved, error, patients}]`, `status`, `cursor`, `counting`, `warnings` and `revision`; `PATCH {auto}`; `start` begins batch 1; `continue` approves conversion of the current batch or resumes a paused plan; `cancel` cancels the active operation and the unstarted batches; `add-new-folders` appends one trailing batch; `POST …/batches/{index}/operation {operation_id, expected_revision}` reassigns a failed or cancelled batch to another operation of the same source whose folders equal the batch's and that no other batch uses (`job-conflict` on a stale revision, `validation` otherwise). Refusals: root holds DICOM files (`validation`), taken dataset name or another running plan (`job-conflict`). Folder names and PatientIDs are never returned. `POST /source-operations` accepts optional `folders` (DCM-22). | DCM-22, DCM-23, DCM-24 |
| API-71 | `GET /logs/{kind}/{id}?cursor=&limit=&project=` | `kind`: `source-operation` (API-69 id) · `workspace-run` (API-62 run id) · `project-run` (API-45 run id, with `?project=`; else `validation`) · `script-run` (API-73 id: what the script printed and its commands' lines, across attempts). A project run reads its run folder's `log.jsonl` rows and failed `items.jsonl` rows (a radiomics run: failed `errors.jsonl` rows), across attempts, with a cursor bound to the run. Otherwise the current attempt's `progress.jsonl` (stage/inventory rows as one-liners, inventory at most once per read, `log` rows, failed items) then `task.log` → `{lines[{ts, level: info\|warn\|error, stream: stage\|log\|stderr, text}], next_cursor, done}`. The opaque cursor binds the attempt and byte offsets; a new attempt restarts with a `— attempt N —` line. At most `limit` (500, ≤2000) lines and 256 KiB per read; `done` once the attempt ended and everything was read. Text is redacted: a path under a data root or the source becomes `DATA:` with the rest of the path dropped, workspace/derived paths become `WORKSPACE:`/`DERIVED:` refs, other absolute paths `…` (NFR-17, DCM-24). Unknown id `not-found`, bad cursor `validation`. | UI-29, NFR-17 |
| API-72 | `GET /ctflow/commands` · `POST /ctflow/eval` | The command catalog (core commands and one per listed task, with options from the task's settings schema) / one line or script `{line, session?, project_id?, plan, client: console\|terminal\|agent}` with optional `X-Reviewer` → `{session, project_id, value, text, steps[{command, value, task_id, target, plan, started, work, data, text}], plan_stopped, error}` (`started`/`work`: a run or source operation to follow, with its kind for status and API-71). An ended session is `not-found` with `actions: [new_session]`. Task commands call the same services as API-45/69; `plan` resolves, validates and preflights without starting anything. Unknown command or target `not-found`; refused or ambiguous targets `validation` with `actions[]` or `errors[]` | CTF-02..06, CTF-09 |
| API-73 | `POST·GET /ctflow/script-runs` · `GET /ctflow/script-runs/{id}` · `POST …/{id}/cancel` · `…/pause` · `…/resume` | Durable script runs: start `{script \| library, params?, name?, project_id?, client}` (a library script is copied into the record; parameters must match its header) with optional `X-Reviewer` → `202` record / list / detail with the last 200 journal entries / controls (`cancel` and `pause` forward to the child it waits on; `resume` replays the journal). Output through API-71 `script-run`. Incompatible transitions `job-conflict` | CTF-10..14 |
| API-74 | `GET /ctflow/scripts?project=` · `GET·PUT·DELETE /ctflow/scripts/{name}?project=` | The script library (CTF-17): list with scope (`project`, `workspace`, `shipped`), summary and parameters from each header / read with its text / save `{text}` (must parse; into the project with `?project=`, else the workspace) / delete (shipped examples cannot be removed). Bad name or text `validation` | CTF-17 |
| API-75 | `POST /projects/{pid}/task-runs/{rid}/register-converted` | A `dicom.convert` run that ended `completed_with_errors` after verified cleanup imports its converted series; failed rows become excluded items with their reasons; the run keeps its status → `200` run detail. Other runs or unverified cleanup → `409 job-conflict`. API-69 `POST …/convert` accepts optional `allow_mixed_versions` for project conversions | DCM-31, DCM-34 |
| API-76 | `POST /projects/{pid}/cohort/rows` | Cohort grid: case → scan rows over `{columns[], filters{name:[values]}, q?, phase?, sort?{column, desc}, offset=0, limit=100 (≤500)}` → `{n_cases, n_scans, rows[{case_id, values, differs[], scans[{scan_idx, item_id, phase, modality, values}]}]}`. The scan unit is the scan's `complete` item; a case row carries a column's value when all its scans agree, else `null` with the column in `differs`. Filter semantics as API-20 (`var.*` values: AND across names, OR within, `min..max` for numeric/date); `q` a case/patient-id substring, `phase` checked against the project vocabulary. A case shows when it has an item not excluded upstream and a `complete` item; `sort.column` is a requested column or `case_id`, missing values sort last. The variable table is read with column projection only. Unknown column/filter or phase `validation` | COH-03, COH-05 |
| API-77 | `POST /projects/{pid}/cohort/summary` | Column summary over the API-76 filtered rows, at the variable's level (case-level columns count once per case): `{column, filters}` → categorical `{counts (top 20), other, missing}`; numeric/date `{bins[{lo, hi, count}] (20 equal-width), missing}`. Bin edges round-trip into `var.{column}=min..max` filters. Unknown column `validation` | COH-06 |
| API-78 | `POST /projects/{pid}/cohort/balance` | Balance check over the API-76 filtered rows: `{a, b, filters, test=auto\|default\|alternative}` (two different categorical variables) → `{unit (case when both are case-level, else scan), rows[], cols[], cells[{row, col, n, expected}], excluded_rows[], excluded_cols[], test (chi2\|fisher), reason, statistic, p, cramers_v, n, missing}`. Levels with fewer than 5 units are excluded; `alternative` forces Fisher exact, `default` forces χ². Also served as `POST /view/{token}/cohort/balance` on view-only links. Unknown or non-categorical variable `validation` | COH-13 |
| API-79 | `POST /plugins/labeling/projects/{pid}/tables/{tid}/rows {case_id}` · `DELETE …/tables/{tid}/rows/{target}` | Event tables (LBL-11, ADR-0049): add a row (one event of a case; `201 {table_id, target, case_id, removed}`, target `{case_id}#{n}`) / remove it (the `#` percent-encoded). Need `X-Reviewer`. A table of another level, an unknown case or a missing reviewer is refused (`validation`, `reviewer-required`). | LBL-12 |
| API-80 | `GET /projects/{pid}/cohort/timeline/{case_id}` (also `GET /view/{token}/cohort/timeline/{case_id}`) | One case on a day axis: `{case_id, anchor_scan, scans[{scan_idx, item_id, phase, day}], events[{table_id, table, target, kind, day, values}], followup_days}`. Days count from the earliest dated scan (the anchor); no calendar date is returned. Unknown case `not-found`. | COH-14 |

API-69 also provides revision/attempt-fenced `POST …/import-draft`,
`POST …/import-preview` (202), and `POST …/import-commit` (202; optional `allow_incomplete`, DCM-34). Draft choices
persist on the operation; preview and commit intent/job identities persist before
acknowledgment. The existing import service builds previews and indexes in managed
background jobs. Detail responses expose `import_preview` and `import_job`;
Cancel drains current work, and Resume restarts the retained stage. Committing a
retained preview reuses the same import identity and immutable snapshot. A project
must be chosen explicitly before Preview/Commit.

API-69 discovery-only requests can include `import_context` with `alias`, preferred
`adapter`, `add` and draft adapter `options`. These choices persist on the operation
before 202, independent of browser storage. Context is refused for Open/conversion
or `prepare_plan=true`. Its Estimate command requires a separate conversion
operation; adapter options still require Preview validation. Omitting context preserves the request hashes of older idempotency receipts.

API-69 `purpose=discover` uses the same recoverable inventory lifecycle. Once discovery
is complete and cleanup verified, `GET …/detection` returns the API-19 `DetectResult`
from the retained inventory without walking source directories or probing image headers.
It uses the same adapter policy, ignored-name rules and up-to-50 evenly spread NIfTI
samples as API-19. Active, cancelled, partial, missing or incompatible inventories return
409 with next actions. These are hints from the prepared generation; import Preview still
validates the selected source/options. Results create no import, project or conversion run.

API-69 `purpose=open` prepares whole image/series header units under the existing owned-worker
lifecycle. `POST …/open` returns 201 with the API-07 preview after verified completion and
cleanup; the session URL and byte routes restore that durable result after API restart.
Attached masks persist as managed session state. Close ends that preview; another explicit
`POST …/open` reopens the retained result. Incompatible reader/code or altered result bytes
return 409. Open rejects `prepare_plan=true` and Estimate: conversion starts a separate operation.

API-69 implementation: `prepare_plan` persists discovery → Estimate intent before returning 202.
`ready` means a complete plan is available; conversion requires the separate generation-fenced command.
The linked `conversion_run` projects API-45/62 authority; it is not a second native run record.
Controls include the operation revision/attempt and `expected_run_attempt` when linked.
After the first native attempt, missing or stale run fences return 409.
`pending_control` retains a command interrupted before acknowledgment; retry its exact `request`.
A native `resume_request_id` proves its attempt belongs to that command, including after restart.
Duplicate acknowledged commands return current state without creating another attempt.
Native API-46/47 DICOM controls and operation controls share the run lock.
API-45 list rows include `attempts`. API-46/62 cancel/resume accept an optional `{expected_attempt}` body; it is required for the linked phase run and stale attempts return 409. Other task runtimes retain their existing controls.
Conversion details expose `phase_run_id`; API-69 `phase_run` projects the child's API-45/62 record. Phase retry uses the child's control endpoint and returns its new job; repeating the same retry fence returns that attempt without launching another worker. Phase and conversion outcomes remain independent (ANZ-02/04).
`retry-failed` delegates to the linked API-46/62 conversion run and always requires
`expected_run_attempt`. API-62 also exposes `POST /task-runs/{rid}/retry-failed`
with `{expected_attempt}`. Both native routes return 202 `TaskRunStarted`.
Only stopped, cleanup-verified, unsealed conversions with recorded failures may retry;
missing/stale fences, unavailable outcome history and an empty failure selection return 409.
Native duplicate retry fences identify the same attempt; the source facade persists a distinct
`retry_failed` receipt. Its incompatible controls remain blocked until that receipt settles.
Project counts add `pending`; workspace counts retain converter names including `pending`.
Failed background plans persist `problem` details/actions; non-DICOM refusals retain API-44/62 remedies.
API-69 Estimate accepts an optional `name`: omitted/null preserves it; an empty string restores the neutral default.
Settings-only Estimate retains the operation/inventory but replaces the plan attempt; previous conversion fences return 409.
API-69 discovery `progress` adds `files_total`/`folders_total` (provisional while `progress_stage` is `counting`, DCM-20) and keeps `rejected`; the operation adds nullable `discovery_eta` `{low_s, high_s, basis: unknown|recent_rate}` (DCM-21), and `summary` adds `files_total`, `folders_total`, `inventory_cap_bytes` and `inventory_projection {projected_bytes, cap_bytes, warning}`. All are additive.
API-45 DICOM `progress` retains DCM-16 counters and separate `stage`, `stage_done`, `stage_total`; ETA stays null without compatible history.
API-44/62 estimates and API-45/62 DICOM run details expose additive `conversion_time`:
`basis: unknown|history|complete`, `confidence: unknown|low`, `sample_count`,
`remaining_units`, and nullable finite nonnegative `estimated_s`/`lower_s`/`upper_s`.
Unknown has no time values; history requires at least five compatible observations and an
ordered range; complete has zero remaining work/time. This covers conversion only (DCM-19),
not discovery, registration or phase analysis. Generic job `eta_s` is not substituted.
The enclosing estimate retains its existing `basis: sample|manifest|unknown` enum:
compatible historical measurements use `sample`, with their precise basis in `conversion_time`.
API-45/62 DICOM run `progress` adds optional `bytes_done`, `bytes_total` (selected series' source bytes, committed incl. verified reuse) and `bytes_per_s` (present once this attempt converted a series), DCM-25. API-70 plans add `eta {low_s, high_s, basis: unknown|completed_batches}`: the time left for unfinished batches, `unknown` with null bounds until a batch completes. All additive.
API-45/62 resource waits expose typed `resource_wait` (`reason`, optional `required_mb`/`budget_mb`, `remedy`); resume clears the prior wait.
API-69 projects pending project registration as `status: reconciling`, `stage: registering`,
even when native conversion is complete. API-45 `execution.registration_pending` and
`registration_job_id` identify background metadata recovery; its native attempt stays unchanged.
Polling does not wait for indexing. Registration-only Resume also replays a lost response without
another pixel attempt; failed registration remains visible until that control or restart recovery.
An occupied project index is also a registration failure with that remedy; it does not leave
the operation indefinitely reporting active reconciliation after its job has stopped.
API-69 registration Cancel persists `execution.registration_cancel_requested` on the linked
API-45 run, reports `cancelling` while metadata workers drain, then `cancelled` after
`registration_cancelled` is recorded. Native conversion stays completed. Resume before that
point returns 409; afterward it retries registration in the same native attempt. Controls share
the generated-import dispatch gate and replay lost acknowledgments. Committed artifacts and
already registered rows are retained; cancellation does not roll them back.
API-69 reconfirms metadata durability before acknowledging repeated controls. Creation reserves
its request receipt before installing the operation; a pending creation can be reconstructed
before dispatch, while a committed receipt with a missing operation is refused. Replaying a
queued discovery/Estimate or conversion handoff whose submission never occurred reuses its operation
and attempt; retained execution evidence blocks redispatch until cleanup is reconciled. Legacy creation receipts
without a completion field remain readable when their operation exists.
When a source job stops before publishing its final state, subsequent reads reconcile the operation
against finished-job and native cleanup evidence. Verified failure/interruption is resumable;
unconfirmed cleanup remains `cleanup_pending`, and a still-finalizing job is not treated as stopped.

Radiomics is the task `radiomics.pyradiomics` (RAD-13): validate, estimate, runs, control and errors are API-43..47, whose answers carry the radiomics record as `radiomics` (API-43 `ValidateResult`, API-44 `EstimateResult`, API-45 list `RunSummary` / detail and API-46 cancel `RunDetail`, API-47 `RunError` per row). Only the engine schema (API-30), profiles (API-32), feature exports (API-36) and dashboard views (API-38) are radiomics routes.

## SSE event types (API-40)

| `event` | `data` |
|---|---|
| `curation.appended` | CurationEvent |
| `labeling.appended` | CellEvent (LBL-04); a batch over 500 cells sends `project.updated {fields: [labeling]}` instead |
| `phase.appended` | PhaseEvent (PHS-05); an import over 500 events sends `project.updated {fields: [phase]}` instead |
| `job.progress` | `{job_id, kind, done, total, eta_s}` |
| `job.finished` | `{job_id, kind, status, ref}` |
| `job.status` | `{job_id, status}`, e.g. `waiting_for_runner` → `running` (TSK-06) |
| `index.rebuilt` | `{import_id, n_items, n_warnings}` |
| `project.updated` | `{fields[]}` |
| `reset` | `{}`, sent first when `Last-Event-ID` cannot be resumed (from before a restart, older than an evicted event, unknown); its `id` is the newest one, and the client refetches the project (AUD-A5-11) |

The stream opens with a `: open` comment and `retry: 3000`, so clients (Firefox) see it live at once.
Clients reconnect with `Last-Event-ID`; the server replays up to 1,000 recent events per project, or sends `reset` when it cannot. The web client also refetches the project whenever the stream reopens after an error.

## Bundles (API-06)

Import answers `201 {project: ProjectDetail, source_project_id, id_changed, roots: [{root: {alias, path, exists}, verify: VerifyReport}], needs_relink}`.
`exists` is false when the directory is missing or outside `ALLOWED_DATA_ROOTS`; `needs_relink` is true if any root is missing or any verify sample is missing or mismatched, and the client then opens relink (API-05).
Errors: `validation` (not a zip, unsafe entry, no/invalid `project.json`), `format-version-unsupported`. Bundle rules: PROJECT_FORMAT §Bundles.

## Errors (RFC 9457)

`{type, title, status, detail, instance, errors?[], actions?[]}`, where `type` is a slug under `/problems/` and `actions[]` lists next steps the UI offers (SRC-11):

| Slug | Status |
|---|---|
| `not-found` | 404 |
| `validation` | 422 (`errors[]` = field issues; also an unconvertible legacy `.npy`) |
| `path-outside-root` | 403 |
| `source-missing` | 409 |
| `format-version-unsupported` | 409 |
| `job-conflict` | 409 |
| `precondition-failed` | 412 |
| `precondition-required` | 428 |
| `reviewer-required` | 428 |
| `server-busy` | 503 |
| `unsupported-format` | 415 |
| `ambiguous-axis-order` | 422 |
| `geometry-mismatch` | 422 |
| `derived-root-required` | 409 |
| `roots-overlap` | 409 |
