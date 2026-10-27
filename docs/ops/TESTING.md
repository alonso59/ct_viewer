# Testing

Scope: test layers, fixtures, safety and compliance tests, CI gates.
Read when: writing tests or adding a feature (every requirement ID should map to ≥1 test that names it; see "Requirement IDs in tests").
Depends: all domain docs.

| ID | Layer | Tooling | Covers |
|---|---|---|---|
| TST-01 | Backend unit | pytest | services, reducer (CUR-08), path guards (BE-02) |
| TST-02 | Parsers | pytest + hypothesis | IMP input variants, phase normalization table |
| TST-03 | API contract | pytest + httpx; OpenAPI diff | API-*, problem+json slugs |
| TST-04 | Frontend unit | Vitest + Testing Library | features, stores, schema-driven form (RAD-01/04); the API binding over responses recorded from the real backend (§Mock API) |
| TST-05 | E2E | Playwright (Chromium, Firefox) | import → explore → view → curate → radiomics → dashboard |
| TST-06 | IBSI compliance | pytest | Engine output vs IBSI digital phantom + CT phantom reference values, within the IBSI-published tolerances; results stored with `ibsi_map_version` |
| TST-07 | Source immutability | pytest / E2E hook | SHA-256 of every fixture source file before and after the full E2E suite must match (R1); derived writes only inside run folders / append-only datasets. E2E: `e2e/tst07.ts` (global setup) + `e2e/tst07-teardown.ts` |
| TST-08 | Multi-user | Playwright (2 contexts) + Vitest | CUR-11 SSE sync, CUR-12 last-writer-wins; the API-40 handler on a real QueryClient (first-load race, per-set rows, reconnect `reset`: `api/liveState.test.ts`) |
| TST-09 | Performance | scripted bench | NFR-01..05 on the reference volume |
| TST-10 | Container smoke | `scripts/container-smoke.sh` (Docker), `scripts/container_smoke.py --url … --root …` (udocker; `./rw smoke`), `scripts/udocker-selftest.sh` (udocker simulated in Docker) | Image boots under Docker and udocker; health OK; one item viewable; native DICOM lifecycle via `python -m tools.dicom_image_smoke --evidence <empty-dir>` |
| TST-11 | Fixtures | `make fixtures` | Synthetic dataset (below) |
| TST-12 | Statistics | pytest vs SciPy/statsmodels reference | ANA test choice, p/q/effect sizes, each REC rule triggered by a fixture |
| TST-13 | Orientation | pytest | A synthetic DICOM series and NumPy `xyz`/`zyx` arrays with an asymmetric marker (known L/A/S voxel) convert to NIfTI with the marker at the expected RAS mm (NFR-18) |
| TST-14 | Task protocol | pytest | Builtin and external runtimes on the fake `segment.threshold` plugin: queue, runner claim, progress, cancel, resume, `waiting_for_runner`, mask registration as a segmentation set |
| TST-15 | Sources | pytest + hypothesis | `nifti-files` patterns, single-file import, identity registry stability across incremental imports, Open mode (NIfTI, DICOM file, every opened file is an image, attach NIfTI only + mismatch), nnU-Net names not special (ADR-0024), refusal `actions[]` |
| TST-16 | Analyzers | pytest | Phase text/timing/conflict cases, target profiles, readiness codes, activation reindex (ANZ-*) |
| TST-17 | Plugins | pytest + Vitest | Manifest validation, Library status reasons, contributions registered, pending plugins not openable (PLG-*) |
| TST-18 | View-only link | pytest + Playwright | API-60 serves reads only, never returns `project_id` or an absolute server path (any body, jobs included), rotation revokes the old token; the UI hides every editing control (PRJ-17, UI-26) |
| TST-19 | Labeling | pytest + Playwright | Tables at case/scan/item level, cell events, two-browser live sync, `lbl.*` variables, CSV import report, edit / delete / restore of tables and columns (LBL-*) |
| TST-20 | Metadata ownership | pytest | Converter output (app + CLI) has no phase/curation/group/selection fields; legacy files with them still import; dataset-table export joins active layers (DCM-13, ADR-0020) |
| TST-21 | nnU-Net segmentation | pytest + GPU-host acceptance | SEG-* with a fake official CLI: profile validation, staging, disjoint GPU parts, bounded workers, merge, partial failure, cancel/resume, geometry rejection, provenance, immutable sources and segmentation-set indexing; on `john-gpinedo`, one item and a 2–4 GPU batch with the `Dataset220_KiTS2023` profile |
| TST-22 | Supervised-job verification gates | pytest + CI + host preflight | ADR-0034: fail-closed required backend/environment protections, bounded workers, hermetic fake processes, first-failure diagnostics and enforced pre-publication checks; further P7g cases/gates in SEGMENTATION_JOB_TEST_PLAN.md |
| TST-23 | Effective local/server containment | opt-in Linux host pytest | OPS-16..19: bounded owned services, actual source-write/network restrictions and native IPC, inherited confinement, descendant cancel/crash cleanup, unaffected sentinel and verified generation release. `make test-host` runs serially and never skips missing prerequisites; normal container CI does not certify host effects |
| TST-24 | Durable DICOM lifecycle | pytest + real-process restart/cleanup tests + Playwright + benchmark | SRC-18/19, DCM-15..19, TSK-16, BE-16, UI-28, API-69; DICOM_JOB_TEST_PLAN.md owns D01–D35/U01–U12/B01–B08/P01–P06 and actual evidence remains separate from plan acceptance |

TST-21 commands: `cd backend && .venv/bin/pytest -q tests/test_nnunet.py`; real host acceptance: `.venv/bin/python -m tools.nnunet_acceptance --items 1 --gpus 0 --gpu-cap 1 --backend server`, then `--items 2 --gpus 0,6 --gpu-cap 2 --backend local`. Authorized idle devices only; full source/model hashes and geometry/index checks are required. Current evidence is owned by SEGMENTATION_JOB_TEST_PLAN.md.

ADR-0025/0026 (2026-09-25): `tests/test_phase.py` (PHS-*), `tests/test_dataset_export.py` (`dataset.jsonl` one line per item with the effective phase and layers; VAR-09 sensitive fields only on request, CSV and JSONL); `tests/test_labeling.py::test_reference_column_mirrors_a_comparable_variable` (LBL-09 / VAR-13) and `tests/test_api_variables.py` (`phase.effective` comparable); `tests/test_sidecars.py` (IMP-15: tag mapping, partial marker, derived root only, off by default); Vitest `features/phase/{model,PhaseButtons}.test.ts(x)`, `plugins/labeling/TableEditor.test.tsx` (LBL-09 read-only reference); Playwright `p7c-exit` (view-only refuses a phase write).

CUR-16 / API-66: `tests/test_recycle.py` covers full metadata audit, cleanup, shared projects, stale confirmations, rollback, discovery and restart recovery; Vitest `features/viewer/RecycleScan.test.tsx` covers explicit confirmation and view-only hiding. These tests use disposable copies; the TST-07 source-immutability journey does not invoke CUR-16.

IMP-16: `tests/test_voi_paths.py` covers legacy field aliases, dataset/catalog-relative and absolute paths, ambiguity, canonical precedence, missing files and root/symlink escapes; `tests/test_api_ingest.py::test_legacy_voi_paths_preview_commit_and_reindex` checks preview → index → reindex with NumPy geometry and byte-identical source/snapshot catalogs.

## Rules

- Backend tests are parallel-safe: no shared writable path outside `tmp_path`, except the module-scoped repo fixture of `test_e2e_import.py` (one worker per module keeps it single).
- Dead code: `make deadcode` (knip: entries beyond the Vite / Vitest / Playwright plugins are listed in `frontend/knip.json`, exports used only in their own file are allowed; vulture ≥ 80 over `app tools tests scripts plugins` with `backend/vulture_allowlist.py` for verified false positives).
- Coverage: `make coverage` (a report, not a gate).
- Which test covers which ID: `make trace`.

## Mock API (TST-04)

`VITE_API_MODE=mock` (Vitest and the standalone prototype) binds the HTTP binding (`api/http.ts`) to a replay of `frontend/src/api/mock/recorded.json` (`api/mock/replay.ts`): real responses of one demo scenario on the fixtures, recorded by `make record-mock` (`backend/tools/record_mock.py`: in-process app, inline jobs, a temporary workspace). A request is answered by the recording with the same method, path, query (paging dropped) and JSON body, else the same request with any body, else (GET) the same path without its query; anything else is a `not-recorded` problem (501). The mock computes nothing and a write changes no later answer, so component tests assert the request they send and leave the effect to the backend's tests. Re-record after an API change or a fixture change (`make record-mock` also records CUR-16 on a disposable dataset; `cd backend && .venv/bin/python -m tools.record_recycle` refreshes only those exchanges); the recording redacts the project id and every host path (`/data`, `/workspace`, `/derived`), and fails if a host path is left. `npm run mock:slices` writes the viewer placeholder's mid-slices (`api/mock/slices.json`). Vitest runs in `node` by default; files that need a DOM start with `// @vitest-environment jsdom`; the replay has no latency under Vitest.

Requirement IDs in tests (AUD-A4-01): a new or touched test names the IDs it covers in its docstring, `describe`/`test` title or header comment; `make trace` writes the ID → test citation report into `build/trace/` (a report, not a gate).

Import wizard UX (owner addendum 2026-09-25): Vitest `features/import/patternSuggest.test.ts` (SRC-17: stems, groups only when the sample shows them, no guess below half, highlight segments).

Feature test files: TST-13 `tests/test_dicom.py` (series from `tools/dicom_fixtures.py`; NumPy half in `tests/test_sources.py`) · TST-14 `tests/test_tasks.py` (builtin, RAD-05, curation `seg_id`), `tests/test_runner.py` (the real `scripts/rw-runner.py` as a subprocess), `e2e/runner.spec.ts` · TST-15 `tests/test_sources.py`, `e2e/open-mode.spec.ts` · TST-16 `tests/test_analyzers.py` · TST-17 `tests/test_plugins.py`, Vitest `plugins/host.test.ts`, `features/library/LibraryView.test.tsx` · TST-18 `tests/test_projects_v3.py`, Vitest `features/projects/settings/*.test.ts(x)`, `shell/registry.test.ts`, `e2e/view-only.spec.ts` · TST-19 `tests/test_labeling.py`, Vitest `plugins/labeling/*.test.ts(x)`, `e2e/labeling.spec.ts` · TST-20 `tests/test_metadata_ownership.py`, `tests/test_open_convert_once.py`, Vitest `plugins/dicom/ConverterOverlay.test.tsx`, `e2e/converter.spec.ts` · CT tools `tests/test_ct_tools.py`, Vitest `features/viewer/{model/measure,display}.test.ts`, `api/liveState.test.ts`, `e2e/ct-tools.spec.ts` · format v2 / derived roots `tests/test_format_v2.py`.

Test constraints: external-runtime tests and the E2E backend point `PLUGINS_ROOT` at a temp dir with a symlink to `plugins/threshold/` (never at `plugins/` itself); the E2E backend gets a temporary `ALLOWED_DERIVED_ROOTS`; PyRadiomics is not thread-safe, so the engine serializes extraction within a process (inline jobs run units in threads); tests that need the ccRCC defaults create projects with `packs: ["ccrcc"]`.

## Dataset820 import check (P1, real data)

`cd backend && .venv/bin/python -m tools.import_check --root /ABS/PATH/TO/Dataset820 --sha256 --workers 4` prints preview counts, index time, case count, warnings per code and `sources_changed` (must be `[]`); exit 0 = pass. It sets `ALLOWED_DATA_ROOTS` to the root and uses a throwaway workspace (`--workspace DIR` keeps it). `--sha256` reads every byte before and after; drop it for a quick run. On the remote server run `make setup-backend VENV=$CONDA_PREFIX` first and use `$CONDA_PREFIX/bin/python`.

## Synthetic fixture dataset (TST-11)

Generated, not committed: `make fixtures` writes `.fixtures/synthetic/` (generator `backend/tools/make_fixtures.py`, oracle `expected.json`). It is small (64³–128³ int16 volumes, 3 labels as spheres/ellipsoids) and deterministic (fixed seed).
It contains `metadata.jsonl`, `phase.json`, `voi/voi_catalog.jsonl` and a legacy `.npy` VOI, plus **deliberate defects**:
missing SEG, shape mismatch, ambiguous phase, ambiguous side, duplicate identity, missing file, a `.mha` seg (`unsupported_format`), a VOI with `axis_order: yxz` (`ambiguous_axis_order`).
Every IMP-08 warning code must be produced by at least one fixture row.
DICOM, NIfTI and NumPy fixtures (generated, no real data; DICOM in `.fixtures/synthetic/dicom/`: 2 patients, 3 series, seeded UIDs): a synthetic DICOM series (pydicom, CT, with study/series descriptions and contrast times for the phase rules; one PHI-looking fake name to test anonymization), one Enhanced multi-frame file, a NIfTI-only folder in nnU-Net naming with a `labelsTr/` mask, a standalone label map, and NumPy pairs in `xyz` and `zyx` with sidecars.
Variables (VAR/ANA): no `group` field; case-level numeric study variables with ~50 % missing and one compositional pair; a `numeric-discrete` variable; vendor strings needing recode; one MRI scan; enough healthy cases (≥ 30) for group tests. Never copy values from real metadata into fixtures.

## E2E specs (Playwright, Chromium + Firefox)

All in `frontend/e2e/`, real backend on the fixtures (TST-05, TST-07 hook). Ports: `E2E_API_PORT`, `E2E_WEB_PORT`. Specs share `e2e/helpers.ts` (`api` through the web server's proxy, fixture paths, `importedProject`) and `e2e/openMode.ts`; the servers and temp folders are in `e2e/servers.ts`. The global teardown removes the run's temp workspace, derived and plugins folders unless `E2E_KEEP=1` (AUD-A0-05). Dev loop (AUD-A6-18): `make e2e SPEC=… PROJECT=…`, `make e2e-one SPEC=…` (one browser), `make e2e-servers` + `E2E_REUSE=1` (reuse running servers on fixed folders), `E2E_BUILD=1` (the production build through `vite preview`, for a nightly run).

| Spec | Covers |
|---|---|
| `g1-open` · `g2-dicom` · `g3-review` · `g4-radiomics` | Journeys G1..G4 (VISION §Journeys, REL-02) |
| `network-allowlist` | NFR-12 / FE-06 / BE-11 (REL-06): no request or WebSocket outside the app origin across Home, Open mode, a case tab, radiomics, queue, settings and a dashboard; a foreign one is aborted and fails |
| `smoke` · `p2-flow` | App boots; P2 exit (49 cases / 89 scan rows on the fixtures, AUD-A2-08; share link in a second browser) |
| `p7c-exit` | The P7c exit criterion in one journey (`docs/archive/v3/ROADMAP-done.md` §P7c) |
| `tst08-multiuser` · `labeling` · `view-only` | TST-08 · TST-19 · TST-18 |
| `open-mode` · `tasks-dicom` · `converter` · `runner` | SRC-09..14 (TST-15) · DCM + UI-20 · UI-25 / TSK-13 · TST-14 external runner |
| `segmentation-lifecycle` | SRC-20 / PRJ-07/15 / VW-19 / UI-13: dedicated segmentation editor, individual label and whole-set Remove/Restore/Reimport, reindex, separate catalog edits, default inspector and persistent keyboard/mouse section toggles. |
| `converter-recovery` | TST-24 / B04–B06/B08: private real API and native writer callback, cancel/API SIGKILL, same-run resume, fresh browser context, two tabs, theme and keyboard minimize/restore. `e2e/dicomRecovery.ts` proxies the UI to `backend/tests/dicom_browser_server.py`; shared E2E services stay alive. |
| `variables` · `projects-bundle` | API-16..18 · IMP-09 hash job, PRJ-08/09 export → import, archive / restore |
| `ct-tools` · `viewer-fov` | VW-17/22/23, UI-24 · VW-06/26 |

## Verification gates and CI wiring

Verify full backend dependencies and actual WebGL2 before the browser lane. In Linux containers, CPU-only rendering uses Chromium SwiftShader and Firefox with existing Xvfb: `E2E_XVFB=1 LIBGL_ALWAYS_SOFTWARE=1 LP_NUM_THREADS=2 xvfb-run -a make e2e`. Firefox headless on this host lacks WebGL2; a page-loading pass cannot certify the viewer. Node stays container-only remotely. Makefile explicitly selects Ruff's backend/root settings so external parent configuration cannot affect CI formatting.

Local verification: lint + typecheck · TST-01..04 (pytest in parallel, pytest-xdist) · dead code (`make deadcode`: knip + vulture) · OpenAPI/TS types up to date (`make api-types`) · initial JS within NFR-07 (`make bundle-size`) · requirement tables (`make reqs`) · TST-07 · image build. The `make check` prerequisites are independent, so `make -j4 check` runs them in parallel; on shared hosts, bound workers and numerical-library threads (SEGMENTATION_JOB_TEST_PLAN.md).
The publication workflow depends on reusable `.github/workflows/verify.yml`: isolated full checks and serial safety regressions gate the Chromium/Firefox matrix. Each browser runs every spec on an independent runner/workspace using `Dockerfile.verify`; product-image verification/export waits for both. This wiring is covered by TST-22; actual CI execution is separate evidence. No scheduled nightly lane is configured; remaining TST-06/09/10 release/host obligations stay explicit.
The image job also runs `tools.dicom_image_smoke` as an arbitrary non-root UID before exporting the tested image. The packaged command uses disposable synthetic roots and its own API: queued API SIGKILL/restart, cancel/resume, two native DICOM conversions checked against an independent physical-coordinate oracle, and durable Open restoration after another API restart. It hashes sources and committed outputs, refuses nonempty evidence roots, and retains synthetic failure logs. Run the same command inside the exported image under udocker without binding host code. This smoke does not certify active-pixel crashes or cross-container ownership; those remain DICOM_JOB_TEST_PLAN.md obligations.
The image gate additionally runs `scripts/dicom-namespace-smoke.py <image> <new-absolute-evidence-dir>` on two non-root Docker containers with distinct PID namespaces and one private allocation pool. It stops an owned pixel worker before dispatch, cancels a foreign waiter, kills only the pinned owner dispatcher, verifies parent-death cleanup and foreign recovery refusal, then resumes from the owning namespace and completes two native volumes. Source bytes, independent landmarks, pool release and unrelated container survival are checked. No GPU is exposed. This checks cross-namespace admission/recovery at the dispatch barrier; active-native death remains covered separately by the real API/browser cases.

The verification image installs `xauth` and checks `xvfb-run -a true` during its build, so missing display-startup dependencies fail before the test suite.

P7f/P7g: `SEGMENTATION_JOB_TEST_PLAN.md` owns the measured baseline, implementation evidence, remaining cases, environment gates and failure-investigation policy. Use `make test-env FULL_TESTS=1` to fail before collection on missing full dependencies; `make test-runner PYTEST_WORKERS=0 FULL_TESTS=1` exercises safety serially. Full pytest coverage also refuses skipped tests (`--require-full` or `RW_TEST_REQUIRE_FULL=1`).

PRJ-19 / API-67: `tests/test_dataset_projects.py` verifies local state/output layout, archive/restore, reopening a moved dataset, managed-path guards, independent bundles and legacy compatibility; Vitest `features/import/NewProjectDialog.test.tsx` and `features/projects/OpenDatasetDialog.test.tsx` cover folder selection using responses from `tools.record_dataset_projects` on disposable data.

VW-09/27 WebGL regression: with the viewer fixture harness running (DEV_ENV), run `node src/features/viewer/harness/check-3d.mjs` from `frontend/` (Node in the container on remote hosts). `HARNESS_URL`, `CHROME` or `CDP_URL` select the server/browser. Compares visible 2D screenshots across mask-only, deferred proxy refresh and 3D image planes; checks slider tracking, CT restoration and WebGL errors.

VW-09 3D pan regression: `node src/features/viewer/harness/check-3d-pan.mjs` uses the same fixture harness/browser settings as `check-3d.mjs`. Tests actual right-button drags at DPR 1 and 2, screen-pixel tracking, unchanged 2D slices/crosshair/camera scale, pointer release, wheel zoom, left-drag orbit, Fit/Reset recentring and retained 2D right-drag W/L.
