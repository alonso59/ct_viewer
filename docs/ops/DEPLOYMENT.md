# Deployment

Scope: deployment options (native, HPC), the test image, configuration, upgrades.
Read when: deploying, building the test image, or changing env vars.
Depends: ADR-0014, ADR-0016, ADR-0043, ADR-0051, backend/ARCHITECTURE.md, domain/TASKS.md.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| OPS-01 | One image, `radiology-workbench:{semver}`, built in multiple stages (`node:22-slim` → `python:3.12-slim`), serves API and SPA on one port. | M |
| OPS-02 | The image runs under Docker with no init system, no capabilities, no privileged ports, and no dependence on a specific UID. | M |
| OPS-03 | All configuration comes from env vars (§Config). The frontend receives its runtime config through API-01. | M |
| OPS-04 | `ALLOWED_DATA_ROOTS` limits browsing and resolution (BE-02). An empty value refuses to start in container mode. | M |
| OPS-05 | Mirror-mount convention: mount data at the **same path** inside the container as on the host, so aliases and exported absolute paths match. | S |
| OPS-06 | `WORKSPACE_ROOT` must be writable and preferably on local disk (the lock caveat in BE-05). | M |
| OPS-07 | Healthcheck: `GET /api/v1/health`. | M |
| OPS-08 | Image size ≤ 1.5 GB (NFR-10). | S |
| OPS-09 | Retired (ADR-0051): the udocker run script matched the compose definition. | — |
| OPS-10 | Upgrade = new release + restart; project `format_version` migrations run on open (PRJ-11). | M |
| OPS-11 | Derived roots are **writable** folders, separate from the data roots, listed in `ALLOWED_DERIVED_ROOTS` (ADR-0014). | M |
| OPS-12 | Startup refuses a derived root that overlaps a data root, or vice versa (`roots-overlap`). | M |
| OPS-13 | External tasks run through `scripts/rw-runner.py` on the host, in the plugin's own environment; the workspace, the data and the derived roots must be visible to it at the same paths as to the app (TSK-11). | M |
| OPS-15 | Optional `MANAGED_DERIVED_ROOT` must equal the sibling `derived/` of `WORKSPACE_ROOT`. Only that explicitly managed root may overlap an allowed source browsing root; PRJ-19 independently controls dataset-local outputs. | M |
| OPS-14 | Builtin tasks (converter, analyzers, radiomics) stay in the image within OPS-08; heavy plugins (torch, GPU) never go into the image. | M |
| OPS-16 | Production GPU tasks require an accepted execution backend with verified attempt ownership/whole-tree cleanup and bounded CPU, RAM, tasks and runtime. Capabilities are per deployment under ADR-0034; local/server execution requires the effective user-cgroup and Landlock/seccomp gate. Device visibility/reservations are cooperative; quota and logout persistence are reported separately. | M |
| OPS-17 | Runner diagnostics inspect capabilities without changing host policy or starting inference. Reports distinguish observed prerequisites, verified enforcement and advisory/unavailable controls. Never install system tools, enable lingering or change driver/GPU policy as a diagnostic side effect. | M |
| OPS-18 | Operator-owned private deployment configuration selects `local`, `server` or `slurm`, an existing Python/conda environment, approved roots, resource limits and GPU pool. No browser executable, shell text, host paths or scheduler flags. CPU quota is at most 12 and each attempt uses at most four approved GPUs. | M |
| OPS-19 | Where the accepted backend uses an unprivileged sandbox, verify write/network effects and inheritance before GPU admission. Sandbox installation failure refuses launch; conda, torchrun, and visibility variables never certify OS isolation. Explicit runtime filesystem/device allowances and syscall limitations remain documented in domain/SEGMENTATION_RUNTIMES.md. | M |
| OPS-20 | SLURM execution is a separate deployment acceptance gate: approved scheduler resources, shared filesystem/environment visibility, durable scheduler identity and cleanup reconciliation. Configuration validation or fake scheduler tests do not certify an inaccessible cluster. | M |
| OPS-21 | `scripts/ctflow.py` (CTF-18) runs with any Python 3 on the host, standard library only, nothing installed (R4). It reaches the app at `http://127.0.0.1:$PORT` with `PORT` from an env file (`RW_ENV`, default the repository's `.env`; for a native deployment set `RW_ENV` to its `config/runtime.env`), or `--url`/`CTFLOW_URL`. Make it `ctflow` with a link on `PATH`, e.g. `ln -s "$PWD/scripts/ctflow.py" ~/.local/bin/ctflow`. It stores only `~/.config/ctflow/` (reviewer name, history without absolute paths). | S |
| OPS-22 | Native deployment: `scripts/rw-native.py` runs a frozen release from a conda environment pinned by the lock, as a systemd user service, without sudo. It smoke-tests a release before any restart, refuses to switch while work or a GPU allocation is active, verifies health, projects and the served web app, and restores the previous release on failure. Node is used to build only. | S |
| OPS-23 | HPC deployment: the app and a light runner run on an approved service or submission node, in a native conda environment (§Native); never compute on a login node. Heavy work runs only in scheduler allocations. GPU segmentation there needs OPS-20. Accepted only on a real cluster. | S |
| OPS-24 | `rw-dicom` under a scheduler: `--state-dir` keeps the inventory on node-local disk while the output stays on shared storage, and losing it costs only a new header scan; the default memory budget is half of the job's allocation; SIGTERM stops dispatch and a new job resumes. The output's file system must support `flock`. | S |
| OPS-25 | `scripts/rw-mcp.py` (CTF-24) runs with any Python 3, standard library only (R4), and resolves the app URL and reviewer like OPS-21. Register it with an MCP client as a stdio server, e.g. `claude mcp add rw -- python3 scripts/rw-mcp.py`. | S |

## Options (ADR-0043)

| Option | Use when | Section |
|---|---|---|
| Native | One server or workstation with conda, no sudo, performance matters | §Native |
| HPC | SLURM cluster | §HPC |

The OCI image is a test artifact that CI builds and checks (§Test image), not a deployment (ADR-0051).

## Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `WORKSPACE_ROOT` | `/workspace` | Projects directory (rw) |
| `ALLOWED_DATA_ROOTS` | *(required in container)* | `:`-separated absolute dirs that data may come from |
| `HOST` | `0.0.0.0` in the image | Bind address; a native deployment binds `127.0.0.1` |
| `PORT` | `8000` | Must be ≥ 1024 |
| `PUBLIC_BASE_URL` | `http://localhost:{PORT}` | Used in share links (PRJ-03) |
| `JOB_WORKERS` | `2` | Worker processes (BE-06) |
| `PROJECT_CACHE_MAX` | `4` | Projects kept in memory (BE-07) |
| `ARROW_DEFAULT_MEMORY_POOL` | `system` in the image | Arrow uses the system allocator to keep metadata-query idle RSS within NFR-08. Native launches must export this library setting before starting Python. |
| `CACHE_MAX_GB` | `20` | One LRU budget for all disposable caches together: Open-mode `.scratch/open/` and every active project's `cache/` meshes, thumbnails and npy→NIfTI files (`core/cache_budget.py`). Swept after cache writes and every 10 min; least recently used first; entries used in the last minute and anything outside those folders are never touched (R1, PRJ-10). An evicted file is rebuilt on the next use |
| `VIEWER_MAX_LOADED` | `3` | Loaded viewer tabs (VW-14) |
| `LOG_LEVEL` | `info` | |
| `CONTAINER_MODE` | `1` in the image | With `1`, an empty `ALLOWED_DATA_ROOTS` refuses to start (OPS-04) |
| `STATIC_ROOT` | `/app/static` | SPA build |
| `MANAGED_DERIVED_ROOT` | *(unset)* | OPS-15: persistent global fallback when datasets are browsable anywhere under HOME |
| `ALLOWED_DERIVED_ROOTS` | *(empty = no derived root; tasks that write volumes are unavailable)* | `:`-separated absolute writable dirs for `derived` roots (OPS-11) |
| `PLUGINS_ROOT` | *(empty)* | Read-only dir of external task manifests (TSK-01); the runner uses the same dir on the host |
| `BUILTIN_PLUGINS_ROOT` | `plugins/` next to `backend/` (`/app/plugins` in the image) | Builtin task plugins (converter, analyzers); normally left unset |
| `DICOM_MEMORY_MB` | *(unset: headers/Estimate only)* | Explicit pixel-worker virtual-address ceiling, 512..1,048,576 MiB; with `DICOM_WORKERS` > 1 it is the total for all workers. Per-series admission includes current address space, native-library reserve and conservative working buffers. An oversized series waits with a remedy; raise the declared budget and resume after restart. No free-host-memory inference. |
| `HOST_ALLOCATION_ROOT` | *(development: workspace-private pool)* | In container mode, pixel work requires an explicit canonical, private, writable pool visible to all participating app workspaces and equal to the host runner's `state_dir`. It must not overlap a source root, except inside a dot folder, which discovery and browsing never enter. Same Unix identity; ownership/mode 0700 enforced. Prefer a private directory under an already shared writable mount; the path need not be spelled identically across bind mounts, but device/inode identity must match. |
| `DICOM_CPU_THREADS` | `4` | 1..12; plus `JOB_WORKERS` must be ≤12. Owned workers restrict affinity to at most this many available CPUs, header threads to at most four and numerical/ITK threads to one. DICOM and configured GPU attempts serialize through the participating pool. These are application budgets, not host-wide control of other users. |
| `DICOM_WORKERS` | `1` | 1..`DICOM_CPU_THREADS`; series a conversion converts in parallel inside its owned process group (DCM-32). Workers share `DICOM_MEMORY_MB` as one total: a series starts only while every worker's baseline plus the running series' estimated working sets fit. Raise it after measuring on the host (DICOM_STANDALONE_TEST_PLAN.md §Evidence). |
| `DICOM_HEADER_MB` | `8` | 1..64; header read cap in owned DICOM workers. Compatibility-adapter/global header-budget consistency remains in DICOM_JOB_PLAN.md. |
| `DICOM_INVENTORY_MB` | `512` | Per-inventory storage envelope, 1..16,384 MiB. SQLite pages use at most one quarter, reserving space for WAL/index/transactions. Batches checkpoint the WAL; a pinned reader stops further growth. The inventory costs about 300 B per file for typical multi-slice series (a single-slice series per folder costs about 1.7 KB); size the budget from the file count, e.g. 2.4 M files need ~0.8 GB of SQLite pages, so a 4 GiB envelope. Discovery counts the source first and, after 5,000 new files, projects the final inventory size; a projection above 90% of the cap raises a warning without stopping the scan. Reaching the cap reports a partial inventory and preserves prior batches; increase this budget and resume the same operation. Lowering it never deletes existing history. The aggregate ceiling below additionally bounds all retained operation databases. |
| `DICOM_INVENTORY_TOTAL_MB` | `2048` | Aggregate retained SQLite inventory budget, 1..1,048,576 MiB, including WAL/shared-memory overhead. Admission computes the sole writer's remaining allowance under the execution lock. Exhaustion refuses further growth; recoverable history is never evicted to make room. Increase the ceiling and resume when needed. |
| `DICOM_BATCH_SIZE` | `64` | 1..512 files between durable inventory commits. Owned discovery and Estimate use the configured value; cancellation preserves completed batches and never advertises a partial series as complete. |
| `DICOM_CLEANUP_SECONDS` | `28` | 0.1..28 cooperative grace, leaving time for owned-process escalation and exit verification within the healthy-host 30-second target. Unknown cleanup retains the allocation. |

DICOM resource coordination (BE-16, ADR-0047): DICOM conversion no longer takes the host allocation pool lease, so it runs beside a segmentation job instead of waiting for it. Its own `DICOM_CPU_THREADS` and `DICOM_MEMORY_MB` budgets still apply, and one DICOM attempt at a time holds the workspace admission lease. The API still writes `dicom-resources.json` and a configured runner still verifies the pool identity before new GPU attempts. Never delete a pool lease to force admission. Native Open-mode conversion uses the same executor. A completed/queued-without-worker job releases its slot; uncertain cleanup preserves job/lease evidence. Cross-PID-namespace recovery requires independent cleanup proof and remains an image/restart acceptance gate; a reused visible PID cannot certify an old container's writer stopped.

`DICOM_RETENTION_DAYS` (30) expires completed, cleanup-verified inventory and paged-plan caches before new source work. Running, interrupted, failed/cancelled, unfinished import drafts and unclosed Open sessions remain protected regardless of age. Expired operations retain their records and a durable expiry marker; accessing expired inventory offers a fresh source operation. Source files, committed datasets, registration history and conversion journals are never deleted by this sweep.

## Native (conda, no sudo)

```bash
python3 scripts/rw-native.py prepare [--python-env rw-server] [--node-env rwnode]  # release + smoke, nothing restarts
python3 scripts/rw-native.py deploy native-YYYYMMDD-abcdefg                       # OPS-22, restores on failure
python3 scripts/rw-native.py rollback                                             # the release before the last deploy
```

Needs conda, a C compiler for PyRadiomics, and `npm` on `PATH` or a conda environment with Node (`conda create -n rwnode -c conda-forge nodejs=22`). `deploy` keeps `config/runtime.env` and adds `config/native.env` (`CONTAINER_MODE=0`, release paths, the real `HOST_ALLOCATION_ROOT`). `prepare` builds the commit at `HEAD`; uncommitted changes never ship.

## HPC (SLURM)

Run the app per OPS-23 as in §Native on the service node. Convert in a job (OPS-24), not through the app:

```bash
#!/bin/bash
#SBATCH --cpus-per-task=16 --mem=64G --time=24:00:00 --signal=B:TERM@300
exec rw-dicom convert /lustre/project/dicom /lustre/project/out --workers "$SLURM_CPUS_PER_TASK" \
  --state-dir "${SLURM_TMPDIR:-/tmp/rw-$SLURM_JOB_ID}"
```

Submit the same script again to resume, on any node. Installation: `plugins/dicom/README.md`. Several jobs: one output folder each. Site policy (partition, account, QOS) and scratch location are the operator's; this path is not yet accepted on a real cluster.

## Test image (Docker)

`make image` builds the image and `make container-smoke` checks it (TST-10); CI does both on every push. Nothing deploys it.

## Persistent local user service

P7g GPU admission follows OPS-16..20 and ADR-0034. Unconfigured GPU execution stays unavailable; an operator-configured local/server backend must pass effective checks before advertising tasks. Setup and trust/limit details have one owner: `../domain/SEGMENTATION_RUNTIMES.md`. `--preflight` without a deployment retains the original strict prerequisite report for diagnostics.
`RW_RUNNER_STORAGE_ROOT` and `RW_RUNNER_STORAGE_MAX_BYTES` are host-diagnostic inputs for an independently bounded, privately owned mounted filesystem; they do not configure a quota. `/`, symlinks and group/world-writable storage are refused. A free-space check is not an enforced budget.
For explicitly authorized, GPU-free effect testing, use `backend`'s `tools.runner_host_probe --run`; details/results belong to `SEGMENTATION_JOB_TEST_PLAN.md`. It never enables lingering, installs tools, changes driver policy or touches input/model roots.

An installation lives in `$HOME/.local/share/radiology-workbench/`, independently
of the development checkout: `releases/` (frozen native releases), `workspace/` (registry),
`derived/` (global conversion fallback), and `config/` (`runtime.env`, `native.env`,
`release.json`). A release carries the compiled SPA, backend and builtin plugins.
Dataset locations are chosen through PRJ-19 inside the explicitly
authorized browsing root. HOME-wide access requires explicit owner authorization;
it is not the default source policy. Bind only `127.0.0.1`; the persistent
Web UI uses port **5180** for both the compiled frontend and API. Set `PORT` and
`PUBLIC_BASE_URL` together in `config/runtime.env` and restart the user service
to change it. Development Vite keeps its separate 5173 convention (DEV_ENV.md).

Before an upgrade, drain work and back up workspace metadata and release configuration.
Runs that cannot cross an upgrade must finish first or start again afterwards:
- nnU-Net runs paused or interrupted before the `segment` command: CTFLOW.md §Implementation notes (shipped command names), including the host runner's `PLUGINS_ROOT` copy.
- DICOM conversions pinned before ADR-0042: resume refuses them, so finish them on the old release.
A release predating ADR-0038 does not preserve per-label exclusions when it writes project metadata;
rolling back to it requires the compatible pre-upgrade metadata snapshot after verified cleanup.

`radiology-workbench.service` under `$HOME/.config/systemd/user/` runs that release,
uses `Restart=always`, and is enabled for the user’s session. With user lingering
disabled it starts at login rather than running independently of all sessions.

```bash
systemctl --user status radiology-workbench
systemctl --user restart radiology-workbench
systemctl --user stop radiology-workbench
journalctl --user -u radiology-workbench -n 100
```

## Electron (phase P8)

The Electron build is a thin shell that loads `PUBLIC_BASE_URL` (a local or forwarded app). It adds native folder dialogs through a preload bridge. The backend packaging is unchanged (ADR-0001).

## Implementation notes

- Image: 897 MB uncompressed on linux/arm64 (the build stage drops bundled `tests/` folders, pip, pyarrow headers and SimpleITK debug symbols; the web stage runs `vite build` only, type checking is a `make check` gate); 935 MB on linux/amd64 (277 MB compressed, `docker save | gzip` 273 MB); cross-platform builds on an Apple Silicon Mac under colima need `binfmt: true`; the build only succeeds if PyRadiomics passes the IBSI phantom smoke inside the image. Measure size with `du` of the rootfs: under the containerd store, `docker image inspect .Size` is the compressed size.
- `app/main.py` serves the SPA when `STATIC_ROOT/index.html` exists (`/assets` static, `index.html` fallback, `/api/*` never falls back). The entry point `scripts/container_app.py` only validates the config (clean OPS-04 refusal) and runs uvicorn.
- Version: the single source is `backend/pyproject.toml` (`{version}` above). `make image` tags it (`tests/test_version.py`).
- colima on the dev Mac has no host mounts by default (`$HOME` contains a space), so bind mounts appear empty; start it with `colima start --mount '<path>:w'` to use real data under Docker.
- If Docker Desktop is not running, a CLI config with `credsStore: desktop` makes pulls hang; use a `DOCKER_CONFIG` without a creds store.
