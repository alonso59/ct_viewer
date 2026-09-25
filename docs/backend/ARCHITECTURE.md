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
├── main.py          # app factory, router mount, SPA static serving, lifespan (open locks, start job manager)
├── config.py        # env settings (OPS-03)
├── api/v1/          # thin routers only: validation + call service + map errors
│   └── health, projects, fs, imports, cases, items, volumes, curation,
│       radiomics, dashboard, jobs, events
├── core/            # errors (problem+json), ids, fsio (atomic json, jsonl append), paths (alias + guards), locks, redact (paths → alias refs, NFR-17)
├── projects/        # workspace.json + project.json service, migrations (PRJ-11), bundles (PRJ-08/09)
├── ingest/          # parsers (metadata.jsonl, phase.json, voi_catalog), normalizer, indexer, validator, full-hash job (IMP-09)
├── sources/         # adapters (metadata-v1, nifti-files), detect, identity registry, Open-mode sessions (SRC-*)
├── tasks/           # manifest registry, run protocol, builtin runtime, external queue, output registration (TSK-*)
├── imaging/         # header reader, fingerprint, npy→nii, mesh builder, file streaming
├── curation/        # event store, reducer (derived state), queue, exports
├── radiomics/       # engine protocol, pyradiomics adapter, schema builder, ibsi_map.json; runs as builtin task (RAD-13)
├── variables/       # profiling, type inference, catalog overrides, derived + external variables (VAR-*)
├── analytics/       # DuckDB queries for dashboard views (DB-*) + guided statistics and recommendations (ANA-*)
├── jobs/            # job manager, process pool, progress relay
└── events/          # in-process pub/sub → SSE fan-out
```

Outside `backend/`: `plugins/dicom/` (DCM), `plugins/analyzers/` (ANZ), `plugins/nnunet/` (external, deferred), `plugins/threshold/` (CI test plugin), each with a `task.json`. All plugins are first-party (PLG-01) with a `plugin.json`; builtin ones are installed into the image, and `PLUGINS_ROOT` is only the host copy the runner executes for `external` runtimes. `scripts/rw-runner.py` is the host runner (TSK-11). P7c adds `app/plugins/` (Wave 1: `plugin.json` loader, task ownership, Library status for API-49; new plugin routes mount under `/api/v1/plugins/{id}/`), `app/eventstore/` (Wave 5: namespaced append-only log `events/{ns}.jsonl` — `curation` keeps `curation/events.jsonl` —, reviewer/session stamps, `{ns}.appended` SSE, LWW state; used by curation and `app/labeling/`) and the view-only router (API-60).

**Layering:** `api → services (projects|sources|ingest|variables|imaging|curation|tasks|radiomics|analytics) → core`. Builtin plugins are called only through `tasks/`.
Services never import `api`. All filesystem I/O goes through `core.fsio` or `core.paths`.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| BE-01 | Run as a single Uvicorn process (`--workers 1`). CPU-heavy work runs in job worker processes (BE-06). | M |
| BE-02 | Every path access goes through `core.paths.resolve(ref)`, which enforces alias root containment and `ALLOWED_DATA_ROOTS` and rejects symlink escapes. | M |
| BE-03 | Files under `source` roots are only ever opened `rb`. A test fails if any module opens a resolved `source` path for writing. Writes to a `derived` root happen only in task code, inside the run's `output_dir` or the task's `dataset/` (ADR-0014). | M |
| BE-04 | Volumes are streamed as the original file bytes (`FileResponse`, HTTP Range, `ETag` = quick fingerprint). The server does not decode volumes for viewing, except the npy→NIfTI cache (IMP-10). | M |
| BE-05 | Writes: one `asyncio.Lock` per project serializes appends and atomic writes. On startup, take an exclusive `fcntl` lock on `WORKSPACE_ROOT/.server.lock`; refuse to start if it is held. | M |
| BE-06 | Job manager: `ProcessPoolExecutor(JOB_WORKERS)`, with job types `index`, `hash`, `thumbnail`, `radiomics`, `mesh`, `task` (builtin tasks, TSK-07), `open-convert` (SRC-09). Progress is relayed to the event bus, and state is persisted (index status, `run.json`). On restart, running jobs become `interrupted`. A `task` job has a *driver* coroutine instead of units: it owns progress and status (`waiting_for_runner` ↔ `running`, event `job.status`) and one job per `(project, task_id)` is active (TSK-12). | M |
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

A worker job runs marching cubes on `(mask_fp, label, smooth)`; the result is cached at `cache/meshes/{mask_fp}_{label}_{smooth}.{ext}`.
The output format must be one NiiVue loads natively; this is decided in the P3 spike (VW open question).
