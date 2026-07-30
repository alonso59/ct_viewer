# Radiology WebUI

Radiology WebUI is a local-first ccRCC CT dataset curation viewer. It combines a FastAPI backend and a React + TypeScript + Vite frontend for database-driven case worklists, MPR slice review, overlay visualization, optional 3D mesh rendering, and state-only medical curation decisions.

See the full requirements in [docs/SRS.md](docs/SRS.md).

## Environment

- Backend runtime: Anaconda environment `ccrcc`
- Frontend runtime: vendored `udocker` with a `node:22-slim` image
- Port forwarding: handled by VS Code Remote SSH
- Portable runtime for other machines: native Docker + `docker compose`
- Frontend auth token storage defaults to in-memory (`frontend/.env.example`)

First-time machine setup guide:
- [docs/SETUP_PREREQUISITES.md](docs/SETUP_PREREQUISITES.md)

## Local udocker entrypoints

This repo ships two local entrypoints:

- `udocker-1.3.17/udocker/udocker` (upstream launcher)
- `udocker.py` (project wrapper that sets `UDOCKER_DIR`, `PYTHONPATH`, and `PROOT_NO_SECCOMP`)

Examples:

```bash
python udocker.py version
python udocker.py images -l
```

## Quickstart

```bash
make setup
make dev-backend
make dev-frontend
```

`make setup` performs first-step bootstrap for this repository:
- checks conda + vendored udocker availability
- initializes local udocker runtime (`.udocker/`)
- pulls/creates the `radio-node22` container only if missing
- installs backend Python requirements

Note: Docker is detected and reported, but not auto-installed by `make` because Docker installation is system-level and usually requires admin privileges.

To produce the frontend static bundle with udocker:

```bash
make build-frontend
```

## Manual Verification

- Backend health: `http://localhost:8000/api/health`
- Frontend dev server: `http://localhost:5173`
- At first launch, enter the server path to one dataset folder in the workspace setup screen
- Medical curation route: `/datasets/<dataset_id>/cases`

## MPR Rendering

The MPR renderer uses server-rendered PNG slices. This keeps first-slice loading and slice navigation light because the browser requests only the active axial, sagittal, and coronal PNGs plus adjacent slice prefetches.

## v2.0 Medical Curation Workflow

v2.0 is case-first: the doctor selects a case, then reviews complete scans or VOIs from the scan inventory. When `database.csv` is present, it is the source of truth for:

- `case_id`, `patient_id`, group, phase, scan index, side
- full scan, SEG, VOI image, and VOI mask paths
- preprocessing/QC fields and advanced metadata

The legacy `manifest.csv` and folder discovery paths remain available only as fallback when `database.csv` is absent.

The medical worklist surfaces `database.csv` readiness before review, including row/case counts, required-column status, path warning status, and total warnings. The case review page shows prior curation decisions for the active case, exposes the correction queue, and provides CSV export for external correction workflows.

Medical Curation Mode is source-data read-only. Doctor-facing actions save review state only:

- segmentation QC status and priority
- free-text comments
- phase correction proposals
- correction queue entries for external editing

The app does not rename files, move files, overwrite `database.csv`/`manifest.csv`, or modify NIfTI/SEG/VOI voxel data during v2.0 curation.

App-managed files are written under `<dataset>/.webui/` when writable:

- `settings.json`
- `curation_review.csv`
- `correction_queue.csv`

For read-only dataset mounts, set `WEBUI_STATE_DIR` and mount it writable:

```bash
WEBUI_STATE_DIR=/path/to/webui_state
```

Then curation state is written to `$WEBUI_STATE_DIR/<dataset_id>/`.

Legacy source-data mutation endpoints and the old patient/series viewer can remain for technical fallback, but they are not exposed in the v2.0 medical curation route.

## Run On Other Machines (Docker Compose)

Yes, this repo can run on other machines without `udocker`.

1. Copy [.env.example](.env.example) to `.env`.
2. Set `DATASET_DIR` in `.env` so the server can access your dataset folders.
3. Keep `ALLOW_DATA_MUTATIONS=false` for v2.0 medical curation.
4. For read-only data mounts, set `WEBUI_STATE_DIR` to a writable state directory.
5. Start the app:

```bash
docker compose up -d --build
```

6. Open:

- `http://localhost:8000/`
- `http://localhost:8000/api/health`

7. In the UI, enter the server path to a specific dataset folder, for example `/data/Dataset420`.

Useful commands:

```bash
docker compose logs -f
docker compose down
```

Equivalent Make targets:

```bash
make compose-build
make compose-up
make compose-logs
make compose-down
```

## OCI Build (M12)

The project now includes a multi-stage [Dockerfile](Dockerfile):

- Stage 1 builds the Vite frontend.
- Stage 2 installs backend dependencies and serves `/app/static` via FastAPI.
- Container default dataset root is `DATA_ROOT=/data`.

Build the image with Podman:

```bash
podman build -t radiology-ui:1.0 .
```

Build the same image with native Docker:

```bash
docker build -t radiology-ui:1.0 .
```

Run it against the mounted dataset:

```bash
podman run --rm -p 8000:8000 \
  -e WEBUI_STATE_DIR=/state \
  -v /home/alonso/Documents/radio-ccrcc/data/dataset:/data:ro \
  -v /home/alonso/Documents/radio-ccrcc/webui_state:/state:rw \
  radiology-ui:1.0
```

Docker equivalent:

```bash
docker run --rm -p 8000:8000 \
  -e WEBUI_STATE_DIR=/state \
  -v /home/alonso/Documents/radio-ccrcc/data/dataset:/data:ro \
  -v /home/alonso/Documents/radio-ccrcc/webui_state:/state:rw \
  radiology-ui:1.0
```

Then open:

- `http://localhost:8000/`
- `http://localhost:8000/api/health`

## udocker Deployment

Export the built OCI image and run with udocker:

```bash
podman save -o radiology-ui_1.0.tar radiology-ui:1.0
# or: docker save -o radiology-ui_1.0.tar radiology-ui:1.0
python udocker.py load -i radiology-ui_1.0.tar
python udocker.py create --name=radio-ui radiology-ui:1.0
python udocker.py run -p 8000:8000 \
  -e WEBUI_STATE_DIR=/state \
  -v /home/alonso/Documents/radio-ccrcc/data/dataset:/data:ro \
  -v /home/alonso/Documents/radio-ccrcc/webui_state:/state:rw \
  radio-ui
```

The repo includes a local `udocker` bundle and stores its runtime state under `.udocker/`, so no global `udocker` command on `PATH` is required.
