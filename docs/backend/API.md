# HTTP API (v1)

Scope: endpoint list, conventions, errors, realtime events.
Read when: adding or consuming an endpoint. Payload fields come from domain docs; they are not repeated here.
Depends: domain/DATA_MODEL.md, backend/ARCHITECTURE.md.

## Conventions

- Base path `/api/v1`. JSON bodies; `snake_case`; UTC `Z` timestamps.
- `{pid}` = `project_id`, `{iid}` = `item_id`, `{cid}` = `case_id`, `{rid}` = `run_id`.
- Lists: `?cursor=&limit=` (default 200, max 2000) → `{items, next_cursor, total}`.
- Filters on lists: `?q=&group=&phase=&status=&warning=&has_voi=&scope=&sort=`.
- No auth headers (ADR-0004). Writes that record authorship require the `X-Reviewer` header (CUR-01).
- Long operations return `202 {job_id}`; progress arrives via SSE (API-40).

## Endpoints

| ID | Method & path | Purpose | Ref |
|---|---|---|---|
| API-01 | `GET /health` | Liveness, versions, UI runtime config (`VIEWER_MAX_LOADED`, `PUBLIC_BASE_URL`) | OPS-03/07 |
| API-02 | `GET /projects` · `POST /projects` | List / create | PRJ-01/02 |
| API-03 | `GET·PATCH /projects/{pid}` | Read / rename / edit label map, defaults | PRJ-06/07 |
| API-04 | `POST /projects/{pid}/archive` · `POST /projects/{pid}/unarchive` | Archive / restore (no DELETE endpoint) | PRJ-06 |
| API-05 | `GET /projects/{pid}/roots` · `PUT /projects/{pid}/roots/{alias}` | Aliases / relink (+ verify report) | PRJ-05 |
| API-06 | `POST /projects/{pid}/bundle` · `POST /projects/import-bundle` | Export / import bundle | PRJ-08/09 |
| API-10 | `GET /fs/list?path=` | Server folder browser, limited to `ALLOWED_DATA_ROOTS` | IMP-01 |
| API-11 | `POST /projects/{pid}/imports/preview` | Multipart files or `{root, detect:true}` → preview | IMP-02/03 |
| API-12 | `POST /projects/{pid}/imports` | Commit preview → `202 {job_id}` (indexing) | IMP-04/05 |
| API-13 | `GET /projects/{pid}/imports` | Import history + current `index` status | IMP-04 |
| API-14 | `GET /projects/{pid}/warnings` | QC warnings (filterable) | IMP-08 |
| API-15 | `POST /projects/{pid}/hash-jobs` | Full SHA-256 job | IMP-09 |
| API-20 | `GET /projects/{pid}/cases` | Case summaries | DATA_MODEL |
| API-21 | `GET /projects/{pid}/cases/{cid}` | Case + items tree + warnings | |
| API-22 | `GET /projects/{pid}/items/{iid}` | Item record (+ `advanced` with absolute paths) | |
| API-23 | `GET /projects/{pid}/items/{iid}/image` | Image bytes (Range, ETag) | BE-04 |
| API-24 | `GET /projects/{pid}/items/{iid}/mask` | Mask bytes (Range, ETag) | BE-04 |
| API-25 | `GET /projects/{pid}/items/{iid}/mesh/{label}?smooth=1` | Mesh (`202` + job if not cached) | VW-09 |
| API-26 | `GET /projects/{pid}/items/{iid}/thumbnail` | Lossless WebP thumbnail (`404` until generated) | IMP-12 |
| API-30 | `GET /radiomics/schema` | Engine options, defaults, constraints | RAD-01 |
| API-31 | `POST /radiomics/validate` | Settings → issues | RAD-04 |
| API-32 | `GET·POST /projects/{pid}/radiomics/profiles` · `PATCH·DELETE …/{hash}` | Profiles | RAD-03 |
| API-33 | `POST /projects/{pid}/radiomics/estimate` | Pre-run estimate | RAD-11 |
| API-34 | `POST /projects/{pid}/radiomics/runs` · `GET …/runs` · `GET …/runs/{rid}` | Start / list / detail | RAD-06 |
| API-35 | `POST …/runs/{rid}/cancel` · `POST …/runs/{rid}/resume` | Control | RAD-06/08 |
| API-36 | `GET …/runs/{rid}/features?format=json\|parquet\|csv&shape=long\|wide&item_id=` | Export; the `item_id` filter + JSON feeds the Measurements panel | RAD-10, UI-14 |
| API-37 | `GET …/runs/{rid}/errors` | Per-item failures | RAD-07 |
| API-38 | `POST …/runs/{rid}/views/{view}` | Dashboard computation (body = view params) | DB-* |
| API-40 | `GET /projects/{pid}/events` (SSE) | Realtime stream | CUR-11 |
| API-41 | `GET /jobs?project={pid}` · `POST /jobs/{job_id}/cancel` | Jobs panel | BE-06 |
| API-50 | `GET·POST /projects/{pid}/curation/events` | History (filter by `item_id`/`case_id`) / append | CUR-02/14 |
| API-51 | `GET /projects/{pid}/curation/state` | Derived latest state | CUR-08 |
| API-52 | `GET /projects/{pid}/curation/queue?format=json\|csv` | Correction queue | CUR-09 |
| API-53 | `POST /projects/{pid}/curation/exports` | Write CUR-10 files to `exports/` | CUR-10 |
| API-54 | `POST /projects/{pid}/curation/import-v2` | Import `curation_review.csv` | CUR-13 |

## SSE event types (API-40)

| `event` | `data` |
|---|---|
| `curation.appended` | CurationEvent |
| `job.progress` | `{job_id, kind, done, total, eta_s}` |
| `job.finished` | `{job_id, kind, status, ref}` |
| `index.rebuilt` | `{import_id, n_items, n_warnings}` |
| `project.updated` | `{fields[]}` |

Clients reconnect with `Last-Event-ID`; the server replays up to 1,000 recent events per project.

## Errors (RFC 9457)

`{type, title, status, detail, instance, errors?[]}`, where `type` is a slug under `/problems/`:

| Slug | Status |
|---|---|
| `not-found` | 404 |
| `validation` | 422 (`errors[]` = field issues; also an unconvertible legacy `.npy`) |
| `path-outside-root` | 403 |
| `source-missing` | 409 |
| `format-version-unsupported` | 409 |
| `job-conflict` | 409 |
| `reviewer-required` | 428 |
| `server-busy` | 503 |
