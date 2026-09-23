# Deployment

Scope: OCI image, Docker (local), udocker (remote, no sudo), configuration, upgrades.
Read when: building or running the image, or changing env vars.
Depends: ADR-0007, backend/ARCHITECTURE.md.

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
| `CACHE_MAX_GB` | `20` | Per-project `cache/` cap; LRU purge |
| `VIEWER_MAX_LOADED` | `3` | Loaded viewer tabs (VW-14) |
| `LOG_LEVEL` | `info` | |
| `STATIC_ROOT` | `/app/static` | SPA build |

## Docker (local machine)

```yaml
# docker-compose.yml (sketch)
services:
  app:
    image: radiology-workbench:3.0.0
    build: .
    ports: ["127.0.0.1:${PORT:-8000}:8000"]
    env_file: .env
    volumes:
      - ${WORKSPACE_HOST:-./workspace}:/workspace
      - ${DATA_HOST}:${DATA_HOST}:ro        # mirror mount (OPS-05)
```

## udocker (remote server, no sudo)

udocker cannot build images. Build with Docker elsewhere, then transfer the tar or pull from a registry:

```bash
docker save radiology-workbench:3.0.0 -o rw-3.0.0.tar      # on the build machine
udocker load -i rw-3.0.0.tar                               # on the server
udocker create --name=rw radiology-workbench:3.0.0
./scripts/udocker-run.sh                                   # wraps: udocker run --volume=… --env=… rw
```

| Note | Consequence |
|---|---|
| udocker does not isolate the network: the process binds host ports directly | Use `HOST=127.0.0.1` and let VS Code forward the port; `-p` mapping is not relied on |
| Mount `:ro` is not guaranteed under every execution mode | Source safety is enforced by the app (BE-02/03), not the mount |
| Execution mode affects I/O speed (`P1` default vs `F3`) | Benchmark in P7; document the chosen mode in the run script |
| No compose | `udocker-run.sh` is the single source of the run command (OPS-09) |
| Runs as the invoking user | `WORKSPACE_ROOT` must be writable by that user |

## Electron (phase P8)

The Electron build is a thin shell that loads `PUBLIC_BASE_URL` (local Docker or a forwarded remote). It adds native folder dialogs through a preload bridge. The backend packaging is unchanged (ADR-0001).
