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
- Long operations return `202 {job_id}`; progress arrives via SSE (API-40).

## Endpoints

| ID | Method & path | Purpose | Ref |
|---|---|---|---|
| API-01 | `GET /health` | Liveness, versions, UI runtime config (`VIEWER_MAX_LOADED`, `PUBLIC_BASE_URL`) | OPS-03/07 |
| API-02 | `GET /projects` · `POST /projects` | List / create `{name, description?, default_modality?, packs?}` (neutral; `packs` for scripts) | PRJ-01/02/14 |
| API-03 | `GET·PATCH /projects/{pid}` | Read (with `ETag`) / rename / edit label map, `default_modality`, `display`; PATCH needs `If-Match` → `428 precondition-required` when missing, `412 precondition-failed` when stale | PRJ-06/07/14/15/18 |
| API-04 | `POST /projects/{pid}/archive` · `POST /projects/{pid}/unarchive` | Archive / restore (no DELETE endpoint) | PRJ-06 |
| API-05 | `GET /projects/{pid}/roots` · `PUT /projects/{pid}/roots/{alias}` | Aliases / relink (+ verify report); body `{path, role?}`, `role: derived` registers the derived root (PRJ-13; default = the alias's current role, else `source`) | PRJ-05/13 |
| API-06 | `POST /projects/{pid}/bundle` · `POST /projects/import-bundle` | Export (`200 application/zip`, attachment) / import (multipart field `bundle` → `201` report, §Bundles) | PRJ-08/09 |
| API-07 | `POST /open` · `GET /open/{sid}` · `DELETE /open/{sid}` | Open mode: `{path}` → `201 {sid, path, root, kind, items[], truncated, ignored}` (headers only; DICOM/NumPy converted into `.scratch/`); DELETE → `204` | SRC-09 |
| API-08 | `GET /open/{sid}/items/{n}/image?axis_order=` · `GET …/items/{n}/preview?axis_order=` · `POST /open/{sid}/items/{n}/attach` | Open-mode bytes (Range; NumPy needs a decided or given `axis_order`, else `ambiguous-axis-order`) / NumPy middle slice PNG / attach a segmentation `{path}` → the session with the new label item, or `geometry-mismatch`; also `GET …/items/{n}/dicom-tags` (DICOM JSON of the item's first header, VW-22) | SRC-10/12 |
| API-09 | `POST /open/{sid}/items/{n}/save` | SRC-14: `{dest_dir?, sidecar, anonymize}` → `201 {path, sidecar_path}`; `dest_dir` inside `ALLOWED_DERIVED_ROOTS` (default `{first}/_open/{YYYY-MM-DD}/`), never overwrites; `derived-root-required` when `ALLOWED_DERIVED_ROOTS` is empty | SRC-14 |
| API-10 | `GET /fs/list?path=&role=` | Server folder browser, limited to `ALLOWED_DATA_ROOTS` (`role=derived`: `ALLOWED_DERIVED_ROOTS`, `derived-root-required` when empty) | IMP-01, PRJ-13 |
| API-11 | `POST /projects/{pid}/imports/preview` | Multipart files or `{root, detect: true, adapter?, options?}` → preview (`adapter`: `metadata-v1` default, `nifti-files`; a NIfTI file as `root` = single-file import, SRC-05). The preview adds `adapter`, `options`, `sample`, `unmatched`, `orphan_masks`, `ignored` | IMP-02/03, SRC-03..06 |
| API-12 | `POST /projects/{pid}/imports` | Commit preview → `202 {job_id}` (indexing) | IMP-04/05 |
| API-13 | `GET /projects/{pid}/imports` | Import history + current `index` status | IMP-04 |
| API-14 | `GET /projects/{pid}/warnings` | QC warnings (filterable) | IMP-08 |
| API-15 | `POST /projects/{pid}/hash-jobs` | Full SHA-256 job: body `{force?}` → `202 {job_id, n_files, n_skipped}`; results appear as `image.sha256` / `mask.sha256` on API-21/22 | IMP-09 |
| API-16 | `GET /projects/{pid}/variables` · `PATCH …/variables/{name}` | Catalog with profile; override type/visibility/tags | VAR-01..05 |
| API-17 | `POST /projects/{pid}/variables/derived` · `DELETE …/derived/{name}` | Bin / recode / dominant | VAR-06 |
| API-18 | `POST /projects/{pid}/variables/external` | CSV/TSV keyed by case_id or patient_id → match report | VAR-07 |
| API-19 | `POST /sources/detect` | `{path}` (folder or file) → `{path, kind, root, candidates: [{adapter, reason, counts, confidence, options, available, unavailable_reason}], counts, ignored}`; adapters `metadata-v1`, `nifti-files`, `dicom.convert`, `open`; nothing accepted → `unsupported-format` | SRC-01..06 |
| API-20 | `GET /projects/{pid}/cases` | Case summaries | DATA_MODEL |
| API-21 | `GET /projects/{pid}/cases/{cid}` | Case + items tree + warnings | |
| API-22 | `GET /projects/{pid}/items/{iid}` · `GET …/items/{iid}/dicom-tags` | Item record (+ `advanced` with absolute paths) / its DICOM JSON sidecar, on demand (`not-found` without one) | DCM-04/05 |
| API-23 | `GET /projects/{pid}/items/{iid}/image` | Image bytes (Range, ETag) | BE-04 |
| API-24 | `GET /projects/{pid}/items/{iid}/mask?seg=` | Mask bytes of one segmentation set (default `default_seg`; Range, ETag) | BE-04, ADR-0015 |
| API-25 | `GET /projects/{pid}/items/{iid}/mesh/{label}?smooth=1&seg=` | Mesh of one set's label (`202` + job if not cached) | VW-09 |
| API-26 | `GET /projects/{pid}/items/{iid}/thumbnail` | Lossless WebP thumbnail (`404` until generated) | IMP-12 |
| API-28 | `GET /packs` · `POST /projects/{pid}/packs` `{pack_id}` | Study packs available (from plugins) / apply one → `{project, job_id}` (records `packs[]`, never deletes data; `job_id` = the reindex when phase rules changed) | PRJ-16 |
| API-27 | `GET /projects/{pid}/segmentations` · `PATCH …/segmentations/{seg}` | Sets with producer + counts / rename, label mapping; `default_seg` via API-03 | ADR-0015 |
| API-30 | `GET /radiomics/schema` | Engine options, defaults, constraints | RAD-01 |
| API-31 | `POST /radiomics/validate` | Settings → issues | RAD-04 |
| API-32 | `GET·POST /projects/{pid}/radiomics/profiles` · `PATCH·DELETE …/{hash}` | Profiles | RAD-03 |
| API-33 | `POST /projects/{pid}/radiomics/estimate` | Pre-run estimate | RAD-11 |
| API-34 | `POST /projects/{pid}/radiomics/runs` · `GET …/runs` · `GET …/runs/{rid}` | Start / list / detail | RAD-06 |
| API-35 | `POST …/runs/{rid}/cancel` · `POST …/runs/{rid}/resume` | Control | RAD-06/08 |
| API-36 | `GET …/runs/{rid}/features?format=json\|parquet\|csv&shape=long\|wide&item_id=` | Export; the `item_id` filter + JSON feeds the Measurements panel | RAD-10, UI-14 |
| API-37 | `GET …/runs/{rid}/errors` | Per-item failures | RAD-07 |
| API-38 | `POST …/runs/{rid}/views/{view}` | Dashboard computation (body = view params) | DB-* |
| API-39 | `POST /projects/{pid}/analyses` · `GET …/analyses[/{aid}]` · `GET …/analyses/{aid}/export` | Create+run / list / results + recommendations / tidy CSV + spec | ANA-* |
| API-40 | `GET /projects/{pid}/events` (SSE) | Realtime stream | CUR-11 |
| API-41 | `GET /jobs?project={pid}` · `POST /jobs/{job_id}/cancel` | Jobs panel | BE-06 |
| API-42 | `GET /tasks` · `GET /tasks/{tid}` | `{tasks: [{manifest, source, manifest_hash, available, unavailable_reason, runner_online, settings_schema_url}], invalid: [{path, error}], runners[]}` | TSK-01, TSK-11 |
| API-43 | `POST /tasks/{tid}/validate` | Settings → issues | TSK-02 |
| API-44 | `POST /projects/{pid}/tasks/{tid}/preflight` · `…/estimate` | Selection → readiness + suggestions / estimate | TSK-04/05 |
| API-45 | `POST·GET /projects/{pid}/task-runs?task=` · `GET …/task-runs/{rid}` | Start (`{task_id, settings, selection, name?}`, optional `X-Reviewer` → `202 {run_id, job_id, status}`) / list (radiomics runs included) / detail | TSK-06/10 |
| API-46 | `POST …/task-runs/{rid}/cancel` · `POST …/task-runs/{rid}/resume` | Control | TSK-07 |
| API-47 | `GET …/task-runs/{rid}/errors` · `GET …/task-runs/{rid}/outputs` | Per-item failures / registered outputs | TSK-09 |
| API-49 | `GET /plugins` · `GET /plugins/{id}` | Plugin Library: installed first-party plugins, contributions, status (`ready`, `needs runner`, `needs derived root`, `needs segmentation`, `pending`) with the reason | PLG-05/06 |
| API-48 | `GET /projects/{pid}/annotations?field=&run=&item_id=` · `GET …/annotation-sources` · `PUT …/annotation-sources/{field}` | Annotations with confidence/evidence and `active` / active runs / activate a run (`{run_id\|null}` → `{annotation_sources, job_id}`, the reindex job) | ANZ-01/04 |
| API-50 | `GET·POST /projects/{pid}/curation/events` | History (filter by `item_id`/`case_id`) / append (`X-Reviewer`, optional `X-Session-Id`) | CUR-02/14 |
| API-51 | `GET /projects/{pid}/curation/state` | Derived latest state | CUR-08 |
| API-52 | `GET /projects/{pid}/curation/queue?format=json\|csv` | Correction queue | CUR-09 |
| API-53 | `POST /projects/{pid}/curation/exports` | Write CUR-10 files to `exports/` | CUR-10 |
| API-54 | `POST /projects/{pid}/curation/import-v2` | Import `curation_review.csv` | CUR-13 |
| API-55 | `POST /projects/{pid}/curation/import-converter` | Import the converter CLI's `curation.csv` (multipart `file`, `X-Reviewer`) → `201` report as API-54 | CUR-15 |

| API-56 | `GET·POST /plugins/labeling/projects/{pid}/tables` · `PATCH …/tables/{tid}` · `GET …/tables/{tid}/history?target=&column_id=` | Label tables and column schemas (list rows carry `n_rows` + per-column `progress`) / cell history, newest first | LBL-01/02/04/08 |
| API-57 | `GET·POST /plugins/labeling/projects/{pid}/tables/{tid}/cells` | Cell state (paged, filterable) / append cell events (`X-Reviewer`) | LBL-03..05 |
| API-58 | `POST …/tables/{tid}/import` · `GET …/tables/{tid}/export?format=csv\|parquet` | CSV import with a match report / export | LBL-07 |
| API-59 | `GET /projects/{pid}/exports/dataset-table?format=csv\|parquet` · `GET /projects/{pid}/layers` | Merged metadata table (rows + active layers; attachment, not stored), layer columns named `{field}@{layer id}`, Parquet schema metadata `layers` = provenance / the active layers `{column, id, plugin, field, level, source, n_values}` | ADR-0020 |
| API-60 | `GET /view/{token}/…` | Read-only mirror of the project GET endpoints for a view-only link; never exposes `project_id`; writes do not exist on this path | PRJ-17 |
| API-61 | `POST·DELETE /projects/{pid}/view-token` | Create/rotate → `{view_token, view_url}` / revoke (`204`) the view-only link | PRJ-17 |
| API-62 | `POST·GET /task-runs` · `GET /task-runs/{rid}` · `POST /task-runs/{rid}/cancel` · `POST /tasks/{tid}/estimate` | Workspace tasks (`scope: workspace`, e.g. `dicom.convert` without a project) → `{derived}/_datasets/{name}/`; the estimate is the dry run | TSK-13 |

API-30..37 are aliases of API-42..47 for `radiomics.pyradiomics` during P7b (RAD-13) and are removed one release after the P7b exit.

## SSE event types (API-40)

| `event` | `data` |
|---|---|
| `curation.appended` | CurationEvent |
| `labeling.appended` | CellEvent (LBL-04); a batch over 500 cells sends `project.updated {fields: [labeling]}` instead |
| `job.progress` | `{job_id, kind, done, total, eta_s}` |
| `job.finished` | `{job_id, kind, status, ref}` |
| `job.status` | `{job_id, status}`, e.g. `waiting_for_runner` → `running` (TSK-06) |
| `index.rebuilt` | `{import_id, n_items, n_warnings}` |
| `project.updated` | `{fields[]}` |

The stream opens with a `: open` comment and `retry: 3000`, so clients (Firefox) see it live at once.
Clients reconnect with `Last-Event-ID`; the server replays up to 1,000 recent events per project.

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
