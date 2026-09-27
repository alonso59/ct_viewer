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
| OPS-14 | Builtin tasks (converter, analyzers, radiomics) stay in the image within OPS-08; heavy plugins (torch, GPU) never go into the image. | M |

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
| `ALLOWED_DERIVED_ROOTS` | *(empty = no derived root; tasks that write volumes are unavailable)* | `:`-separated absolute writable dirs for `derived` roots (OPS-11) |
| `PLUGINS_ROOT` | *(empty)* | Read-only dir of external task manifests (TSK-01); the runner uses the same dir on the host |
| `BUILTIN_PLUGINS_ROOT` | `plugins/` next to `backend/` (`/app/plugins` in the image) | Builtin task plugins (converter, analyzers); normally left unset |

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
| External tasks | Compose and `udocker-run.sh` both mount `PLUGINS_HOST` at `/plugins` (`PLUGINS_ROOT`) and the derived folder writable (§Docker); udocker volumes carry no read-only flag. Start `scripts/rw-runner.py` in the plugin env (e.g. `conda activate rw-nnunet`) on the same host, outside udocker; it talks to the app only through `WORKSPACE_ROOT/queue/` (OPS-13) |

### Local udocker simulation (`make udocker-selftest`)

`scripts/udocker-selftest.sh` checks the udocker path without a server: it saves the image into a named volume of a throwaway Linux container (`python:3.12-slim` + `curl`, same architecture), and as uid 10001 with no sudo it installs udocker from `./udocker.py`, runs `./rw update` (udocker load), `./rw up` (→ `udocker-run.sh`), `scripts/container_smoke.py`, a source-hash check (R1) and `./rw stop`, once per mode in `EXECMODES` (default `P1 F3`). Only Docker is needed on the host (named volumes + `docker cp`, no bind mounts); the udocker engine tarball is downloaded once into `build/udocker-selftest/`.

Result 2026-09-27 (linux/arm64 under colima, default Docker seccomp profile, no extra capabilities): **P1 pass** (healthy after ~13 s, TST-10 in 3 s), **F3 pass** (healthy after ~12 s including the F3 setup, TST-10 in 1 s); 191 source files unchanged. P1 (proot/ptrace) needed no `--cap-add SYS_PTRACE` or `seccomp=unconfined` on the outer container; if a stricter Docker host blocks ptrace, pass them through `OUTER_OPTS` (outer test container only; a real server has no such limit). The real remote check (amd64, real data, I/O benchmark) stays open (REL-07).

## Electron (phase P8)

The Electron build is a thin shell that loads `PUBLIC_BASE_URL` (local Docker or a forwarded remote). It adds native folder dialogs through a preload bridge. The backend packaging is unchanged (ADR-0001).

## Implementation notes

- Host-side `.env` keys: `DATA_HOST`, `WORKSPACE_HOST`, `RW_VERSION` (image tag), `RUN_AS` (optional UID:GID, Docker), `UDOCKER_EXECMODE` (udocker), `DERIVED_HOST`, `PLUGINS_HOST`.
- Image: 897 MB uncompressed on linux/arm64 (the build stage drops bundled `tests/` folders, pip, pyarrow headers and SimpleITK debug symbols; the web stage runs `vite build` only, type checking is a `make check` gate); 935 MB before FB10 (277 MB compressed, `docker save | gzip` 273 MB) on linux/amd64, built in ~4 min under colima qemu on an M-series Mac (needs colima `binfmt: true`); the build only succeeds if PyRadiomics passes the IBSI phantom smoke inside the image. Measure size with `du` of the rootfs: under the containerd store, `docker image inspect .Size` is the compressed size.
- `app/main.py` serves the SPA when `STATIC_ROOT/index.html` exists (`/assets` static, `index.html` fallback, `/api/*` never falls back). The entry point `scripts/container_app.py` only validates the config (clean OPS-04 refusal) and runs uvicorn.
- Version: the single source is `backend/pyproject.toml` (`{version}` above). `make image` tags it; the compose `RW_VERSION` default, `.env.example` and `udocker-run.sh` follow it (`tests/test_version.py`).
- Build for the server's architecture: `make image PLATFORM=linux/amd64` on an Apple Silicon Mac. The tag carries no architecture, so a second build for another platform replaces the first under the same tag.
- colima on the dev Mac has no host mounts by default (`$HOME` contains a space), so bind mounts appear empty; start it with `colima start --mount '<path>:w'` to use real data under Docker.
- If Docker Desktop is not running, a CLI config with `credsStore: desktop` makes pulls hang; use a `DOCKER_CONFIG` without a creds store.
