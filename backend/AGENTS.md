# backend/ map

Python 3.12 · FastAPI · Pydantic v2. Package `app/`, dev tools `tools/`, tests `tests/`.

**Owns** (per-package detail: `docs/backend/ARCHITECTURE.md` §Module layout)
- `api/v1/`: thin routers (validate → call service → map errors).
- `core/`: every path resolution and file write (`paths`, `fsio`), problem+json errors, locks, redaction of host paths.
- Data in: `projects`, `sources` (adapters, Open mode), `ingest` (imports, indexing, manual segmentation manifests; SRC-20), `layers`.
- Review state: `eventstore` → `curation`, `labeling`, `phase`.
- Compute: `tasks` (with `plugins` loader and `selection`), `jobs`, `radiomics`, `imaging`, `events` (SSE).
- Analysis: `variables`, `analytics`.
- `tools/`: OpenAPI snapshot, mock recorder, fixture generator, acceptance and environment checks.

**Entry points:** `app/main.py` (factory, lifespan), `app/context.py` (service container), `app/config.py` (env settings, OPS-03).

**Boundaries**
- `api → services → core`; services never import `api` (`tests/test_layering.py`). Plugins are reached only through `tasks/`.
- Paths only via `core.paths`, writes via `core.fsio`; `source` files opened `rb` only (BE-02/03, R1).
- Heavy work (radiomics, meshes, thumbnails, npy conversion) runs in job workers, never in the API process (BE-12). No outbound network (BE-11).

**Tests:** `tests/test_<area>*.py`, parallel-safe (TESTING.md §Rules); `host_tests/` are opt-in host effects (`make test-host`). Gate selection: skill `rw-verify`.
`tests/dicom_browser_server.py` starts the private real API for native DICOM browser recovery tests.
`tests/test_task_attempt_fencing.py` covers durable external dispatch, competing resumes and obsolete task callbacks.
`scripts/dicom-namespace-smoke.py` checks the product image's owned DICOM dispatch, cancellation and recovery across two Docker PID namespaces in CI.

**Change together**
- Endpoint or response model → skill `rw-api-change`.
- QC codes: `app/ingest/codes.py` is the single source; keep it equal to `docs/domain/INPUT_METADATA.md`.
- Env var: `app/config.py` ↔ `docs/ops/DEPLOYMENT.md` §Config ↔ `.env.example`.
- Task or runner behavior → `plugins/AGENTS.md`.

**Read more:** the owning domain doc (`docs/INDEX.md`); endpoints and error slugs `docs/backend/API.md`; jobs and concurrency `docs/backend/ARCHITECTURE.md`.
