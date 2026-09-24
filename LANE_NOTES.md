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
