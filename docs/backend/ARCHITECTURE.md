# Backend Architecture

Scope: stack, module layout, layering rules, concurrency, jobs, streaming.
Read when: writing any backend code.
Depends: domain/*.md, API.md, ADR-0002, ADR-0003, ADR-0006.

## Stack

| Concern | Choice |
|---|---|
| Runtime | Python 3.12, FastAPI, Uvicorn (**1 worker**), Pydantic v2, pydantic-settings |
| Imaging | nibabel (headers, npy→NIfTI), numpy, scikit-image (marching cubes) |
| Radiomics | PyRadiomics + SimpleITK + PyWavelets behind an adapter (ADR-0006) |
| Tabular / analytics | pyarrow (Parquet), DuckDB (dashboard queries), scikit-learn (PCA; UMAP optional) |
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
├── core/            # errors (problem+json), ids, fsio (atomic json, jsonl append), paths (alias + guards), locks
├── projects/        # workspace.json + project.json service, migrations (PRJ-11)
├── ingest/          # parsers (metadata.jsonl, phase.json, voi_catalog), normalizer, indexer, validator
├── imaging/         # header reader, fingerprint, npy→nii, mesh builder, file streaming
├── curation/        # event store, reducer (derived state), queue, exports
├── radiomics/       # engine protocol, pyradiomics adapter, schema builder, ibsi_map.json, runner
├── analytics/       # DuckDB queries backing dashboard views (DB-*)
├── jobs/            # job manager, process pool, progress relay
└── events/          # in-process pub/sub → SSE fan-out
```

**Layering:** `api → services (projects|ingest|imaging|curation|radiomics|analytics) → core`.
Services never import `api`. All filesystem I/O goes through `core.fsio` or `core.paths`.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| BE-01 | Run as a single Uvicorn process (`--workers 1`). CPU-heavy work runs in job worker processes (BE-06). | M |
| BE-02 | Every path access goes through `core.paths.resolve(ref)`, which enforces alias root containment and `ALLOWED_DATA_ROOTS` and rejects symlink escapes. | M |
| BE-03 | Source files are only ever opened `rb`. A test fails if `imaging/`, `ingest/` or `radiomics/` open resolved source paths for writing. | M |
| BE-04 | Volumes are streamed as the original file bytes (`FileResponse`, HTTP Range, `ETag` = quick fingerprint). The server does not decode volumes for viewing, except the npy→NIfTI cache (IMP-10). | M |
| BE-05 | Writes: one `asyncio.Lock` per project serializes appends and atomic writes. On startup, take an exclusive `fcntl` lock on `WORKSPACE_ROOT/.server.lock`; refuse to start if it is held. | M |
| BE-06 | Job manager: `ProcessPoolExecutor(JOB_WORKERS)`, with job types `index`, `hash`, `thumbnail`, `radiomics`, `mesh`. Progress is relayed to the event bus, and state is persisted (index status, `run.json`). On restart, running jobs become `interrupted`. | M |
| BE-07 | Per-project in-memory caches (index, curation state, label map) are loaded on first access and invalidated on write. An LRU keeps at most `PROJECT_CACHE_MAX` projects. | M |
| BE-08 | Errors are RFC 9457 `application/problem+json`, with stable `type` slugs (API.md §Errors). | M |
| BE-09 | Structured JSON logs to stdout; level from `LOG_LEVEL`; never log absolute patient paths at `info`. | S |
| BE-10 | OpenAPI is the contract; the frontend generates TS types from it (FE-03). CI fails on an unreviewed contract diff. | M |
| BE-11 | No outbound network calls; dependencies must not phone home. | M |
| BE-12 | The API process never holds full volumes in memory; mesh, radiomics and npy conversion run in workers. | S |
| BE-13 | Graceful shutdown: stop accepting jobs, mark running jobs `interrupted`, flush logs. | S |

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
