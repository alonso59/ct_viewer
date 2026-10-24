# Deployment

Scope: OCI image, Docker (local), udocker (remote, no sudo), configuration, upgrades.
Read when: building or running the image, or changing env vars.
Depends: ADR-0007, ADR-0014, ADR-0016, backend/ARCHITECTURE.md, domain/TASKS.md.

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| OPS-01 | One image, `radiology-workbench:{semver}`, built in multiple stages (`node:22-slim` → `python:3.12-slim`), serves API and SPA on one port. | M |
| OPS-02 | The image runs unchanged under Docker and udocker: no init system, no capabilities, no privileged ports, and no dependence on a specific UID. | M |
| OPS-03 | All configuration comes from env vars (§Config). The frontend receives its runtime config through API-01. | M |
| OPS-04 | `ALLOWED_DATA_ROOTS` limits browsing and resolution (BE-02). An empty value refuses to start in container mode. | M |
| OPS-05 | Mirror-mount convention: mount data at the **same path** inside the container as on the host, so aliases and exported absolute paths match. | S |
| OPS-06 | `WORKSPACE_ROOT` must be writable and preferably on local disk (the lock caveat in BE-05). | M |
| OPS-07 | Healthcheck: `GET /api/v1/health`. | M |
| OPS-08 | Image size ≤ 1.5 GB (NFR-10). | S |
| OPS-09 | `scripts/udocker-run.sh` reads the same `.env` file as compose and runs the equivalent command. | M |
| OPS-10 | Upgrade = new image + restart; project `format_version` migrations run on open (PRJ-11). | M |
| OPS-11 | Derived roots are a third, **writable**, mirror-mounted mount (`DERIVED_HOST`), listed in `ALLOWED_DERIVED_ROOTS` (ADR-0014). | M |
| OPS-12 | Startup refuses a derived root that overlaps a data root, or vice versa (`roots-overlap`). | M |
| OPS-13 | External tasks run through `scripts/rw-runner.py` on the host (Docker or udocker alike), in the plugin's own environment; `WORKSPACE_HOST`, the data and the derived roots must be visible to it at the same paths as in the container, except the workspace, which the runner addresses by its host path (TSK-11). | M |
| OPS-15 | Optional `MANAGED_DERIVED_ROOT` must equal the sibling `derived/` of `WORKSPACE_ROOT`. Only that explicitly managed root may overlap an allowed source browsing root; PRJ-19 independently controls dataset-local outputs. | M |
| OPS-14 | Builtin tasks (converter, analyzers, radiomics) stay in the image within OPS-08; heavy plugins (torch, GPU) never go into the image. | M |
| OPS-16 | Production GPU tasks require an accepted execution backend with verified attempt ownership/whole-tree cleanup and bounded CPU, RAM, tasks and runtime. Capabilities are per deployment under ADR-0034; local/server execution requires the effective user-cgroup and Landlock/seccomp gate. Device visibility/reservations are cooperative; quota and logout persistence are reported separately. | M |
| OPS-17 | Runner diagnostics inspect capabilities without changing host policy or starting inference. Reports distinguish observed prerequisites, verified enforcement and advisory/unavailable controls. Never install system tools, enable lingering or change driver/GPU policy as a diagnostic side effect. | M |
| OPS-18 | Operator-owned private deployment configuration selects `local`, `server` or future `slurm`, an existing Python/conda environment, approved roots, resource limits and GPU pool. No browser executable, shell text, host paths or scheduler flags. CPU quota is at most 12 and each attempt uses at most four approved GPUs. | M |
| OPS-19 | Where the accepted backend uses an unprivileged sandbox, verify write/network effects and inheritance before GPU admission. Sandbox installation failure refuses launch; conda, torchrun, visibility variables and udocker never certify OS isolation. Explicit runtime filesystem/device allowances and syscall limitations remain documented in domain/SEGMENTATION_RUNTIMES.md. | M |
| OPS-20 | SLURM execution is a separate deployment acceptance gate: approved scheduler resources, shared filesystem/environment visibility, durable scheduler identity and cleanup reconciliation. Configuration validation or fake scheduler tests do not certify an inaccessible cluster. | M |

## Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `WORKSPACE_ROOT` | `/workspace` | Projects directory (rw) |
| `ALLOWED_DATA_ROOTS` | *(required in container)* | `:`-separated absolute dirs that data may come from |
| `HOST` | `0.0.0.0` in Docker, `127.0.0.1` in udocker | Bind address (see udocker notes) |
| `PORT` | `8000` | Must be ≥ 1024 |
| `PUBLIC_BASE_URL` | `http://localhost:{PORT}` | Used in share links (PRJ-03) |
| `JOB_WORKERS` | `2` | Worker processes (BE-06) |
| `PROJECT_CACHE_MAX` | `4` | Projects kept in memory (BE-07) |
| `CACHE_MAX_GB` | `20` | One LRU budget for all disposable caches together: Open-mode `.scratch/open/` and every active project's `cache/` meshes, thumbnails and npy→NIfTI files (`core/cache_budget.py`). Swept after cache writes and every 10 min; least recently used first; entries used in the last minute and anything outside those folders are never touched (R1, PRJ-10). An evicted file is rebuilt on the next use |
| `VIEWER_MAX_LOADED` | `3` | Loaded viewer tabs (VW-14) |
| `LOG_LEVEL` | `info` | |
| `CONTAINER_MODE` | `1` in the image | With `1`, an empty `ALLOWED_DATA_ROOTS` refuses to start (OPS-04) |
| `STATIC_ROOT` | `/app/static` | SPA build |
| `MANAGED_DERIVED_ROOT` | *(unset)* | OPS-15: persistent global fallback when datasets are browsable anywhere under HOME |
| `ALLOWED_DERIVED_ROOTS` | *(empty = no derived root; tasks that write volumes are unavailable)* | `:`-separated absolute writable dirs for `derived` roots (OPS-11) |
| `PLUGINS_ROOT` | *(empty)* | Read-only dir of external task manifests (TSK-01); the runner uses the same dir on the host |
| `BUILTIN_PLUGINS_ROOT` | `plugins/` next to `backend/` (`/app/plugins` in the image) | Builtin task plugins (converter, analyzers); normally left unset |
| `DICOM_MEMORY_MB` | *(unset: headers/Estimate only)* | Explicit pixel-worker virtual-address ceiling, 512..1,048,576 MiB. Per-series admission includes current address space, native-library reserve and conservative working buffers. An oversized series waits with a remedy; raise the declared budget and resume after restart. No free-host-memory inference. |
| `HOST_ALLOCATION_ROOT` | *(development: workspace-private pool)* | In container mode, pixel work requires an explicit canonical, private, writable pool visible to all participating app workspaces and equal to the host runner's `state_dir`. Same Unix identity; ownership/mode 0700 enforced. Prefer a private directory under an already shared writable mount; the path need not be spelled identically across bind mounts, but device/inode identity must match. |
| `DICOM_CPU_THREADS` | `4` | 1..12; plus `JOB_WORKERS` must be ≤12. Owned workers restrict affinity to at most this many available CPUs, header threads to at most four and numerical/ITK threads to one. DICOM and configured GPU attempts serialize through the participating pool. These are application budgets, not host-wide control of other users. |
| `DICOM_HEADER_MB` | `8` | 1..64; header read cap in owned DICOM workers. Compatibility-adapter/global header-budget consistency remains in DICOM_JOB_PLAN.md. |
| `DICOM_INVENTORY_MB` | `512` | Per-inventory storage envelope, 1..16,384 MiB. SQLite pages use at most one quarter, reserving space for WAL/index/transactions. Batches checkpoint the WAL; a pinned reader stops further growth. Reaching the cap reports a partial inventory and preserves prior batches; increase this budget and resume the same operation. Lowering it never deletes existing history. It is not yet a global cache quota. |
| `DICOM_BATCH_SIZE` | `64` | 1..512 files between durable inventory commits. Owned discovery and Estimate use the configured value; cancellation preserves completed batches and never advertises a partial series as complete. |
| `DICOM_CLEANUP_SECONDS` | `28` | 0.1..28 cooperative grace, leaving time for owned-process escalation and exit verification within the healthy-host 30-second target. Unknown cleanup retains the allocation. |

DICOM resource coordination (BE-16): the API writes `dicom-resources.json` under the workspace. A configured runner verifies the pool identity before new GPU attempts and reports it in its heartbeat. A mismatch/older unverified runner prevents DICOM admission; a DICOM lease has an empty GPU list and is never adopted or signalled by the host supervisor. Configure the same pool before rollout and drain/reconcile prior allocations; never delete a lease to force admission. Native Open-mode conversion uses the same executor. A completed/queued-without-worker job releases its slot; uncertain cleanup preserves job/lease evidence. Cross-PID-namespace recovery requires independent cleanup proof and remains an image/restart acceptance gate; a reused visible PID cannot certify an old container's writer stopped.

`DICOM_RETENTION_DAYS` (30) is validated but retention/aggregate-cache eviction remains pending. Active/recoverable inventories and checkpoints are retained; no age-based deletion is currently performed.


## Quick start (`./rw`)

`./rw` (repo root, bash, no sudo) is the one launcher for both runtimes. It uses Docker when `docker compose` (v2) reaches a daemon, else udocker (`udocker` on `PATH` or the bundled `./udocker.py`); `RW_RUNTIME=docker|udocker` forces one. `./rw help` lists the options.

```bash
./rw init                 # writes .env from .env.example; asks DATA_HOST, optional DERIVED_HOST, PORT
./rw up                   # starts in the background, waits for /api/v1/health, prints the URL
./rw status | logs [-f] | stop
./rw update rw-{version}.tar   # load a new image (docker save) and restart; ./rw update REF pulls
./rw smoke                # TST-10 against the running app (adds one smoke project to the workspace)
```

`make up` / `make down` / `make logs` wrap it. Every command is idempotent (`init` never overwrites `.env` without `--force`; `up` on a healthy app only prints the URL). On a remote server, open the printed port through the VS Code Ports view (AGENTS R7). Under Docker, `./rw up` is `docker compose up -d` (compose builds the image when it is missing); under udocker it runs `scripts/udocker-run.sh` in the background (pid and log in `.rw/`, git-ignored).

## Docker (local machine)

`docker-compose.yml` is the Docker run definition (plain compose v2, R3): `.env` as `env_file`, the container-side paths fixed in `environment:`, the mirror mounts of OPS-05/OPS-11 and `127.0.0.1:${PORT}` published. `tests/test_udocker_run.py` checks that `udocker-run.sh` resolves the same environment and volumes.

**Source recycling:** Docker keeps the source mount `ro` by default. To enable CUR-16 on imported source datasets, set `DATA_MOUNT_MODE=rw` in `.env` and recreate the container. Ordinary source operations still follow R1. udocker relies on the application’s path guards and explicit confirmation.

**Derived roots (owner decision 2026-09-27):** the default stays `./derived` (next to `.env`) mounted at `/derived` for both compose and udocker, so `ALLOWED_DERIVED_ROOTS=/derived`; set `DERIVED_HOST` to an absolute path to mirror-mount it instead. The external runner (nnU-Net, OPS-13) is out of scope for this default: it lives on the remote server where the repo is installed, and is configured there.

## udocker (remote server, no sudo)

udocker cannot build images. Build with Docker elsewhere (`make image PLATFORM=linux/amd64` for an amd64 server), then transfer the tar:

```bash
make image-tar                 # on the build machine: docker save -> build/rw-{version}.tar
./rw update rw-{version}.tar   # on the server: normalize + udocker load (see the first note)
./rw init && ./rw up           # runs scripts/udocker-run.sh (creates the container `rw` on first run)
```

| Note | Consequence |
|---|---|
| `docker save` from the containerd image store writes an OCI-layout tar; BuildKit nests the image in a second index (provenance attestation) | udocker 1.3 cannot follow that index and names OCI images by a random hash. `./rw update` first runs `scripts/oci_tar_normalize.py` (flat index, attestations dropped, blobs unchanged; needs free disk for one tar copy), then `udocker load -i FILE radiology-workbench` |
| udocker needs `curl` (or pycurl) even offline, and fetches its engine tarball (proot, patchelf) on first use | Most servers have `curl`. Offline: copy `udocker-englib-*.tar.gz` and set `UDOCKER_TARBALL=/path/to/it` before the first run |
| udocker does not isolate the network: the process binds host ports directly | Use `HOST=127.0.0.1` and let VS Code forward the port; `-p` mapping is not relied on |
| Mount `:ro` is not guaranteed under every execution mode | Source safety is enforced by the app (BE-02/03), not the mount |
| Execution mode: `P1` (proot, default) or `F3` (fakechroot, set `UDOCKER_EXECMODE=F3`) | Both pass the local simulation below; `F3` needs a username for the invoking uid (a normal server account has one). Benchmark I/O on the real server (Step 4) |
| No compose | `udocker-run.sh` is the single source of the run command (OPS-09) |
| Runs as the invoking user | `WORKSPACE_ROOT` must be writable by that user |
| External tasks | Compose and `udocker-run.sh` both mount `PLUGINS_HOST` at `/plugins` (`PLUGINS_ROOT`) and the derived folder writable (§Docker); `PLUGINS_HOST` defaults to the repository's shipped `plugins/` tree, and udocker volumes carry no read-only flag. Start `scripts/rw-runner.py` in the plugin environment (`conda activate torch` for SEG-*) on the same host, outside udocker; it talks to the app only through `WORKSPACE_ROOT/queue/` (OPS-13) |

### Local udocker simulation (`make udocker-selftest`)

`scripts/udocker-selftest.sh` checks the udocker path without a server: it saves the image into a named volume of a throwaway Linux container (`python:3.12-slim` + `curl`, same architecture), and as uid 10001 with no sudo it installs udocker from `./udocker.py`, runs `./rw update` (udocker load), `./rw up` (→ `udocker-run.sh`), `scripts/container_smoke.py`, a source-hash check (R1) and `./rw stop`, once per mode in `EXECMODES` (default `P1 F3`). Only Docker is needed on the host (named volumes + `docker cp`, no bind mounts); the udocker engine tarball is downloaded once into `build/udocker-selftest/`.

Result 2026-09-27 (linux/arm64 under colima, default Docker seccomp profile, no extra capabilities): **P1 pass** (healthy after ~13 s, TST-10 in 3 s), **F3 pass** (healthy after ~12 s including the F3 setup, TST-10 in 1 s); 191 source files unchanged. P1 (proot/ptrace) needed no `--cap-add SYS_PTRACE` or `seccomp=unconfined` on the outer container; if a stricter Docker host blocks ptrace, pass them through `OUTER_OPTS` (outer test container only; a real server has no such limit). The real remote check (amd64, real data, I/O benchmark) stays open (REL-07).

## Persistent local user service

P7g GPU admission follows OPS-16..20 and ADR-0034. Unconfigured GPU execution stays unavailable; an operator-configured local/server backend must pass effective checks before advertising tasks. Setup and trust/limit details have one owner: `../domain/SEGMENTATION_RUNTIMES.md`. `--preflight` without a deployment retains the original strict prerequisite report for diagnostics.
`RW_RUNNER_STORAGE_ROOT` and `RW_RUNNER_STORAGE_MAX_BYTES` are host-diagnostic inputs for an independently bounded, privately owned mounted filesystem; they do not configure a quota. `/`, symlinks and group/world-writable storage are refused. A free-space check is not an enforced budget.
For explicitly authorized, GPU-free effect testing, use `backend`'s `tools.runner_host_probe --run`; details/results belong to `SEGMENTATION_JOB_TEST_PLAN.md`. It never enables lingering, installs tools, changes driver policy or touches input/model roots.

An installation may live in `$HOME/.local/share/radiology-workbench/` independently
of the development checkout: `launcher/` (udocker + its Python environment),
`udocker/` (loaded release image and production container), `workspace/` (registry),
`derived/` (global conversion fallback), and `config/runtime.env` + `release.json`.
The container carries the compiled SPA, backend and builtin plugins; source code
is not mounted. Dataset locations are chosen through PRJ-19 inside the explicitly
authorized browsing root. HOME-wide access requires explicit owner authorization;
it is not the default source mount policy. Bind only `127.0.0.1`; the persistent
Web UI uses port **5180** for both the compiled frontend and API. Set `PORT` and
`PUBLIC_BASE_URL` together in `config/runtime.env` and restart the user service
to change it. Development Vite keeps its separate 5173 convention (DEV_ENV.md).

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

The Electron build is a thin shell that loads `PUBLIC_BASE_URL` (local Docker or a forwarded remote). It adds native folder dialogs through a preload bridge. The backend packaging is unchanged (ADR-0001).

## Implementation notes

- Host-side `.env` keys: `DATA_HOST`, `DATA_MOUNT_MODE` (Docker), `WORKSPACE_HOST`, `RW_VERSION` (image tag), `RUN_AS` (optional UID:GID, Docker), `UDOCKER_EXECMODE` (udocker), `DERIVED_HOST`, `PLUGINS_HOST` (defaults to `./plugins`).
- Image: 897 MB uncompressed on linux/arm64 (the build stage drops bundled `tests/` folders, pip, pyarrow headers and SimpleITK debug symbols; the web stage runs `vite build` only, type checking is a `make check` gate); 935 MB before FB10 (277 MB compressed, `docker save | gzip` 273 MB) on linux/amd64, built in ~4 min under colima qemu on an M-series Mac (needs colima `binfmt: true`); the build only succeeds if PyRadiomics passes the IBSI phantom smoke inside the image. Measure size with `du` of the rootfs: under the containerd store, `docker image inspect .Size` is the compressed size.
- `app/main.py` serves the SPA when `STATIC_ROOT/index.html` exists (`/assets` static, `index.html` fallback, `/api/*` never falls back). The entry point `scripts/container_app.py` only validates the config (clean OPS-04 refusal) and runs uvicorn.
- Version: the single source is `backend/pyproject.toml` (`{version}` above). `make image` tags it; the compose `RW_VERSION` default, `.env.example` and `udocker-run.sh` follow it (`tests/test_version.py`).
- Build for the server's architecture: `make image PLATFORM=linux/amd64` on an Apple Silicon Mac. The tag carries no architecture, so a second build for another platform replaces the first under the same tag.
- colima on the dev Mac has no host mounts by default (`$HOME` contains a space), so bind mounts appear empty; start it with `colima start --mount '<path>:w'` to use real data under Docker.
- If Docker Desktop is not running, a CLI config with `credsStore: desktop` makes pulls hang; use a `DOCKER_CONFIG` without a creds store.
