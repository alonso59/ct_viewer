# Backend Architecture

Scope: stack, module layout, layering rules, concurrency, jobs, streaming.
Read when: writing any backend code.
Depends: domain/*.md, API.md, ADR-0002, ADR-0003, ADR-0006, ADR-0014, ADR-0016, ADR-0018, ADR-0022.

## Stack

| Concern | Choice |
|---|---|
| Runtime | Python 3.12, FastAPI, Uvicorn (**1 worker**), Pydantic v2, pydantic-settings |
| Imaging | nibabel (headers, npy→NIfTI), numpy, scikit-image (marching cubes); pydicom + SimpleITK for DICOM (DCM-*) |
| Radiomics | PyRadiomics + SimpleITK + PyWavelets behind an adapter (ADR-0006) |
| Tabular / analytics | pyarrow (Parquet), DuckDB (dashboard queries), scikit-learn (PCA; UMAP optional), SciPy (tests, FDR; ANA-*) |
| Realtime | Server-Sent Events (sse-starlette) |
| IDs | ULID (`python-ulid`) |
| Tests | pytest, httpx, hypothesis (parsers) |

## Module layout

```text
backend/app/
├── main.py          # app factory, router mount, SPA static serving, lifespan (locks, job manager, cache budget)
├── context.py       # service container built in the lifespan (routers get it via api/v1/deps)
├── config.py        # env settings (OPS-03)
├── api/v1/          # thin routers only: validation + call service + map errors; paging helper (limits)
│   └── health, projects, fs, imports, cases, items, volumes, segmentations, sources, curation,
│       phase, labeling, annotations, variables, exports, radiomics, dashboard, tasks, plugins,
│       jobs, events, view (API-60)
├── core/            # errors (problem+json, settings issues → errors), ids, fsio (atomic json, jsonl append), paths (alias + guards), locks, logs, redact (paths → alias refs, NFR-17), cache_budget (CACHE_MAX_GB LRU), reviewer (the `X-Reviewer` stamp rule)
├── projects/        # workspace.json + project.json service, migrations (PRJ-11), bundles (PRJ-08/09)
├── ingest/          # parsers (metadata.jsonl, phase.json, voi_catalog), normalizer, indexer, validator, sidecars (IMP-15), full-hash job (IMP-09)
├── sources/         # adapters (metadata-v1, nifti-files), detect, identity registry, Open-mode sessions + service (open_service.py: open, attach, save; SRC-*)
├── layers/          # metadata layers joined onto the rows; dataset table (API-59, ADR-0020)
├── tasks/           # manifest registry, run protocol, builtin runtime, external queue, output registration (TSK-*); the service is split records → selection → jobspec → estimate → registration → driver → service
├── plugins/         # plugin.json loader, task ownership, Library status (PLG-*, API-49)
├── eventstore/      # namespaced append-only log `events/{ns}.jsonl`, reviewer/session stamps, `{ns}.appended` SSE, LWW state (ADR-0022)
├── curation/        # Curation & QC on the event store: reducer (derived state), queue, exports (CUR-*)
├── labeling/        # Labeling tables on the event store: schemas, cells, layers (LBL-*)
├── phase/           # native phase selection: events, read-time join, exports (PHS-*, ADR-0026)
├── imaging/         # header reader, fingerprint, npy→nii, mesh builder (route: api/v1/mesh.py, API-25), thumbnails, file streaming
├── radiomics/       # engine protocol, pyradiomics adapter, schema builder, ibsi_map.json; runs as builtin task (RAD-13)
├── variables/       # profiling, type inference, catalog overrides, derived + external variables (VAR-*)
├── analytics/       # DuckDB queries for dashboard views (DB-*) + guided statistics and recommendations (ANA-*)
├── jobs/            # job manager, process pool, progress relay; runs (the shared run lifecycle: `run.json` I/O, status, reconcile, cancel, resume guard, submit) for task and radiomics runs
└── events/          # in-process pub/sub → SSE fan-out
```

Outside `backend/`: task plugins `plugins/dicom/` (DCM), `plugins/analyzers/` (ANZ), `plugins/threshold/` (CI test plugin) with their `task*.json` manifests; `plugins/nnunet/` and `plugins/voi/` are pending manifests (PLG-09); `plugins/radiomics/` (the builtin `radiomics.pyradiomics` task in `app/radiomics/`), `plugins/curation/`, `plugins/labeling/`, `plugins/dashboard/` and the packs `plugins/ccrcc/`, `plugins/generic-ct/` contribute UI, routes or pack data only. All plugins are first-party (PLG-01) with a `plugin.json`; builtin ones are installed into the image, and `PLUGINS_ROOT` is only the host copy the runner executes for `external` runtimes. `scripts/rw-runner.py` is the host runner (TSK-11).

**Layering:** `api → services (projects|sources|ingest|layers|variables|imaging|eventstore|curation|labeling|phase|tasks|plugins|radiomics|analytics) → core`. Builtin plugins are called only through `tasks/`. `tests/test_layering.py` checks that no service imports `api` and that no new two-way package dependency appears (the ones that exist are listed there, to be removed by moving shared models down, AUD-A6-10).
Services never import `api`. All filesystem I/O goes through `core.fsio` or `core.paths`.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| BE-01 | Run as a single Uvicorn process (`--workers 1`). CPU-heavy work runs in job worker processes (BE-06). | M |
| BE-02 | Every path access goes through `core.paths.resolve(ref)`, which enforces alias root containment and `ALLOWED_DATA_ROOTS` and rejects symlink escapes. | M |
| BE-03 | Files under `source` roots are only ever opened `rb`. A test fails if any module opens a resolved `source` path for writing. Writes to a `derived` root happen only in task code, inside the run's `output_dir` or the task's `dataset/` (ADR-0014). | M |
| BE-04 | Volumes are streamed as the original file bytes (`FileResponse`, HTTP Range, `ETag` = quick fingerprint). The server does not decode volumes for viewing, except the npy→NIfTI cache (IMP-10). | M |
| BE-05 | Writes: one `asyncio.Lock` per project serializes appends and atomic writes. On startup, take an exclusive `fcntl` lock on `WORKSPACE_ROOT/.server.lock`; refuse to start if it is held. | M |
| BE-06 | Job manager: `ProcessPoolExecutor(JOB_WORKERS)`, with job types `index`, `hash`, `thumbnail`, `radiomics`, `mesh`, `task` (builtin tasks, TSK-07), `open-convert` (SRC-09). Progress is relayed to the event bus, and state is persisted (index status, `run.json`; task and radiomics runs share one run lifecycle, `jobs/runs.py`, AUD-A6-06). On restart, running jobs become `interrupted`. A `task` job has a *driver* coroutine instead of units: it owns progress and status (`waiting_for_runner` ↔ `running`, event `job.status`) and one job per `(project, task_id)` is active (TSK-12). | M |
| BE-07 | Per-project in-memory caches (index, curation state, label map) are loaded on first access and invalidated on write. An LRU keeps at most `PROJECT_CACHE_MAX` projects. | M |
| BE-08 | Errors are RFC 9457 `application/problem+json`, with stable `type` slugs (API.md §Errors). | M |
| BE-09 | Structured JSON logs to stdout; level from `LOG_LEVEL`; never log absolute patient paths at `info`. | S |
| BE-10 | OpenAPI is the contract; the frontend generates TS types from it (FE-03). CI fails on an unreviewed contract diff. | M |
| BE-11 | No outbound network calls; dependencies must not phone home. | M |
| BE-12 | The API process never holds full volumes in memory; mesh, radiomics and npy conversion run in workers. | S |
| BE-13 | Graceful shutdown: stop accepting jobs, mark running jobs `interrupted`, flush logs. | S |
| BE-14 | External tasks: the API process writes `queue/{job_id}/job.json` and `cancel`, tails `progress.jsonl` and relays it as job events; it never starts external processes (TSK-11). A job with no fresh runner heartbeat is `waiting_for_runner`. | M |
| BE-15 | Startup refuses overlapping `ALLOWED_DATA_ROOTS` / `ALLOWED_DERIVED_ROOTS` (`roots-overlap`, OPS-12). | M |

## Concurrency model

```text
browser A ─┐                       ┌─ worker 1 (radiomics item k)
browser B ─┼─ HTTP/SSE ─ API proc ─┼─ worker 2 (mesh)
browser C ─┘   (single writer)     └─ …  → writes only inside runs/{run_id}/ or cache/
```

- Multi-user safety comes from the single-writer API process, not from file locking between processes.
- NFS/GPFS caveat: `fcntl` may be unreliable. Put `WORKSPACE_ROOT` on local disk when possible (OPS-06).

## Mesh generation

A worker job runs marching cubes on `(mask_fp, label, smooth)`; the result is cached at `cache/meshes/{mask_fp}_{label}_{smooth}.mz3`.
The format is gzip MZ3 (VIEWER §Decisions).
