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

Deployment (Docker and udocker) arrives in phase P7: [docs/ops/DEPLOYMENT.md](docs/ops/DEPLOYMENT.md).
Research use only; not a medical device.
