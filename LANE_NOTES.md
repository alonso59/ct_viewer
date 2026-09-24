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

## 2026-09-24 · P1b + P4-BE + P5-BE + P6-BE · lane/2-backend

**Done** (commits `53aca21`, `599f6b5`, `23def5d`; ROADMAP P1b ticked, P5/P6 backend lines ticked, mixed P4/P6 lines annotated "backend done")
- P1b (ADR-0011, VAR-01..11, PRJ-07/12, API-16..18): `group` gone from items/cases/drafts/filters; `app/variables/` (profiling, type/level inference, Review, Study/Acquisition via the known converter field list in `variables/schema.py`, tags, overrides, bin/recode/dominant, external CSV/TSV, raw_metadata allowlist, exclusions), `index/variables.parquet`, `var.{name}` filters on API-20. Presets `ccrcc | generic-ct | none`; `Phase` is now a string from `project.json` `phase_vocabulary` + new `phase_mapping` (answers the P2 open issue); empty label map → auto `label_{value}` after the first index.
- Calibration against `../ct_viewer/metadata.jsonl` (scratch script, nothing committed): 77 cases; the two compositional study labels profile continuous case-level (39/77 present), the third numeric-discrete + Review; no `group`; only those three + raw sex/age land in Study. P1b exit met.
- P4-BE curation: API-50..54, CUR-01..14 backend; `app/curation/state.py` (`item_statuses`, `case_statuses`) used by ingest (case rollup, `curation_progress`) and analytics.
- P5-BE radiomics: API-30..37; TST-06 (IBSI digital phantom, 85 compliant + 4 deviates within 0.6 %), NFR-15 (bitwise identical re-run). PyRadiomics stays optional: engine endpoints return `server-busy` without it; its tests `importorskip`.
- P6-BE analytics: API-38 (11 views), API-39 analyses; TST-12 vs SciPy (p/statistics to 1e-12, BH vs `false_discovery_control`, every REC rule triggered). `tests/test_lane2_e2e.py`: real run on the fixtures → `case_00062` is the top outlier with an openable item; 2- and 3-group comparisons on derived variables match SciPy with q + recommendations.
- P2 requests: `CaseSummary.thumb_item_id` (active complete item by phase priority) and `CaseSummary.variables` (case-level visible variables) on API-20/21.
- Fixtures (TST-11): no `group`; 32-case cohort (compositional pair ~50 % missing, numeric-discrete, continuous, vendor strings, 1 MRI, dates/UID/accession/path/raw_metadata), radiomics outlier; `expected.json` lists them. All values invented.
- `make check` green: 303 backend + 32 frontend tests.

**Requests for other paths (integrator)**
- `frontend/src/api/schema.d.ts`: run `make gen-api` (API-16..18, 30..39, 50..54; CaseSummary/Project changes). Frontend contract differences vs the P2 proposal: API-16 GET/PATCH, API-17 POST/DELETE all return the full `Catalog` `{variables, excluded, derived, external, overrides, …}`; profile fields are `distinct`, `top[{value,n}]` (not `n_distinct`, `levels[{value,count}]`); DELETE of an in-use derived variable is 422 `validation` (no 409 slug for it); API-18 returns `{table, n_rows, n_matched, n_unmatched, unmatched_keys, duplicate_keys, conflicts}`.
- `backend/pyproject.toml`: added `scipy>=1.15` (Welch ANOVA). Optional: `"scipy.*"` in mypy `ignore_missing_imports` (then drop the `type: ignore[import-untyped]` on scipy imports); `trimesh` in `[radiomics]` if LBP3D is wanted (marked unavailable now).
- `backend/app/api/v1/__init__.py`: I registered `variables`, `curation`, `radiomics`, `dashboard` routers.
- `docs/domain/VARIABLES.md`: UIDs are excluded (VAR-09) although the type table's example says `series_uid → identifier`; raw phase fields (`phase`, `curated_phase`, `canonical_phase`) are core, not profiled; only `metadata.jsonl` rows are profiled (VOI catalog extras are not); `dominant` is missing if any source is missing, `tie` on equal maxima; bin is `v < t` → lower bin.
- `docs/domain/PROJECT_FORMAT.md`: `phase_mapping` is RAW(upper) → canonical; empty `phase_vocabulary` = open (`none`); PATCHed phase config applies at the next import.
- `docs/domain/CURATION.md` / `docs/backend/API.md` (curation): v2 target mapping (`SEG→seg`, `VOI_mask→voi_mask`, `phase_issue→phase`, `side_laterality_issue→side`, `{name}_mask→label:{value}` via label map, no scan_idx → `target=case`); queue holds item-level entries only; `curation_state.csv` columns = `STATE_COLUMNS` in `app/curation/service.py`; API-50 GET is a `Page`; API-51 takes `case_id`/`item_id`; API-53/54 return 201; API-54 needs `X-Reviewer`; imports > 500 events publish one `project.updated {fields:["curation"]}`.
- `docs/domain/RADIOMICS.md` / API.md (radiomics): profiles stored as `profiles/{hex}.json` (no colon); saving identical settings returns the existing profile (200); profile DELETE returns the remaining list; absent labels → `kind:"skipped"` rows in `errors.jsonl` + `counts.skipped` (not an error status); `run.json` extra `job_id`, `error`, `counts.skipped`; `units.jsonl` per-run plan for resume; engine major change → 409 `format-version-unsupported`; one radiomics run per project (409 `job-conflict`); `.npy` VOIs go through the `npy_convert` cache; schema-vs-table differences: `sigma` has no default, extra `label_channel` (Mask handling), engine defaults for Gradient/LBP2D/LBP3D/`start_level`, 107 default features.
- `docs/domain/ANALYSIS.md` / `docs/frontend/DASHBOARD.md`: export `GET …/analyses/{aid}/export?file=tidy|results|descriptives|spec`; color/split = `{kind: variable|phase|scope|side|label|curation_status, name}`; filters body `{var, phase, scope, side, label, status, item_ids}`; unit `{label, scope, phase, aggregate: first|mean|none}`; unconfirmed numeric-discrete variables are rejected for tests (422, confirm the type first); R×C Fisher = seeded permutation test; tidy export omits `sensitive` variables. `docs/adr/0012` mentions statsmodels — not used (SciPy only).

**Open issues**
- IBSI map codes and the extended phantom reference values were written from memory by the implementing agent; a wrong reference can only demote a feature to `not_defined`, but codes and the compliant list need a spot-check against the IBSI manual. IBSI CT phantom (TST-06 part 2) not run: dataset not available offline.
- Not done (not in this lane's tasks): IMP-09/API-15 full-hash job and PRJ-08/09 bundles (ROADMAP P6 first line).
- Views/analyses compute in a thread in the API process, not in a job worker; fine at fixture scale, revisit at 3,000 cases. `state.json` is rewritten on every curation append. Resume does not re-check input fingerprints. Worker-process (spawn) radiomics path is exercised only via inline threads in tests. UMAP untested (optional). `list_analyses` has no paging.
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

## 2026-09-24 · Step 2 integration · v3

**Done**
- Merged `lane/2-backend` (4 commits), `lane/2-shell` (1), `lane/2-viewer` (1). Only conflicts: this file (entries kept).
- Integration fixes: mounted API-25 mesh router, moved `mesh_test.py` → `backend/tests/test_mesh.py`, contract test exempts binary `…/mesh/{label}`, OpenAPI snapshot + `make gen-api` refreshed.
- Frontend vs real API: removed `group` handling in `api/http.ts` and the mock; added a Catalog → Variable[] adapter (profile `distinct/top` → `n_distinct/levels`, quantile count ↔ cut probabilities, ExternalReport → ExternalImportResult) with `api/http.variables.test.ts`; `phase_mapping` default; harness imports.
- Viewer: `vw` strings moved into `en.json` (temporary `features/viewer/i18n.ts` deleted); `configureViewer` wired from API-01 in `App.tsx`; NiiVue lazy-loaded (initial JS 632 → 300 KB gzip, NFR-07); NiiVue pinned to 0.69.0.
- Docs: implementation notes recorded in VIEWER, VARIABLES, PROJECT_FORMAT, CURATION, RADIOMICS, ANALYSIS, UI_SHELL, FE ARCHITECTURE, DEV_ENV; ADR-0012 and BE stack say SciPy only.
- `make fixtures && make check` green: 279 backend (3 PyRadiomics modules skipped, extra not installed here) + 76 frontend.

**For Step 3 lanes**
- P6-FE: remove `group` from `FeatureRow`/dashboard; build on API-38/39.
- P4-FE / P5-FE: backend contracts in CURATION.md / RADIOMICS.md §Implementation notes; regenerate types with `make gen-api`.
- Initial bundle is at the 300 KB limit: keep new heavy dependencies behind lazy boundaries.

## 2026-09-24 · P7-prep packaging · lane/3-packaging

**Done** (ROADMAP §P7 lines annotated; the remote parts stay for Step 4)
- `Dockerfile` (OPS-01/02/07): `node:22-slim` build → `python:3.12-slim` + `gcc`/`git` building `backend[radiomics]` into `/opt/venv` → `python:3.12-slim` runtime (no compiler). App source at `/app/backend` (`PYTHONPATH`), SPA at `/app/static`, `/workspace` mode 1777, `HOME=/tmp`, no fixed UID, `HEALTHCHECK` on API-01. The build runs `tools.spikes.ibsi_phantom_smoke` in the runtime stage, so a build only succeeds if PyRadiomics passes the IBSI phantom on Linux (ADR-0006): 20/20 on arm64.
- OPS-04: `Settings.container_mode` (`CONTAINER_MODE=1`, set by the image). Empty `ALLOWED_DATA_ROOTS` fails validation at startup, so the container exits 1 with `refusing to start: … (OPS-04)`. Tests: `backend/tests/test_config.py`.
- `scripts/container_app.py`: the container entry point. It mounts the SPA on `app.main.app` (`/assets` static, `index.html` fallback for client routes, `/api/*` never falls back) and runs uvicorn with HOST/PORT/LOG_LEVEL.
- `docker-compose.yml`, `.env.example`: one `.env`; compose pins the container-side HOST/PORT/WORKSPACE_ROOT and mirror-mounts `DATA_HOST` read-only (OPS-05). `ALLOWED_DATA_ROOTS` defaults to `DATA_HOST`; `RUN_AS` sets an optional UID:GID.
- `scripts/udocker-run.sh` (OPS-09): parses the same `.env` without eval (bash 3.2+), passes every key like `env_file`, applies the same overrides (HOST defaults to `127.0.0.1`), creates container `rw` on the first run, applies optional `UDOCKER_EXECMODE`, and has `--dry-run`. No `:ro` on udocker volumes (DEPLOYMENT udocker notes).
- TST-10: `scripts/container-smoke.sh` (Docker) and `scripts/container_smoke.py` (stdlib HTTP only; the same check for udocker via `--url`). Result on this Mac (colima, arm64): image 947 MB uncompressed (265 MB compressed; OPS-08 ≤ 1.5 GB); IBSI pass; OPS-04 refusal; runs as uid 12345; health; SPA and fallback; unknown `/api` path gives 404; import of the synthetic fixtures (index job in worker processes, 49 cases); one item's image with a Range 206 NIfTI header; Docker HEALTHCHECK healthy; 188 source files unchanged (R1). `docker compose up` served health, SPA and assets on 127.0.0.1:8097.
- `README.md`: Docker and udocker quick start.

**Requests for other paths (integrator)**
- `backend/app/main.py`: move the SPA mount from `scripts/container_app.py` (`mount_spa`) into the app factory (BE ARCHITECTURE says `main.py` owns SPA static serving), mount it when `STATIC_ROOT/index.html` exists, then point the Dockerfile `CMD` at `python -m uvicorn app.main:app` or keep the wrapper for its clean OPS-04 message.
- `Makefile`: `image: ; docker build -t radiology-workbench:$(VERSION) .` (VERSION default 3.0.0) and `udocker-run: ; scripts/udocker-run.sh`. Optionally add `container-smoke: ; scripts/container-smoke.sh`. `make lint`/`typecheck` don't cover `scripts/*.py`; I ran them by hand (ruff + `mypy --strict` pass), so consider adding `../scripts` to the backend ruff/mypy calls.
- `.gitignore`: add `/workspace/` (compose's default `WORKSPACE_HOST=./workspace`).
- `docs/ops/DEPLOYMENT.md` §Config: add `CONTAINER_MODE` (image sets `1`; empty `ALLOWED_DATA_ROOTS` then refuses to start, OPS-04). Host-side `.env` keys: `DATA_HOST`, `WORKSPACE_HOST`, `RW_VERSION`, `RUN_AS` (Docker), `UDOCKER_EXECMODE` (udocker). The image size is measured uncompressed (`du` of the rootfs), because `docker image inspect .Size` under the containerd store is the compressed size.
- `docs/ops/TESTING.md` TST-10: scripts `scripts/container-smoke.sh` (Docker) / `scripts/container_smoke.py --url … --root …` (udocker).
- ADR-0006: the "Not yet verified inside the Linux image" risk is resolved (linux/arm64). Re-check linux/amd64 on the build machine used for the server tar.
- `pyproject.toml` version is `3.0.0.dev0`, while the image tag is `3.0.0` (compose default `RW_VERSION`). Align when cutting the release.

**Open issues**
- Only linux/arm64 was built here. The remote server is likely amd64: build with `docker build --platform linux/amd64` (or on an amd64 host) before `docker save`, then rerun `scripts/container-smoke.sh`.
- This Mac's colima VM has no host mounts (`mounts: []`; `$HOME` contains a space), so Docker bind mounts of host paths show up as empty directories. The smoke therefore seeds named volumes with `docker cp`. `docker compose up` still serves the app, but DATA_HOST appears empty inside the container until colima mounts that path (`colima start --mount '<path>:w'`; user decision, not changed).
- The Docker CLI config here uses `credsStore: desktop` without Docker Desktop running, so pulls hang. I used a scratch `DOCKER_CONFIG` without a creds store for the builds (the user's config was not changed).
- udocker not exercised (Step 4): TST-10 under udocker, the execution-mode benchmark (P1 vs F3), whether udocker applies the image `ENV`/`WORKDIR`, and the `HOME` handling. The script passes `CONTAINER_MODE`/`HOST`/`PORT`/`WORKSPACE_ROOT` explicitly, so those don't depend on image ENV.
## 2026-09-24 · P5-FE radiomics form · lane/3-radiomics

**Done** (ROADMAP §P5 settings-form line ticked; phase row and the IBSI human check left to the integrator/owner)
- `features/radiomics/` rebuilt on the real API-30..37 contract (typed from `schema.d.ts` through a feature-local openapi-fetch client, `api.ts`; hooks in `hooks.ts` reuse `keys.schema/profiles/runs/run/runErrors`).
- Settings form generated from `GET /radiomics/schema` (RAD-01): nav = schema groups; filters with their params, availability (LBP3D shows the engine's reason) and 2D badge; feature classes with per-feature checkboxes, All/Defaults/None, deprecated marked (RAD-02); every option typed by `OptionSpec` (bool, int, float, enum, str, lists) with its description, the engine default shown next to it, and a reset-to-default button. Opens on `schema.defaults`; "Engine defaults" restores them. No IBSI names or codes in the GUI.
- Validation (RAD-04): `model/validate.ts` mirrors every §Validation rule plus type/constraint/unavailable, with the server's `loc` paths; API-31 runs debounced and is authoritative once its answer matches the form (Run disabled on its errors); issues show per field, per group (nav badge) and in the side list (click jumps to the group).
- Profiles (RAD-03): load (header select or view), save as, rename, duplicate, delete; header badge when the form matches a saved profile hash.
- Selection (RAD-05): all active / filter (phase, side, any variable with levels: categorical, numeric-discrete, constant) / explicit item-id list; scope; labels from the label map (default: first visible label). Non-CT warning when the `modality` variable has other levels and the selection does not restrict it to CT (RADIOMICS §Decisions).
- Estimate (RAD-11): items × labels = units, skipped count, time, sample errors; marked stale when settings or selection change.
- Runs view (RAD-06..10): newest first, status badge, live progress + ETA from the run's job (SSE-patched jobs cache), cancel (queued/running), resume (interrupted/cancelled), failures dialog (API-37, failed/skipped), CSV long/wide export links (API-36), completed runs open the dashboard tab.
- Settings tab is lazy (`LazySettingsEditor`, own chunk); initial JS ≈ 293 KB gzip (NFR-07).
- Tests: 87 vitest in the feature: `model/validate.test.ts` (every rule, 44), `settings.test.ts` (defaults, wire round trip, 21), `selection.test.ts` (14), `SettingsEditor.test.tsx` (defaults on open, client→server validation gating Run, LoG/2D rules in the UI, variable selection → estimate + run body + `X-Reviewer`, empty list, profile load/reset), `RadiomicsView.test.tsx` (progress/ETA, cancel, resume, failures, exports, `rad.*` key coverage). Fixture `model/fixtures/schema.json` = live PyRadiomics 3.1.1.dev111 schema.
- `make check` green: 318 backend (PyRadiomics installed, TST-06 + NFR-15 modules run) + 163 frontend.
- Real run on the fixtures through the UI (Vite 5175 → backend on `.fixtures/synthetic/Dataset900`): filter phase=NP + modality=CT, label kidney → estimate 46 units → Run → "Completed with errors", 41/46 ok, 107 features; the 5 failures are the injected fixture defects (no mask ×3, geometry mismatch, shape mismatch), logged per item (RAD-07). Rerun with the same settings + items: same `profile_hash`, 4,387 identical feature rows (NFR-15). **P5 exit met** apart from the IBSI human check line.

**Requests for other paths (integrator)**
- `frontend/src/i18n/en.json`: move `RAD_EN` from `features/radiomics/i18n.ts` into en.json under `rad` (or merge into `radiomics`), then delete `i18n.ts` and its import in `index.ts`. Now unused in `radiomics.*`: everything except `newRun` (command title); `radiomics.tabTitle` replaced by `rad.title`.
- `frontend/src/api/` (surface/http/types/mock): the prototype radiomics shapes (`SettingsSchema`, `Settings`, `Profile{name,hash}`, `Estimate`, `Issue{field,message}`, `RadiomicsRun`) do not match API-30..37. This feature no longer uses `api.schema/validate/estimate/saveProfile/startRun`, `useSchema`, `useSaveProfile`, `useStartRun`, `defaultSettings`, `validateSettings` (`api/mock/schema.ts`); please move `features/radiomics/api.ts` into the `Api` surface with the generated types (or delete the old members) and update the mock. Until then, in `VITE_API_MODE=mock` the settings tab shows the "engine not available" state.
- `frontend/src/api/keys.ts`: add a validation key; the feature uses `[...keys.schema(), 'validate', body]`.
- `frontend/src/api/http.ts` `runFeatures` (Measurements panel / P6-FE): API-36 JSON is a `FeaturesTable {columns, rows, total}`, not `{items}`, so `listOrEmpty` returns `undefined` ("Query data cannot be undefined" for `keys.features`).
- `frontend/src/features/explorer` (RAD-05 "current Explorer filter"): the explorer's filter store is not exported, so the form has its own variable filter. To offer "Use the current Explorer filter", export a read-only `useExplorerFilter()` from `features/explorer/index.ts`. Note API-33/34 `SelectionFilter.var` takes level lists only, so continuous ranges (`min..max`) cannot be sent; today the form tells users to bin them into a derived variable (VAR-06). Needs a decision: API support for ranges, or keep "bin first".
- `docs/domain/RADIOMICS.md` (P5-FE implementation notes): Duplicate = load a profile's settings and pre-fill "<name> copy"; since profiles are identified by settings hash, saving unchanged settings keeps the existing profile (toast says so). Default label = first visible label. Server validation is authoritative once current; the client rules only pre-flag.
- `docs/frontend/UI_SHELL.md`: settings tab layout (nav: Selection + schema groups with error badges; form; side panel: validation, summary, estimate, run) and the Radiomics view (runs with progress/cancel/resume/failures/export, profiles).

**Open issues**
- Draft settings are in memory only: a page reload reopens on the engine defaults (by design; profiles persist).
- The runs list relies on `job.finished` SSE to refresh a run's status; progress comes from the jobs cache (`useJobs`).
- IBSI map / extended phantom values still need the human spot-check (ROADMAP §P5); IBSI CT phantom not run.
## 2026-09-24 · P4-FE + P6-FE · lane/3-ui

**Done** (ROADMAP P4 both tasks, P6 FE tasks ticked; phase rows left to the integrator)
- Ownership (user decision, 2026-09-24): besides `features/{curation,dashboard}/**` and the variables/FeatureRow parts, this lane also owned the **curation (API-50..54) and analytics (API-38/39) sections** of `api/{types,surface,hooks,keys,http,mock}.ts`. Radiomics sections were left alone.
- `api/`: curation types from `schema.d.ts`; API-51 `CurationState` is flattened to `CurationStateRow[]` (item and case targets); events are paged, newest first; `X-Session-Id` + `session_id` go on writes; `queueCsv` (API-52 csv), `curationExports` (API-53), `importV2` (API-54). `FeatureRow` has no `group`; the API-36 `FeaturesTable` is adapted, and `feature` = full column name (`original_firstorder_Mean`), as API-38 uses. `dashboardView` (11 typed views), `listAnalyses/getAnalysis/createAnalysis/exportAnalysis`. SSE invalidates the dashboard views on curation/variable changes and on `project.updated {fields:["curation"]}`. Mock: 7 QC views from the seed (`api/mock/dashboard.ts`); the guided statistics, v2 import and analyses answer 503/404 in mock mode.
- Curation UI (CUR-01..14, UI-12):
  - The form's targets come from the label map; proposed phase comes from `phase_vocabulary`; `context.viewer` comes from `getViewerContext()` (VW-16).
  - History shows priority, source and proposal.
  - The queue editor shows absolute paths and downloads the server CSV; it can also write exports and import v2 CSVs, with a report.
  - The curation panels and queue are lazy; shortcuts use `curation/decision.ts`.
- Dashboard (DB-01..09, UI-14):
  - Dockview sub-panels per run, layout persisted in localStorage, with a Views menu.
  - Filter bar on visible variables, phase, scope, side, label and status.
  - Colour by variable, phase, scope, side, label or status, from palette tokens.
  - Brush selection is linked across views.
  - Every view exports PNG and CSV.
  - Item context menu: open, add to queue (CUR event), copy id.
  - Analysis panel: question → variable → confounder, unit and test override; shows test + reason, results (q, effect), descriptives, recommendations and ANA-09 exports. Result rows and recommendations focus their view (DB-09). The Measurements panel is lazy.
- Variables E2E vs the real API-16..18 (`e2e/variables.spec.ts`):
  - Continuous fields no longer show `top` as levels.
  - Problem `detail` is now shown in toasts.
  - The external report shows `duplicate_keys` and `conflicts`.
  - Types derive from the schema.
- Checks:
  - `make check` green: 318 backend + 90 frontend tests.
  - Playwright on Chromium + Firefox: TST-08 (`tst08-multiuser`), variables and smoke pass. `p2-flow` fails, see Open issues.
  - P6 exit checked in the browser on the fixtures run: `case_00062` is the top outlier and opens in one click. A 2-group (`score_bin`, Mann–Whitney) and a 3-group (`score3`, Kruskal–Wallis) comparison return q-values, with REC-VOLUME and REC-REDUNDANT triggered. The SciPy match itself is asserted by the backend TST-12.
  - NFR-07: initial JS 299.97 KB gzip. That's at the limit, but only thanks to lazy strings; see below.

**Requests for other paths (integrator)**
- `features/variables/**` (lane/2-shell code, changed here while fixing the E2E):
  - `VariablesView.tsx`: `isOverrideType` guard, error toasts carry the problem detail, and the dialogs are lazy (NFR-07).
  - `Dialogs.tsx`: the report shows duplicate keys and skipped columns.
- `i18n/`: new `en.lazy.json` + `lazy.ts`. Strings used only inside lazy chunks (dashboard, analysis, queue editor, curation form, history) load with them via `addResourceBundle`. `keys.test.ts` merges both files. Please record this in FE ARCHITECTURE §API layer or FE-11.
- `frontend/playwright.config.ts`: ports can be overridden (`E2E_API_PORT`, `E2E_WEB_PORT`) so lanes can run E2E side by side. New specs: `e2e/tst08-multiuser.spec.ts`, `e2e/variables.spec.ts`.
- `e2e/p2-flow.spec.ts` (lane/2-shell): it expects the old fixture counts (17 cases / 24 scan rows); the Step 2 fixtures give 50 / 89. It fails on the v3 HEAD as well. Please update the expected numbers.
- Backend `app/api/v1/events.py` (SSE): Firefox reports the stream "live" only at the first 15 s ping. Send a comment or `retry:` line right after opening, so events in the first seconds aren't missed. TST-08 waits for "live" to work around it.
- Explorer (DB-04): "Send to Explorer" needs an item-id filter in the explorer (`CaseFilter` / Project view). Until then it copies the ids and opens the first item.
- `api/hooks.ts` `useFeatures` fixed here: `iid = null` used the whole-run cache key.
- Unused i18n keys from the removed `group` UI: `search.group`, `image.group` (explorer/viewer namespaces).
- Docs for the owners:
  - DASHBOARD.md: views are dockview sub-panels with the Analysis panel as one of them. Mock mode serves only the QC views.
  - CURATION.md: the queue CSV comes from API-52 (not client-built).
  - API.md: API-50 POST accepts `X-Session-Id`.

**Open issues**
- NFR-07 has no headroom: HEAD was one 299.7 KB chunk; now entry + shared `shell` + `i18n` chunks = 299.97 KB. The next eager dependency needs a lazy boundary or a `manualChunks`/Rolldown chunking rule in `vite.config.ts` (integrator).
- P4 exit "exported queue CSV opens paths in 3D Slicer" is a human check. The CSV carries absolute image/mask paths (verified), but it hasn't been opened in Slicer.
- v2 import (API-54) is wired and typed but not exercised with a real v2 `curation_review.csv`.
- On the synthetic fixtures the outlier view flags every item at |z| 3.5 (near-constant features → tiny MAD); that's backend behaviour, fine for the exit criterion.
- Mock mode ignores `var` filters and variable colouring in the dashboard.

## 2026-09-24 · Step 3 integration · v3 (autopilot)

**Done**
- Merged `lane/3-packaging`, `lane/3-radiomics`, `lane/3-ui` into `v3`. Only conflicts: this file (entries kept).
- `npm install`, `make gen-api` (no diff), `make fixtures && make check` green: 288 backend (3 PyRadiomics modules skipped here) + 177 frontend.
- Applied small requests: radiomics strings moved from `features/radiomics/i18n.ts` into `en.json` (sidebar keys) and `en.lazy.json` (settings-form keys, loaded with the lazy chunk); unused `radiomics.*`, `search.group`, `image.group` removed; initial JS 299.5 KB gzip. Makefile `image` (VERSION, PLATFORM), `container-smoke`, `udocker-run`; lint + mypy now cover `scripts/*.py`; `/workspace/` ignored.
- Docs: DEPLOYMENT (`CONTAINER_MODE`, host keys, image size, colima/amd64 notes), TESTING TST-10 scripts, ADR-0006 (verified in the arm64 image), RADIOMICS/DASHBOARD/CURATION/API/UI_SHELL/FE ARCHITECTURE implementation notes; ROADMAP P4/P5/P6 ✅, P7 🟨 with follow-ups.

**Not done (listed in ROADMAP §P7)**
- SPA mount into `app/main.py`; radiomics `api.ts` into the `Api` surface + mock; `e2e/p2-flow.spec.ts` counts; SSE opening comment; explorer item-id filter / `useExplorerFilter()`; amd64 image; version alignment.

## 2026-09-24 · Step 3b integration · v3 (orchestrator + sub-agents A/B/C/D)

**Done** (ROADMAP §P6 hash/bundle line and §P7 Step 3 follow-ups ticked)
- A · backend: SPA served from `app/main.py` (`/assets`, `index.html` fallback, `/api/*` → 404); `scripts/container_app.py` only validates config (OPS-04 refusal) and runs uvicorn. SSE opens with `: open` + `retry: 3000` (API-40). `Item.modality` from input `modality` (VOIs inherit). Full-hash job API-15 → `index/hashes.json`, `image/mask.sha256` on API-21/22 (IMP-09). Bundles API-06 export (zip) / import (report, `needs_relink`) (PRJ-08/09, rules in PROJECT_FORMAT §Bundles). One version source: `backend/pyproject.toml` `3.0.0.dev0`; Makefile, compose, `.env.example`, udocker script follow it (`tests/test_version.py`). OpenAPI snapshot refreshed.
- B · radiomics API-30..37 on the shared `Api` surface (types from `schema.d.ts`, `keys.validation`); `features/radiomics/api.ts` and the prototype radiomics members deleted; mock serves the live schema, validation, profiles, estimate and runs, so the settings tab works with `VITE_API_MODE=mock`.
- C · Explorer item-id filter (`CaseFilter.itemIds`, "N items" chip) so "Send to Explorer" filters for real (DB-04); `useExplorerFilter()` + "Use the current Explorer filter" in the run selection (RAD-05, no ranges); viewer reads `item.modality` (VW-05); bundle export/import + "Compute full hashes" in the Projects view/Welcome/palette; `e2e/p2-flow` counts 50/89; new `e2e/projects-bundle.spec.ts`.
- D · `make image PLATFORM=linux/amd64` (qemu under colima, 234 s): IBSI 20/20 in the build; `make container-smoke` all checks pass (OPS-02/04/07/08, SPA + fallback, `/api` 404, import in workers, Range 206, R1 188 files unchanged). amd64 image 935 MB uncompressed, 277 MB compressed (arm64 947/265 MB).
- Integration fixes: `modality: null` default in `normalizeItem` (typed `Required<Item>`), harness reference item.
- Results on the v3 tip: `make fixtures && make check` green, 306 backend (3 PyRadiomics modules skipped in this venv) + 189 frontend vitest. Playwright 14/14 (Chromium 7, Firefox 7). Initial JS 289.1 KB gzip (gzip -9 of entry + static-import closure = the `modulepreload` set; 287.7 KB at 207e51f by the same method; the older 299.5 KB figure used a different method).
- Docs: API, DATA_MODEL, PROJECT_FORMAT, INPUT_METADATA, DEPLOYMENT, ADR-0006 (amd64 verified), BE/FE ARCHITECTURE, VIEWER, DASHBOARD, UI_SHELL, RADIOMICS, TESTING.

**Still open (unchanged scope)**
- Step 4 on the remote server (in maintenance): udocker, TST-10 under udocker, exec-mode benchmark, Dataset820, `docker save` → udocker, TST-05/09.
- Human checks: IBSI map vs manual; queue CSV in 3D Slicer; real v2 `curation_review.csv` import.
- User decision: continuous ranges in radiomics selection (API-33/34) vs "bin first".
- BE-12 (analytics views to job workers if slow at 3,000 cases).

**Open issues / follow-ups**
- Bundle import with a new `project_id` rewrites only `project.json`; other files that store the old id (e.g. radiomics `run.json`) were not audited.
- Bundle export zips in the API thread pool under the project lock; large `radiomics/runs` block writes to that project meanwhile.
- The OPS-04 refusal still carries pydantic's `Value error, ` prefix.
- Image tag has no architecture: building arm64 and amd64 locally under the same version overwrites the tag; `container-smoke.sh` has no `--platform`.
- DB-04 → Explorer is covered by vitest only (E2E needs a PyRadiomics run). Mock seed has no MR item and no bundles (503). Vite HMR re-registering shell registries logs duplicate-key warnings during E2E editing (not on clean runs).
- `SelectionForm.test.tsx` imports `features/explorer/store` directly (test-only boundary exception).

## 2026-09-24 · P7b docs (amendments ADR-0013..0017) · v3

**Done** (docs only, no code)
- ADR-0013 sources + Open mode + identity policy; ADR-0014 source/derived roots (R1 reworded in AGENTS.md; derived folder chosen by the user); ADR-0015 segmentation sets; ADR-0016 tasks/plugins (builtin + external runner through a file queue); ADR-0017 DICOM converter as a task + metadata analyzers. ADR-0002/0005/0006/0007 marked as amended.
- New owners: `domain/SOURCES.md` (SRC-), `domain/TASKS.md` (TSK-), `domain/DICOM_CONVERTER.md` (DCM-), `domain/ANALYZERS.md` (ANZ-). Updated: INDEX, VISION, GLOSSARY, NFR (17/18), INPUT_METADATA, DATA_MODEL, PROJECT_FORMAT (format_version 2, PRJ-13), RADIOMICS (RAD-13), CURATION (CUR-15, `seg_id`), VARIABLES, API (API-07/08/19/27/42..48/55, `actions[]`), BE/FE ARCHITECTURE, UI_SHELL (UI-17..20), VIEWER (VW-19..21), DASHBOARD, DEPLOYMENT (OPS-11..14), TESTING (TST-13..16), ROADMAP §P7b.

**Open issues**
- `backend/app/imaging/npy_convert.py` reads legacy `.npy` VOIs as `xyz` (`affine = diag(spacing)`, no transpose). If the v2 VOI writer saved SimpleITK arrays (`zyx`), today's conversion swaps axes: verify in P7b Wave 2 (SRC-12, IMP-10).
- The owner's converter is kept as read-only reference in `legacy/convert/`. `legacy/` is now git-ignored, `chmod -R a-w` and untracked (115 v2 files removed from the index; tag `legacy-reference` = last commit that tracks them; R9 in AGENTS.md). P7b Wave 3 ports it to `plugins/dicom/` + `plugins/analyzers/`. The CLI emits modality `MRI`; DCM-12 requires `MR`.
- Phase order (user decision): P7b → P7 remote part (Step 4, udocker) → P8 Electron.
- P7b runs in one sequential Claude shell session (prompt in AGENT_RUNBOOK §P7b). `plugins/nnunet/` is deferred until the amendments are stable (user decision 2026-09-24); the external runtime is proven with the fake `segment.threshold` plugin.

## 2026-09-24 · P7b Wave 1 (contracts) · v3

**Done** (ROADMAP §P7b Wave 1 ticked)
- `project.json` format_version 2 + migration 1 → 2 with `project.json.v1.bak` (PRJ-11): `path_roots[].role`, `segmentations` (one `imported` set, identity mapping over the label map), `default_seg`, `annotation_sources`. A v1 index record (`mask`) reads as `masks.imported`; items are stored with `masks` only.
- `Item.masks {seg_id: VolumeRef}`; the deprecated `mask` = `masks[default_seg]`, filled on load, never stored (kept for the whole phase). `?seg=` on API-24 (+HEAD) and API-25; API-27 list (with `n_items`, `is_default`) / PATCH (`name`, `label_mapping`); `default_seg` via API-03.
- Derived roots: `ALLOWED_DERIVED_ROOTS` (strict guard: empty allows none), startup refusal on overlap with `ALLOWED_DATA_ROOTS` (OPS-12, BE-15); PRJ-13 via API-05 `role: derived` (one per project, inside the derived guard, no overlap with the project's source roots → `roots-overlap`); API-10 `?role=derived`. Role-aware `PathResolver` (BE-02). Bundle root check uses the right guard.
- Problems carry `actions[]` (SRC-11); new slugs `unsupported-format`, `ambiguous-axis-order`, `geometry-mismatch`, `derived-root-required`, `roots-overlap`. `container_app.py` strips pydantic's `Value error, ` prefix (open issue from Step 3b).
- Task framework `app/tasks/` (TSK-01..10, API-42..47): manifest model (unknown keys refused), registry (builtin `app/radiomics/task.json` + `plugins/*/task*.json` with the builtin runtime; `PLUGINS_ROOT/*/task.json` external only; invalid ones listed), JSON-Schema-subset settings validation with defaults + `settings_hash`, selection (TSK-03), preflight with reasons and suggestions (TSK-04), estimate (builtin: 3-item sample in `.scratch/estimates/`, disposable; external: `seconds_per_item`), run protocol (`plugins/protocol.py` task side, `app/tasks/protocol.py` backend side), builtin runtime = the job manager's new *driver* jobs (a coroutine tails `progress.jsonl`; cancel = flag file; `waiting_for_runner` status + `job.status` SSE ready for Wave 4), run record `tasks/runs/{run_id}/run.json` + `items.jsonl`, resume skipping `ok` items, TSK-12 one run per (project, task), mask outputs → segmentation set (label mapping by name, unmatched → new label entries), `derived/runs.jsonl` ledger with sha256, index re-join of task sets on every rebuild. `radiomics.pyradiomics` served behind API-42..47 by an adapter over the radiomics service (RAD-13); API-30..37 unchanged.
- Fake plugin `plugins/threshold/` (`segment.threshold`, external manifest, `test_only`); Wave 1 tests run it through the builtin runtime.
- FE API layer: regenerated `schema.d.ts`; `Item.masks`, v2 project fields, `RootInfo.role`, `job.status`; `Api` gains `setDerivedRoot`, `setDefaultSeg`, `fsList(path, role)`, `listSegmentations`, `patchSegmentation`, `maskUrl(pid, iid, seg?)`, and the task members (`listTasks` … `taskRunOutputs`); the mock implements them (`mock/tasks.ts`: radiomics + threshold, a simulated segmentation run that registers a set).
- Image: `plugins/` copied to `/app/plugins` (`.dockerignore` allowlist); `pydicom` added to the dependencies for Wave 3.

**Results**: `make fixtures && make check` green: 327 backend (3 PyRadiomics modules skipped) + 192 frontend vitest (new `mock/tasks.test.ts`, one `maskUrl` test). Playwright 14/14 (Chromium 7, Firefox 7). Initial JS 289.5 KB gzip (entry + modulepreload set, gzip -9).

**Decisions**
- Plugins never import `app`; builtin and external tasks share one protocol. `plugins/` is importable through `pythonpath = ["..", "."]` (pytest), `mypy_path = ".."`, and `registry.ensure_importable` at startup (spawned workers inherit `sys.path`).
- `seg_id` slugs are lower-case `[a-z0-9][a-z0-9_-]{0,63}`; the default task set id is `{task-short}-{run_id[:8]}` lower-cased.
- Unknown modality (null) does not block `requires.modality` (v1 inputs often lack it).
- The builtin threshold variant is injected in tests (a manifest copy with `runtime: builtin`); only its external manifest ships.

**Open issues**
- Radiomics through API-45 ignores `selection.seg_id` until RAD-05 (Wave 4). The mock does not simulate resume of task runs.

## 2026-09-24 · P7b Wave 2 (sources) · v3

**Done** (ROADMAP §P7b Wave 2 ticked)
- `app/sources/`: formats (NIfTI, DICOM by `.dcm` or the `DICM` magic, NumPy; `.npz` refused with a reason), `detect` (API-19: candidates `metadata-v1` / `nifti-files` / `dicom.convert` / `open` with reason, counts, confidence, availability; nothing accepted → `unsupported-format` + `choose_another_path`), identity registry `sources/identity.json` (append-only merge; `table` strategy; slug rule), `nifti-files` adapter (pattern with named groups, `case_id_from` pattern/stem/sequential, mask conventions `seg/`, `labelsTr/`, `_seg`/`_mask`, modality, include list; channel 0000 only, `MRI` → `MR`).
- API-11 takes `{adapter, options}`; a NIfTI file as `root` = single-file import (SRC-05); `source.json` per snapshot (SRC-06); the preview adds `sample`, `unmatched`, `orphan_masks`, `ignored`; commit merges the draft registry. A folder without `metadata.jsonl` is refused with "No metadata.jsonl under the root; N NIfTI files found" and `actions: [import_as:nifti-files, open]` (SRC-11).
- SRC-08: `case_id` is a slug `[A-Za-z0-9_-]{1,64}` (parser, `item_id` regex).
- NumPy (SRC-12): sidecar `{name}.npy.json`, `reference_ref` decision, `zyx` transposed `(2,1,0)` before writing, spacing never permuted; `read_header(axis_order=)`; project VOIs honour a catalog `axis_order` (cache keyed by order); `ambiguous_axis_order` for other values.
- Open mode (API-07/08): in-memory sessions (LRU 32), worker probes (headers + label-map check), NIfTI streamed as-is, NumPy converted into `.scratch/open/{fp}.{order}/` (LRU purge at `CACHE_MAX_GB`), NumPy middle-slice PNG for the axis dialog, attach with shape + affine check (`geometry-mismatch` showing both geometries). DICOM items show "opens with the converter" until Wave 3.
- QC codes `unsupported_format` (a row names a non-NIfTI/NumPy file) and `ambiguous_axis_order` are emitted and covered by fixtures (case_00013 seg `.mha`; new VOI `case_00023.01.voi.R` with `axis_order: yxz`); warnings carry `seg_id` for mask codes.
- FE: `ProblemError.actions`, `lib/ProblemCard` (UI-18); import wizard with API-19 candidates, `nifti-files` options + parsed-name preview, file selection, prefill; `features/open` (lazy route `/open?path=`, "Open file or folder…" dialog on the home page and in the palette, axis-order dialog, attach, "Create project from this" → new project + prefilled wizard); viewer exports `StandaloneViewer`; task/segmentation hooks and SSE handling for `job.status` and `task` jobs.

**Results**: `make fixtures && make check` green: 345 backend (3 PyRadiomics modules skipped) + 196 frontend vitest. Playwright 18/18 (Chromium 9, Firefox 9; new `e2e/open-mode.spec.ts`, `p2-flow` detect step updated). Initial JS 296.2 KB gzip.

**Decisions**
- Registry scan indices are two digits (`01`), matching the fixtures and item ids (SOURCES example changed from `001`).
- Open-mode records use modality `OT` unless DICOM says otherwise (VW-05 percentiles); a label map alone is its own image and overlay with auto `label_{n}` colours.
- An import root that is a non-NIfTI file is `unsupported-format` (415) instead of `validation`.
- `tst08-multiuser` waits 15 s for B's refetched row (the SSE toast already proved delivery); it flaked 1/3 on Chromium at the 5 s default while thumbnails run after indexing.

**Open issues**
- Legacy VOI axis order vs the v2 VOI writer: needs `legacy/`, done in Wave 3 (R9).
- Initial JS is 296 KB of 300: the Tasks view (Wave 3) must be lazy; the import wizard could move to a lazy chunk if needed.
- Open sessions are lost on a server restart (the page shows `not-found`; reopening works).

## 2026-09-24 · P7b Wave 3 (converter + analyzers) · v3

**Done** (ROADMAP §P7b Wave 3 ticked)
- Docs first for the owner addendum: SRC-14 (Save as NIfTI…), SRC-15 (Add to project…), the three Open actions (SOURCES, UI-17, VW-21), API-09, ADR-0014 §4 line for `{derived root}/_open/`, PROJECT_FORMAT write rule; plus SOURCES §Imports (several sources per project).
- `legacy/convert/` (read-only) ported to `plugins/dicom/` (scan with geometry/advanced/MRI inspection, header rows, series → NIfTI through the ITK writer with `DICOMOrient(RAS)`, DICOM JSON sidecars without PixelData and > 64 KiB bulk, `anonymize: basic`, incremental `dataset/` with never-rewritten files, `MR` codes, single-file → 1-slice volume, standalone CLI) and `plugins/analyzers/` (phase, target, readiness; pure `analyze(rows, config)`, vocabulary mapping, compound/conflict → UNK low). Manifests `dicom.convert`, `analyzer.phase|target|readiness` (builtin).
- Task framework: `source` and `rows` inputs, job `context` (vocabulary, preset target profile), `dataset_dir`, `{t: total}` lines, image/sidecar outputs in the ledger, annotations copied to the run and activated where none is (ANZ-04), `metadata` outputs imported as source `task:{task_id}`, identity merged back (SRC-07), converter dry run as the estimate (DCM-06, `detail`).
- Index: the latest snapshot per `source_key` (SOURCES §Imports; plain re-imports unchanged), active annotations joined into phase resolution (`analyzer:{run_id}` after `phase`, before `phase_guess`) and into `extra` for other fields; reindex job on activation (API-48). Commit keeps an alias's role; previews use the derived guard for derived aliases.
- API: API-48 (annotations, sources, PUT activation), API-55 (CUR-15 mapping in CURATION), API-22 `dicom-tags`, API-09 (Save as NIfTI: default `{first derived root}/_open/{date}/`, `os.link` publish with `-1`, `-2` … so nothing is overwritten, optional anonymized sidecar), Open mode DICOM (one item per series, converted into `.scratch/open/`), API-11 `add` for SRC-15.
- FE: `features/tasks` (lazy Tasks view + task tab: selection, schema form, preflight with suggestions and the derived-folder prompt, estimate, run, runs with outputs and annotation activation); Image view DICOM tags on demand; Open toolbar Save as NIfTI… / Add to project… / Create project from this; wizard runs `dicom.convert` for DICOM sources and passes `add`.
- Fixtures: `.fixtures/synthetic/dicom/` (2 patients, 3 series, seeded UIDs, outside `Dataset900` so counts are unchanged); `tools/dicom_fixtures.py` also serves the tests.

**Results**: `make fixtures && make check` green: 391 backend (3 PyRadiomics modules skipped) + 198 frontend vitest. Playwright 22/22 (Chromium 11, Firefox 11; new `e2e/tasks-dicom.spec.ts`). Initial JS 297.7 KB gzip. TST-13 DICOM: the marker lands at RAS (−x, −y, z) of its LPS position (`tests/test_dicom.py`), NumPy half in Wave 2.

**Decisions**
- Several sources per project through `source_key` (needed for converter runs and SRC-15); the later import wins a duplicate `item_id` with `duplicate_row_identity`.
- In-app converter rows carry no `phase_guess`; the analyzers' annotations replace it (the CLI still writes the legacy fields). Case indices start at 0 like the CLI.
- `anonymize: basic` hashes identity keys, so `sources/identity.json` never holds PatientIDs for anonymized runs.
- SimpleITK moved to the core dependencies (the converter is builtin); PyYAML stays a CLI-only dependency.
- CUR-15 target mapping: `phase` for `curated_phase`, `seg` otherwise (documented in CURATION).

**Open issues**
- The legacy VOI axis-order check (IMP-10, SRC-12) cannot be done: `legacy/convert/` has no VOI writer and the task allows reading only that folder. Default stays `xyz`; a catalog `axis_order` overrides it.
- Without `anonymize`, converter rows (institution, dates, …) are snapshotted into `sources/` and `index/` and therefore travel in bundles, which conflicts with DCM-05's "never in bundles" for rows. Owner decision: strip PHI fields at bundle export, or require `anonymize` for projects that are shared.
- `anonymize: basic` covers a subset of Table E.1-1; the PHI review of a sidecar stays a human check.
- `legacy/` is now fully ported and can be deleted by the owner (not done here).
- Initial JS 297.7 of 300 KB: Wave 4 (VW-19 in the viewer) must keep new UI lazy or move the import wizard into a lazy chunk.
