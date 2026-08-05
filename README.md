# Radiology WebUI

Radiology WebUI is a local-first ccRCC CT dataset curation viewer. It combines a FastAPI backend and a React + TypeScript + Vite frontend for database-driven case worklists, MPR slice review, overlay visualization, optional 3D mesh rendering, and state-only medical curation decisions.

See the full requirements in [docs/SRS.md](docs/SRS.md).

## Environment

- Backend runtime: Anaconda environment `ccrcc`
- Frontend runtime: vendored `udocker` with a `node:22-slim` image
- Port forwarding: handled by VS Code Remote SSH
- Portable runtime for other machines: native Docker + `docker compose`
- Desktop runtime: Tauri 2 on Windows 10/11 x64 with a private FastAPI sidecar
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
- At first launch, enter a server-visible path in **Open Dataset**, inspect it, then activate it
- Medical curation route: `/datasets/<dataset_id>/cases`

## Windows Desktop (M15)

Radiology Desktop is an additional distribution; it does not replace the web application. Tauri loads the compiled Vite assets locally and starts one hidden PyInstaller FastAPI sidecar on a dynamic loopback port. React receives the backend URL and an ephemeral bearer token through Tauri IPC before the native window is shown.

Desktop security boundaries:

- the sidecar listens only on `127.0.0.1`;
- every non-health API request requires a fresh 256-bit token kept only in memory;
- the handshake contains PID and port, never the token;
- CORS accepts only `http://tauri.localhost` and `http://localhost:5173`;
- JavaScript has no general shell permission; Browse uses one purpose-built Rust command;
- local path access is unrestricted only in the desktop sidecar, while source-data mutation remains disabled;
- normal close is graceful, with a five-second forced-termination fallback and parent-process watchdog.

The Open Dataset page shows `Browse…` only in desktop. Browse fills the field; `Inspect` still calls the read-only M14 contract and `Open dataset` activates separately. Cases, Patients, Resume, MPR PNG, and GLB routes are shared with the web edition.

### Reproducible Windows x64 build

Use a 64-bit Windows PowerShell with MSVC Build Tools, WebView2 Runtime, and the exact versions in `toolchains/desktop-windows-x64.json`. Install the pinned Tauri CLI once, then run the sole build entrypoint:

```powershell
cargo install tauri-cli --version 2.11.4 --locked
pwsh -File .\scripts\build-desktop.ps1
```

The script uses `npm ci`, the hashed desktop Python lock, `Cargo.lock`, deterministic environment settings, PyInstaller onefile without UPX, and Tauri NSIS `currentUser` packaging. Outputs are written to `artifacts/windows-x64/`:

- `Radiology-Desktop_2.2.0_x64-setup.exe` (unsigned);
- `Radiology-Desktop_2.2.0_x64-setup.exe.sha256`;
- `toolchain-manifest.json`;
- `build.log`.

The matching GitHub Actions workflow is `.github/workflows/windows-desktop.yml`. The installer uses the standard WebView2 download bootstrapper and may display the normal Windows warning because code signing is outside M15.

## Secure Dataset Opening

Dataset selection is a two-step operation:

1. `POST /api/workspace/inspect` reads markers, metadata, and volume headers without changing the active workspace, clearing caches, or creating `.webui/`.
2. `PUT /api/workspace` repeats validation and activates only an openable dataset.

`canonical` and `converter_output` datasets open in the case worklist. Legacy, standalone NIfTI, and VOI collections open in the compatible patient explorer. Incomplete datasets remain available as read-only diagnostics and cannot be activated.

The backend restricts dataset paths, referenced files, and symlink targets to `ALLOWED_DATA_ROOTS`. When that variable is absent it defaults to `DATA_ROOT`. Multiple roots use the server operating system's path separator (`:` on Linux, `;` on Windows), for example:

```bash
ALLOWED_DATA_ROOTS=/data:/mnt/research
```

`ALLOW_UNRESTRICTED_DATA_PATHS=true` bypasses this boundary and is intended only for explicit, isolated development. The workspace store keeps the five most recently opened server paths; it never stores patient or clinical metadata.

## MPR Rendering

The MPR renderer uses server-rendered PNG slices. This keeps first-slice loading and slice navigation light because the browser requests only the active axial, sagittal, and coronal PNGs plus adjacent slice prefetches.

## v2.0 Medical Curation Workflow

v2.0 is case-first: the doctor selects a case, then reviews complete scans or VOIs from the scan inventory. The current dataset contract is:

- `metadata.jsonl` for converter traceability and read-only scan metadata
- `phase.json` for mutable scan-level phase curation keyed by `case_id + scan_idx`
- `voi/voi_catalog.jsonl` for VOI rows, paths, side, provenance, and scan linkage

The medical worklist surfaces dataset readiness before review, including row/case counts, required-column status, path warning status, and total warnings. The case review page shows prior curation decisions for the active case, exposes the correction queue, and provides CSV export for external correction workflows.

Medical Curation Mode is source-data read-only. Doctor-facing actions save review state only:

- segmentation QC status and priority
- free-text comments
- phase correction proposals
- correction queue entries for external editing

The app does not rename files, move files across phase folders, overwrite `metadata.jsonl`/`voi_catalog.jsonl`, or modify NIfTI/SEG/VOI voxel data during v2.0 curation.

App-managed files are written under `<dataset>/.webui/` when writable:

- `settings.json`
- `curation_review.csv`
- `correction_queue.csv`

For read-only dataset mounts, set `WEBUI_STATE_DIR` and mount it writable:

```bash
WEBUI_STATE_DIR=/path/to/webui_state
```

Then curation state is written to `$WEBUI_STATE_DIR/<dataset_id>/`. Inspecting a dataset only reports the predicted state path and never creates it.

Legacy source-data mutation endpoints may remain for technical fallback, but the old patient/series viewer is no longer exposed in the WebUI. The GUI uses the case worklist and case review flow.

## Run On Other Machines (Docker Compose)

Yes, this repo can run on other machines without `udocker`.

1. Copy [.env.example](.env.example) to `.env`.
2. Set `DATASET_DIR` in `.env` so the server can access your dataset folders.
3. Keep `ALLOWED_DATA_ROOTS=/data` and `ALLOW_UNRESTRICTED_DATA_PATHS=false`.
4. Keep `ALLOW_DATA_MUTATIONS=false` for medical curation.
5. For read-only data mounts, set `WEBUI_STATE_DIR` to a writable state directory.
6. Start the app:

```bash
docker compose up -d --build
```

7. Open:

- `http://localhost:8000/`
- `http://localhost:8000/api/health`

8. In the UI, inspect and open a specific dataset folder, for example `/data/Dataset420`.

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
