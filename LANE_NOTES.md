# Lane notes

Append-only handoff log between lanes and the integrator (docs/ops/AGENT_RUNBOOK.md).
Format: `## <date> · <lane> · <branch>`, then **Done**, **Requests for other paths**, **Open issues**.

## 2026-09-23 · Step 0 bootstrap · v3

**Done**
- v2 app moved to `legacy/`. v3 skeletons in `backend/` and `frontend/`; `Makefile`; `make fixtures` (13/13 QC codes, deterministic); `make check` green.
- Toolchain: Python 3.12 (uv venv at `backend/.venv`), Node native locally (RUNTIME=native).

**Open issues for later lanes**
- P1: `pyradiomics` is in the optional `[radiomics]` extra until the Python 3.12 spike passes (ADR-0006). Not installed by `make setup`.
- P1: Starlette warns that the TestClient's `httpx` backend is deprecated in favour of `httpx2`; revisit when adding API tests.
- Frontend pins: TypeScript ~5.9 (openapi-typescript and typescript-eslint reject 6+/7) and ESLint 9 (eslint-plugin-react rejects 10). Revisit when upstream supports them.
- `fingerprint_changed` fixture needs a test step: index, then modify `expected.json → mutate_after_index`, then revalidate.
- Extra warnings are expected alongside a defect's main code (e.g. `missing_seg` on the `unreadable_file` case); tests should assert inclusion, not exact sets.

## 2026-09-23 · P1 backend core · lane/1-backend: spikes

**Spike A: PyRadiomics on Python 3.12 (ADR-0006).** Result: **pass, with a source pin.**
- PyPI `pyradiomics` 3.1.0 (latest) ships wheels only up to cp39; its sdist fails to build (missing `cmatrices.h`, sdist metadata says 3.0.1a1). Not installable on 3.12 from PyPI.
- Upstream master `AIM-Harvard/pyradiomics@8ed57938` (3.1.1.dev111) builds from source on CPython 3.12.14 (macOS arm64, needs a C compiler) with numpy 2.x, SimpleITK, PyWavelets.
- IBSI 1 digital phantom smoke test: 20/20 within tolerance (first-order 17 features incl. entropy/uniformity at binWidth 1; mesh volume 556.3, voxel volume 592, surface 388.1). Reproduce offline: `backend/.venv/bin/python -m tools.spikes.ibsi_phantom_smoke` after `uv pip install -e 'backend[radiomics]'`.
- `backend/pyproject.toml` `[radiomics]` extra now pins that commit (`allow-direct-references`). Still optional; not installed by `make setup`.
- Not verified: the Linux runtime image (no Docker daemon on this machine). P7 must build the extra inside the image (needs `gcc` in the build stage only) and rerun the smoke script. Kurtosis caveat for the IBSI map (P5): PyRadiomics reports non-excess kurtosis (IBSI = value − 3).
- **ADR:** no superseding ADR needed; the decision (PyRadiomics default behind the adapter) holds. Integrator: please set ADR-0006 status to "Accepted (P1 spike passed 2026-09-23; installed from a pinned upstream commit, not PyPI)". MIRP fallback not triggered.

**Spike B: NiiVue mesh format (VIEWER.md open question, API-25).** Result: **MZ3, gzip-compressed.**
- NiiVue 0.69.0 `NVMeshLoaders` parse MZ3, GIfTI, STL, OBJ, PLY, VTK, … headlessly in Node. Marching cubes (skimage) → each encoder → NiiVue loader:

| Mesh | Format | Size | NiiVue parse |
|---|---|---|---|
| 302k tris / 151k verts (400×400×200 kidney proxy, 0.8×0.8×1.5 mm) | MZ3 gzip | 1.98 MB | 16 ms |
| | MZ3 raw | 5.3 MB | 1 ms |
| | GIfTI (GZipBase64) | 2.6 MB | 23 ms |
| | STL binary | 14.8 MB | 6 ms (no shared verts: 907k) |
| | OBJ | 10.4 MB | 138 ms |
| fixture tumor, 824 tris | MZ3 gzip / GIfTI / STL | 4.8 / 7.3 / 41 KB | < 30 ms |

- Decision proposal for P3: `cache/meshes/{mask_fp}_{label}_{smooth}.mz3`, gzip MZ3 (header `<HHIII` magic 23117, attr 3 = faces+verts; int32 faces then float32 verts in world mm via the NIfTI affine), served as `application/octet-stream`. Marching cubes on a 400×400×200 mask ≈ 0.2 s. Owner: lane 2 viewer (`backend/app/imaging/mesh*`); VIEWER.md open question → Decisions (integrator).

## 2026-09-23 · P1 backend core · lane/1-backend: summary

**Done** (tasks ticked in ROADMAP §P1; phase row left ⬜ until the Dataset820 check below)
- `core/` (errors/problem+json, ids, fsio, paths + guards, locks, JSON logs), config validation (OPS-03).
- `projects/`: workspace registry, project.json + LRU, PRJ-11 migrations (backup `project.json.v{n}.bak`), archive/unarchive (purges `cache/`), roots + relink verification (PRJ-05). API-02..05, API-10.
- `ingest/`: parsers (+hypothesis), phase/side normalization, preview (detect or multipart) → commit snapshot `sources/{import_id}/` → index job (worker units read-only) → validator (all 13 IMP-08 codes) → `index/*`. API-11..14, 20..22.
- `imaging/`: header reader, quick fingerprint, byte streaming with Range/ETag/304 (BE-04), npy→NIfTI cache in workers (IMP-10), 128 px WebP thumbnails job after indexing (IMP-12). API-23/24/26.
- `jobs/` (process pool, FIFO, progress throttle, cancel, conflict, interrupted on shutdown) and `events/` (bus with 1,000-event replay, SSE with Last-Event-ID). API-40/41.
- Tests: 170 pytest (TST-01 core/services, TST-02 parsers, TST-03 `test_contract.py` with OpenAPI snapshot `backend/tests/openapi.snapshot.json`, TST-07 in `test_e2e_import.py` against `.fixtures/synthetic` with a BE-03 write-open guard). `make check` green.
- Exit on fixtures: `tools.import_check` with real worker processes → all expected defects reported, 58 source files unchanged (SHA-256), pass.
- Fixture fix: the `missing_affine` case had sform code 2 (nibabel re-stamps on save); now codes 0/0.

**Dataset820 check (for the project owner)**, from the repo root on the machine that has the data:
```
cd backend && .venv/bin/python -m tools.import_check --root /ABS/PATH/TO/Dataset820 --sha256 --workers 4
```
Prints preview counts, index time, case count, warnings per code, and `sources_changed` (must be `[]`); exit 0 = pass. It uses a throwaway workspace (add `--workspace DIR` to keep it) and sets `ALLOWED_DATA_ROOTS` to the root. On the remote server: `make setup-backend VENV=$CONDA_PREFIX` first and use `$CONDA_PREFIX/bin/python`. `--sha256` reads every byte once before and once after; drop it for a quick run.

**Requests for other paths (integrator)**
- `frontend/src/api/schema.d.ts`: run `make gen-api` (OpenAPI changed: API-02..05, 10..14, 20..26, 40, 41). Not done here (frontend is not lane-owned).
- `docs/domain/INPUT_METADATA.md`: the image location is `relative_path` → `nifti_file` → `nifti/{filename}` (v2 behaviour, implemented); "first non-empty wins" only holds for the filename identity. Please reword.
- `docs/backend/API.md`: API-13 response also carries `index` (IndexStatus); API-26 thumbnails are lossless WebP; an unconvertible `.npy` returns `validation` (422). Please record, or pick another slug.
- `docs/adr/0006`: status note (see spikes above). `docs/frontend/VIEWER.md` open question → Decision: gzip MZ3.
- `docs/ops/DEPLOYMENT.md` / P7: OPS-04 "empty `ALLOWED_DATA_ROOTS` refuses to start in container mode" is not enforced yet (no container-mode signal in OPS-03); today empty = unrestricted with a warning log. P7 should add the signal.
- `backend/pyproject.toml` (integrator-owned list): added `pillow>=10.4`; `[radiomics]` extra pinned to a git commit.

**Open issues / not in P1**
- IMP-09 / API-15 full-hash job and PRJ-08/09 bundles are not implemented (not in the P1 task list).
- Thumbnail worker warnings include the absolute path of a failing file at `warning` level (allowed by BE-09, which only forbids `info`).
- sse-starlette's `AppStatus.should_exit` is process-global; tests that stop uvicorn must reset it (see `tests/test_events_sse.py`).
- `fingerprint_changed` is detected on re-import (compare with the previous index), not by a background revalidation.
## 2026-09-23 · P0.5 design · lane/1-design

**Done**
- `frontend/`: tokens (GitHub Dark + Light), base styles, CT icon set (UI-15), registry-driven shell (UI-01/02) on dockview, command palette / quick open, keybindings with overrides, status bar, toasts, reviewer prompt.
- Features on a mock API seeded from `make fixtures` (`npm run mock:seed`, seed committed ~0.9 MB): home, import wizard, project view with thumbnails, 2×2 viewer placeholder (real mid-slices, VW-04 colours), curation + history + correction queue, radiomics settings (schema-driven, live validation), run dashboard (ECharts, lazy), measurements, jobs/output.
- Tests: i18n key coverage, CUR-08 rollup, RAD-04 rules, dashboard analytics, chords, icon rules. `make check` green.
- UI_SHELL.md updated (Alt+W close tab, Image view + section, CT icon list, theme choice, prototype defaults).

**Requests for other paths**
- ROADMAP.md (integrator): mark P0.5 tasks done except the curator/researcher walkthrough.
- Deps added: react-router 7, zustand, @tanstack/react-query + react-virtual, dockview-react, radix (dialog, dropdown-menu, tooltip, checkbox), @vscode/codicons, cmdk, echarts.

**Open issues**
- Port 5173 is held by VS Code on the dev Mac; the lane dev server ran on 5174.
- P2: replace `api/mock` with the generated client behind the same `api` surface; dashboard sub-panels (DB-01) and brushing (DB-04) are not in the prototype.

## 2026-09-23 · Step 1 integration · v3

**Done**
- Merged `lane/1-backend` (P1, 4 commits) and `lane/1-design` (P0.5, 1 commit) into `v3`. Only conflict: this file (both entries kept).
- `make gen-api` regenerated `frontend/src/api/schema.d.ts` for the P1 endpoints. `make fixtures && make check` green: 170 backend + 32 frontend tests.
- Applied the lane requests: ROADMAP P0.5 tasks ticked (walkthrough still open), ADR-0006 status + spike result, RADIOMICS spike result, VIEWER mesh decision (gzip MZ3), INPUT_METADATA image-location order, API.md (API-13 `index`, API-26 lossless WebP, `.npy` 422).
- Deferred items now listed in ROADMAP: Dataset820 check, IBSI smoke in the image and OPS-04 container-mode signal (P7); IMP-09/API-15 and PRJ-08/09 (P5/P6).

**For Step 2 lanes**
- P2: replace `frontend/src/api/mock` with the generated client behind the same `api` surface.
- P3: mesh format is gzip MZ3 (VIEWER.md §Decisions); two NiiVue spikes remain (single vs four instances, label rendering).
- Dev server port: 5173 is taken by VS Code on the dev Mac; lanes used 5174.

## 2026-09-24 · P3 viewer · lane/2-viewer

**Done** (ROADMAP §P3 tasks ticked; exit met on the synthetic reference volume, see TST-09)
- `features/viewer/engine/`: `ViewerHandle` on NiiVue 0.69 (only place that imports it). Layouts VW-01 (DOM grid drives NiiVue `setCustomLayout` tiles), maximize/Esc VW-02, wheel/Shift/slider VW-03, Slicer-coloured linked crosshair VW-04 (DOM lines), W/L drag + inputs + presets / non-CT percentile VW-05, pan (middle, Space, tool) and zoom (Ctrl/Cmd+wheel, pinch, tool) with a link toggle VW-06, labels VW-07, readout VW-08, 3D volume/label render + API-25 surfaces + blend VW-09, toolbar incl. engine screenshot VW-10, item switcher kept VW-11, adaptive states VW-12, byte-progress loading VW-13, `VIEWER_MAX_LOADED` budget VW-14, same-geometry crosshair/W/L carry-over VW-15, `getViewerContext()` for CUR `context.viewer` VW-16.
- `backend/app/imaging/mesh.py`, `mesh_api.py`, `mesh_test.py`: API-25 mesh job (marching cubes in a `mesh` worker job, optional Gaussian smoothing, world-mm vertices, outward winding, gzip MZ3 at `cache/meshes/{mask_fp}_{label}_{smooth}.mz3`); `200` bytes / `202` + JobInfo + `Location` / `304` / `404` / `409` / `422`. 0.2–0.5 s on 400×400×200 and 512×512×600 masks (NFR-05 < 5 s).
- Harness (no app router change): `npx vite --config src/features/viewer/harness/vite.config.ts` → http://127.0.0.1:5175 (fixture items from `.fixtures/`, `?src=reference`, `?layout=`). Reference volume: `node src/features/viewer/harness/make-reference.mjs` (512×512×600 int16 LPS CT phantom + 3-label mask, ~155 MB gz, into `.fixtures/reference/`).
- Checks: `make check` green (170 pytest, 55 vitest incl. 25 new); `pytest app/imaging/mesh_test.py` 15 passed (run explicitly: outside `testpaths`).

**Spike results (VIEWER.md §Technical spikes → Decisions, integrator please record)**
1. *One instance vs four:* **one instance per case tab**, all tiles on one canvas via `setCustomLayout`; four instances would hold four GPU copies of the volume. Frames/headers/sliders/crosshair lines are DOM over the canvas.
2. *Label rendering:* **custom LUT in our own 2D slice shader**, not NiiVue's label colormap. NiiVue's atlas shader forces every visible label to alpha 1 (only one layer opacity) and its outline is 3D. Ours: LUT row 0 = colour + per-label opacity (0 = hidden), row 1 = outline flag; outline = in-plane 4-neighbour boundary (3D Slicer style). NiiVue's label colormap is still used for the 3D tile (visibility only).
3. *Found during TST-09 (new):* NiiVue re-uploads and re-composites the full volume on every W/L or overlay change (≈ 550–650 ms per change on 512×512×600; 2 fps). So 2D tiles use NiiVue's `setCustomSliceShader` hook with full-resolution textures uploaded once (R16_SNORM via EXT_texture_norm16, R32F fallback; labels R8UI/R16UI); W/L and labels are uniforms. NiiVue still does layout, pan/zoom, picking and the 3D tile, which renders a ≤ 24 M-voxel proxy (same extent) refreshed 200 ms after a change settles. Still NiiVue per ADR-0003 (no superseding ADR needed in my reading; integrator/user may disagree).

**TST-09** (`node src/features/viewer/harness/bench.mjs`, harness running; Apple M4, Chrome for Testing, ANGLE Metal, 1600×1000 @2×, four-up):
| Metric | Before (NiiVue compositing) | Now | Target |
|---|---|---|---|
| NFR-01 open → first slice | 2.5 s | **1.9 s** (mask 3.1 s) | < 3 s |
| NFR-02 scroll axial / sagittal | 18 / 19 fps | **60 / 60 fps** (GPU 10.7 ms) | ≥ 30 |
| NFR-02 W/L drag | 2 fps | **60 fps** | ≥ 30 |
| Overlay opacity drag | 2 fps | **60 fps** | — |
| JS heap, one tab | 2.4 GB | **0.58 GB** | NFR-09 ≤ 3 GB for 3 tabs |
Synthetic phantom only; Dataset820 re-run belongs to TST-09 in P7.

**Requests for other paths (integrator)**
- `backend/app/api/v1/__init__.py`: mount API-25 — `from app.imaging import mesh_api` and `router.include_router(mesh_api.router)` after the loop; refresh `backend/tests/openapi.snapshot.json`; `make gen-api`. Move `backend/app/imaging/mesh_test.py` into `backend/tests/` (or add it to `testpaths`).
- `frontend/src/i18n/en.json`: move the `vw` bundle from `features/viewer/i18n.ts` (VW_EN) into en.json (e.g. merge into `viewer.*`), then delete `i18n.ts` and the `./i18n` imports. Unused now: `viewer.placeholderNote`, `viewer.render3dPlaceholder`, `viewer.noPreview`.
- `docs/frontend/VIEWER.md` §Wrapper contract: `load` takes `LoadOptions` (`onProgress`, `onImage`, `signal`) and the handle adds `maskError`, `setTiles`, `setLabels`, `setOverlay`, `setLinkedZoom`, `setRender`, `setMeshes`, `step/goto/pick/hover/pan/zoom/orbit`, `resetView`, `defaultWindow`, `onView`, `screenshot`, `stats` (see `features/viewer/model/types.ts`). Move spikes to §Decisions as above. VW-16 `slice` is the 1-based index shown in the viewport header.
- Shell (P2): call `configureViewer({ maxLoaded: health.ui_config.viewer_max_loaded })` from `features/viewer` once API-01 is loaded (default 3). Case URLs use `/api/v1/projects/{pid}/items/{iid}/{image|mask|mesh/{label}}`.
- `frontend/package.json`: added `@niivue/niivue ^0.69.0`.
- P2 note applied: `ImageSection` reads `advanced.image_path/mask_path` and the group row is gone (VAR-10).

**Open issues**
- VW-05 "modality = CT": `ItemRecord` has no `modality`; the viewer reads `extra.modality` and treats a missing value as CT.
- VW-09 3D pan is not implemented (NiiVue has no 3D pan); orbit and zoom work. 3D shows the proxy (≤ 24 M voxels), so fine detail comes from the surfaces.
- API-25 end to end (UI → backend) not exercised: the router is not mounted in this lane; client polling is unit-tested.
- NFR-09 with 3 loaded tabs not measured (one tab 0.58 GB heap + GPU textures ≈ 0.5 GB for the reference).
- Browsers without EXT_texture_norm16 (likely Safari) fall back to R32F (2× GPU memory for int16 CT); not tested on Safari/Firefox.
