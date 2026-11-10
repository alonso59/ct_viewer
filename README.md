# Radiology Workbench

Local-first, browser-based CT workbench for dataset inspection, segmentation visualization (read-only),
curation and radiomics. QuPath-style layout in a VS Code shell (GitHub Dark) with a 3D Slicer-style 2×2 viewer.

> **Status:** v3 rewrite in progress; see [docs/product/ROADMAP.md](docs/product/ROADMAP.md).
> Documentation starts at [docs/INDEX.md](docs/INDEX.md). The v2 app and the original DICOM converter are kept locally in `legacy/` as read-only reference (not in git after tag `legacy-reference`).

## Quick start (development)

Requirements: Python 3.12 (via `uv` or `python3.12`), Node 22+ (natively or from a conda environment).

```bash
make setup      # backend venv + frontend deps
make fixtures   # synthetic test dataset -> .fixtures/synthetic/
make check      # lint, type check, unit tests (both sides), requirement check
make docs       # docs site -> build/docs/ (Sphinx + MyST via uvx; dev only)
make dev-backend    # terminal 1: API on 127.0.0.1:8000
make dev-frontend   # terminal 2: UI on 127.0.0.1:5173
```

Remote servers without sudo: activate the conda env, then `make setup-backend VENV=$CONDA_PREFIX`,
and put a conda environment with Node on `PATH` (`conda create -n rwnode -c conda-forge nodejs=22`). See [docs/ops/DEV_ENV.md](docs/ops/DEV_ENV.md).

## Run it

- **Production:** a native conda release run as a systemd user service, without sudo:
  `python3 scripts/rw-native.py prepare`, then `deploy`. On a remote server, VS Code forwards the port.
- **Local, any operating system (development and quick tests):** `cp .env.example .env`, set
  `DATA_HOST`, then `docker compose up -d --build` and open http://localhost:8000.

Details: [docs/ops/DEPLOYMENT.md](docs/ops/DEPLOYMENT.md).

Research use only; not a medical device.
