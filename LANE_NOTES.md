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
