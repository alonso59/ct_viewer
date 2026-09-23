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

## 2026-09-23 · P2 shell + explorer · lane/2-shell

**Done** (ROADMAP §P2 tasks ticked; phase row left to the integrator)
- `api/`: explicit `Api` surface (`surface.ts`) with two bindings: `http.ts` (default; openapi-fetch for the P1 endpoints, documented paths for the rest) and `mock/` (`VITE_API_MODE=mock`, unit tests; loaded by dynamic import, so the seed is out of the prod bundle: main chunk 291 KB gzip, NFR-07). Domain types alias `schema.d.ts` where the endpoint exists (FE-03); the client normalizes paged lists (follows cursors), `scans[]` → `items`, job kinds/statuses, problem+json → `ProblemError`.
- SSE (API-40): one `EventSource` per project shared by subscribers; `useProjectSync` patches caches (jobs, index, variables) and drives the status bar live/connecting/offline (UI-07). A finished thumbnail job retries 404'd thumbnails.
- Home (UI-04, PRJ-02/03): Open Recent with API-26 thumbnail and progress, share-link copy, relink dialog on API-05 (also offered on open when a root does not resolve). New project offers the study preset (PRJ-12). `/p/{unknown}` shows "Project not found".
- Import wizard (IMP-01..05): allowed-roots browser (API-10), optional metadata upload (multipart), preview counts / field mapping / first 50 errors, commit → index job progress → toast.
- Explorer (UI-08/09, VAR-10): `group` removed from filters, rows, quick open. Search view filters on any visible variable (`var.{name}=level` or `min..max`); Project view header menu "Columns and colour" picks case-level variables as row columns and one categorical variable as a colour stripe (`--cat-1..8`) with a legend. Per-project prefs in localStorage.
- Variables view (new `features/variables/`): Study / Derived / External / Acquisition sections, Review badge with "Use categorical/continuous" for numeric-discrete (VAR-03), type override, visibility, tags (VAR-05), derived bin/recode/dominant dialog (VAR-06), external CSV/TSV import with match report (VAR-07). The mock implements the VARIABLES.md inference rules (`api/mock/variables.ts`, tested).
- Share link copies the active deep link (`/p/{pid}/case/{cid}?item=…`, PRJ-03); falls back to showing the URL when the clipboard is unavailable (plain-http hosts).
- Tests: 51 vitest (new: inference rules, derived form, explorer variable helpers). Playwright (`frontend/e2e/p2-flow.spec.ts`) against the real backend on `.fixtures/synthetic`: new project → import → browse → share link opened in a second browser context; unknown link. 6/6 on Chromium + Firefox. `make check` green.

**Requests for other paths**
- lane/2-backend (API-16..18, PRJ-12), proposed contract the frontend codes against (`frontend/src/api/types.ts` §Study variables; please confirm or tell the integrator what differs):
  - `GET /projects/{pid}/variables` → `Variable[]` or `{items, total}` (both accepted). `Variable = {name, source: metadata|derived|external|raw, type, inferred_type, level: case|scan, group: study|acquisition, tags[], visible, confidence, review, overridden, profile: {missing_pct, n_distinct, examples[], min?, max?, levels?: [{value, count}]}, definition?}`.
  - `PATCH …/variables/{name}` body `{type?, visible?, tags?}` → `Variable`. `POST …/variables/derived` body = the VARIABLES.md derived JSON → `Variable` (422 `validation` with `detail` on a bad definition). `DELETE …/derived/{name}` → 204 (409 if another derived variable uses it). `POST …/variables/external` multipart `file` + `key` (`case_id|patient_id`) → `{key, n_rows, matched, unmatched_keys[], added[]}`.
  - `CaseSummary` gains `variables: {name: value}` (case-level visible variables) so the explorer can show columns/colour, and `thumb_item_id` (else the client fetches each visible case's detail to pick one). Catalog changes emit `project.updated {fields: ["variables"]}`.
  - `ProjectCreate` gains `preset: ccrcc|generic-ct|none` (sent already; P1 ignores it). `ProjectDetail.preset` is read if present.
- lane/2-viewer (`features/viewer/ImageSection.tsx`): switch `advanced.image_abs/mask_abs` to the API names `image_path/mask_path` (aliases kept in `ItemDetail` until then) and drop the `image.group` row (VAR-10).
- `docs/frontend/UI_SHELL.md` (integrator): Variables view layout above; Project view "Columns and colour" menu + colour stripe/legend; share link = deep link; §Prototype defaults: the mock and "Simulate a second reviewer" exist only with `VITE_API_MODE=mock` (Settings hides them otherwise).
- `docs/frontend/ARCHITECTURE.md` / `docs/ops/DEV_ENV.md`: `api/surface.ts` + `http.ts` + `mock/`; env `VITE_API_MODE`, `VITE_API_BASE` (FE-07), `VITE_PORT`, `VITE_API_PROXY` (dev proxy target; flushes SSE headers, otherwise the stream only opens at the first 15 s ping). `make e2e` starts its own backend (8011) and Vite (5174) with a temp workspace; needs `make fixtures` and a free 5174.
- `frontend/package.json` (integrator): added `openapi-fetch` ^0.14 (listed in ARCHITECTURE §Stack, was missing).

**Open issues**
- Presets vs phases: `generic-ct` (NC/ART/PV/DELAYED) cannot be expressed in `PhaseInfo.canonical` (NC/CMP/NP/EP/UNK) or the frontend `PHASES`; the phase filter and chips still use the fixed set. Needs a P1b decision (API enum or `project.phase_vocabulary`).
- Endpoints not merged yet (curation API-50..54, radiomics API-30..38, variables API-16..18): the HTTP client calls the documented paths; list reads treat 404/405 as empty, so on the P1 backend those views show empty states and the console logs 404s. Their hand-written types stay until `make gen-api` covers them (P4-FE/P5-FE reconcile).
- The P1 `GET /cases` never lists cases whose items are all excluded upstream, so "Show items excluded upstream" is mock-only.
- Dashboard `group` (FeatureRow, DashboardEditor) is untouched, as assigned to P6-FE.
