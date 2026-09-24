# Radiology Workbench

Local-first, browser-based CT workbench for dataset inspection, segmentation visualization (read-only),
curation and radiomics. QuPath-style layout in a VS Code shell (GitHub Dark) with a 3D Slicer-style 2×2 viewer.

> **Status:** v3 rewrite in progress; see [docs/product/ROADMAP.md](docs/product/ROADMAP.md).
> Documentation starts at [docs/INDEX.md](docs/INDEX.md). The v2 app is frozen in [legacy/](legacy/).

## Quick start (development)

Requirements: Python 3.12 (via `uv` or `python3.12`), Node 22+ natively **or** Docker/udocker.

```bash
make setup      # backend venv + frontend deps
make fixtures   # synthetic test dataset -> .fixtures/synthetic/
make check      # lint, type check, unit tests (both sides)
make dev-backend    # terminal 1: API on 127.0.0.1:8000
make dev-frontend   # terminal 2: UI on 127.0.0.1:5173
```

Remote servers without sudo: activate the conda env, then `make setup-backend VENV=$CONDA_PREFIX`,
`make setup-node` once, and use `RUNTIME=udocker` for frontend targets. See [docs/ops/DEV_ENV.md](docs/ops/DEV_ENV.md).

## Quick start (Docker)

One image serves the API and the UI on one port ([docs/ops/DEPLOYMENT.md](docs/ops/DEPLOYMENT.md)).

```bash
cp .env.example .env    # set DATA_HOST and ALLOWED_DATA_ROOTS (absolute paths)
docker compose up --build
# open http://localhost:8000
```

Data is mounted read-only at the same path as on the host; projects live in `WORKSPACE_HOST`
(default `./workspace`). Smoke test of a built image (TST-10): `make fixtures && scripts/container-smoke.sh`.

## Remote server (udocker, no sudo)

udocker cannot build images: build and `docker save radiology-workbench:3.0.0 -o rw-3.0.0.tar` on a
Docker machine, copy the tar over, then:

```bash
udocker load -i rw-3.0.0.tar   # or: python3 udocker.py load … (bundled copy)
cp .env.example .env    # same file as for compose
scripts/udocker-run.sh  # binds 127.0.0.1:$PORT; VS Code forwards the port
```

Research use only; not a medical device.
