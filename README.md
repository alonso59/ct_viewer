# Radiology Workbench

Local-first, browser-based CT workbench for dataset inspection, segmentation visualization (read-only),
curation and radiomics. QuPath-style layout in a VS Code shell (GitHub Dark) with a 3D Slicer-style 2×2 viewer.

> **Status:** v3 rewrite in progress; see [docs/product/ROADMAP.md](docs/product/ROADMAP.md).
> Documentation starts at [docs/INDEX.md](docs/INDEX.md). The v2 app and the original DICOM converter are kept locally in `legacy/` as read-only reference (not in git after tag `legacy-reference`).

## Quick start (development)

Requirements: Python 3.12 (via `uv` or `python3.12`), Node 22+ natively **or** Docker/udocker.

```bash
make setup      # backend venv + frontend deps
make fixtures   # synthetic test dataset -> .fixtures/synthetic/
make check      # lint, type check, unit tests (both sides), requirement check
make docs       # docs site -> build/docs/ (Sphinx + MyST via uvx; dev only)
make dev-backend    # terminal 1: API on 127.0.0.1:8000
make dev-frontend   # terminal 2: UI on 127.0.0.1:5173
```

Remote servers without sudo: activate the conda env, then `make setup-backend VENV=$CONDA_PREFIX`,
`make setup-node` once, and use `RUNTIME=udocker` for frontend targets. See [docs/ops/DEV_ENV.md](docs/ops/DEV_ENV.md).

## Quick start (run the image)

One image serves the API and the UI on one port. `./rw` runs it with Docker (compose v2) or, on a
server without sudo, udocker ([docs/ops/DEPLOYMENT.md](docs/ops/DEPLOYMENT.md)).

```bash
./rw init    # writes .env: asks DATA_HOST (absolute), optional DERIVED_HOST and PORT
./rw up      # starts, waits for health, prints the URL (default http://localhost:8000)
./rw stop    # also: ./rw status | logs | update rw-<version>.tar | smoke
```

udocker cannot build images: run `make image image-tar` on a Docker machine, copy
`build/rw-<version>.tar` to the server, then `./rw update rw-<version>.tar`.
On a remote server, VS Code forwards the port.

Research use only; not a medical device.
