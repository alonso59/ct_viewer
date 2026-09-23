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
