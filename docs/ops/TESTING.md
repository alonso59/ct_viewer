# Testing

Scope: test layers, fixtures, safety and compliance tests, CI gates.
Read when: writing tests or adding a feature (every requirement ID should map to ≥1 test).
Depends: all domain docs.

| ID | Layer | Tooling | Covers |
|---|---|---|---|
| TST-01 | Backend unit | pytest | services, reducer (CUR-08), path guards (BE-02) |
| TST-02 | Parsers | pytest + hypothesis | IMP input variants, phase normalization table |
| TST-03 | API contract | pytest + httpx; OpenAPI diff | API-*, problem+json slugs |
| TST-04 | Frontend unit | Vitest + Testing Library | features, stores, schema-driven form (RAD-01/04) |
| TST-05 | E2E | Playwright (Chromium, Firefox) | import → explore → view → curate → radiomics → dashboard |
| TST-06 | IBSI compliance | pytest | Engine output vs IBSI digital phantom + CT phantom reference values, within the IBSI-published tolerances; results stored with `ibsi_map_version` |
| TST-07 | Source immutability | pytest / E2E hook | SHA-256 of every fixture source file before and after the full E2E suite must match (R1); derived writes only inside run folders / append-only datasets. E2E: `e2e/tst07.ts` (global setup) + `e2e/tst07-teardown.ts` |
| TST-08 | Multi-user | Playwright (2 contexts) | CUR-11 SSE sync, CUR-12 last-writer-wins |
| TST-09 | Performance | scripted bench | NFR-01..05 on the reference volume |
| TST-10 | Container smoke | `scripts/container-smoke.sh` (Docker), `scripts/container_smoke.py --url … --root …` (udocker) | Image boots under Docker and udocker; health OK; one item viewable |
| TST-11 | Fixtures | `make fixtures` | Synthetic dataset (below) |
| TST-12 | Statistics | pytest vs SciPy/statsmodels reference | ANA test choice, p/q/effect sizes, each REC rule triggered by a fixture |
| TST-13 | Orientation | pytest | A synthetic DICOM series and NumPy `xyz`/`zyx` arrays with an asymmetric marker (known L/A/S voxel) convert to NIfTI with the marker at the expected RAS mm (NFR-18) |
| TST-14 | Task protocol | pytest | Builtin and external runtimes on the fake `segment.threshold` plugin: queue, runner claim, progress, cancel, resume, `waiting_for_runner`, mask registration as a segmentation set |
| TST-15 | Sources | pytest + hypothesis | `nifti-files` patterns, single-file import, identity registry stability across incremental imports, Open mode (NIfTI, DICOM file, label map, attach mismatch), refusal `actions[]` |
| TST-16 | Analyzers | pytest | Phase text/timing/conflict cases, target profiles, readiness codes, activation reindex (ANZ-*) |
| TST-17 | Plugins | pytest + Vitest | Manifest validation, Library status reasons, contributions registered, pending plugins not openable (PLG-*) |
| TST-18 | View-only link | pytest + Playwright | API-60 serves reads only, never returns `project_id`, rotation revokes the old token; the UI hides every editing control (PRJ-17, UI-26) |
| TST-19 | Labeling | pytest + Playwright | Tables at case/scan/item level, cell events, two-browser live sync, `lbl.*` variables, CSV import report (LBL-*) |
| TST-20 | Metadata ownership | pytest | Converter output (app + CLI) has no phase/curation/group/selection fields; legacy files with them still import; dataset-table export joins active layers (DCM-13, ADR-0020) |

P7c files (Wave 4): `tests/test_ct_tools.py` (Open-mode DICOM window + tags, converter window facts); Vitest `features/viewer/model/measure.test.ts`, `features/viewer/display.test.ts`, `api/liveState.test.ts`; Playwright `e2e/ct-tools.spec.ts` (the tool set in Open mode on DICOM and in a case tab, header info with DICOM tags, measurements, Close for both).

P7c files (Wave 3): TST-20 in `tests/test_metadata_ownership.py` (app converter rows and the CLI without study fields and without `curation.csv`; legacy `curated_phase`/`phase_guess`/`group` still resolve; dataset table joins the analyzer and curation layers, Parquet provenance; workspace run → `_datasets/` → neutral project with the phase layer, write-once; workspace task errors); `tests/test_open_convert_once.py` (the flaky E2E's root cause); Vitest `plugins/dicom/ConverterOverlay.test.tsx`; Playwright `e2e/converter.spec.ts` (overlay → dataset → Create project from this).

P7c files (Wave 2): `tests/test_projects_v3.py` (neutral create, If-Match 428/412, packs list/apply/reindex without data loss, TST-18 view mirror + rotation + revoke, bundle without token, migration 2 → 3); Vitest `features/projects/settings/{labelFiles,ProjectSettings}.test.ts(x)` (label imports, conflict → reload and reapply, packs, view link) and `shell/registry.test.ts` (UI-26 filtering); Playwright `e2e/view-only.spec.ts` (TST-18 UI half). Tests that relied on the old ccRCC default create projects with `packs: ["ccrcc"]`.

P7c files (Wave 1): TST-17 in `tests/test_plugins.py` (shipped manifests valid, validation errors, status reasons, API-49 with and without `?project=`, `PLUGINS_ROOT` first-party only) and Vitest `src/plugins/host.test.ts`, `src/features/library/LibraryView.test.tsx`.

P7b files (Wave 4): TST-14 external half in `tests/test_runner.py` (the real `scripts/rw-runner.py` as a subprocess: waiting → claim → progress → set registration, SIGTERM cancel, resume, a crashing task, a lost runner, single claim); `e2e/runner.spec.ts` runs the fake plugin through the runner from the Tasks tab (the E2E backend gets `PLUGINS_ROOT` = a temp dir with a symlink to `plugins/threshold/`). RAD-05 and curation `seg_id` in `tests/test_tasks.py`. PyRadiomics is not thread-safe, so tests that run it in inline (threaded) mode use one unit at a time.

P7b files (Wave 3): TST-13 DICOM half + converter, sidecars, anonymize, incremental runs, activation, CUR-15, Open DICOM, Save as NIfTI (TST-15), Add to project in `tests/test_dicom.py` (synthetic series from `tools/dicom_fixtures.py`); TST-16 in `tests/test_analyzers.py`; `e2e/tasks-dicom.spec.ts` (Open a DICOM file + save; convert a DICOM folder from the Tasks tab). The fixtures add `.fixtures/synthetic/dicom/` (2 patients, 3 series, seeded UIDs). The E2E backend gets a temporary `ALLOWED_DERIVED_ROOTS`.

P7b files: TST-14 builtin half and the task framework `tests/test_tasks.py` (the external half with the runner in Wave 4); TST-15 `tests/test_sources.py` + `e2e/open-mode.spec.ts`; TST-13 NumPy half in `tests/test_sources.py`; format v2 / derived roots `tests/test_format_v2.py`. External-runtime tests point `PLUGINS_ROOT` at a temp dir with a symlink to `plugins/threshold/` (never at `plugins/` itself).

## Synthetic fixture dataset (TST-11)

Generated, not committed: `make fixtures` writes `.fixtures/synthetic/` (generator `backend/tools/make_fixtures.py`, oracle `expected.json`). It is small (64³–128³ int16 volumes, 3 labels as spheres/ellipsoids) and deterministic (fixed seed).
It contains `metadata.jsonl`, `phase.json`, `voi/voi_catalog.jsonl` and a legacy `.npy` VOI, plus **deliberate defects**:
missing SEG, shape mismatch, ambiguous phase, ambiguous side, duplicate identity, missing file, a `.mha` seg (`unsupported_format`), a VOI with `axis_order: yxz` (`ambiguous_axis_order`).
Every IMP-08 warning code must be produced by at least one fixture row.
P7b fixtures (generated, no real data): a synthetic DICOM series (pydicom, CT, with study/series descriptions and contrast times for the phase rules; one PHI-looking fake name to test anonymization), one Enhanced multi-frame file, a NIfTI-only folder in nnU-Net naming with a `labelsTr/` mask, a standalone label map, and NumPy pairs in `xyz` and `zyx` with sidecars.
Variables (VAR/ANA): no `group` field; case-level numeric study variables with ~50 % missing and one compositional pair; a `numeric-discrete` variable; vendor strings needing recode; one MRI scan; enough healthy cases (≥ 30) for group tests. Never copy values from real metadata into fixtures.

## E2E specs (Playwright, Chromium + Firefox)

`smoke`, `p2-flow` (50 cases / 89 scan rows on the fixtures), `variables` (API-16..18), `tst08-multiuser` (TST-08), `projects-bundle` (IMP-09 hash job, PRJ-08/09 export → import). Ports: `E2E_API_PORT`, `E2E_WEB_PORT`.

## CI gates

Lint + typecheck · TST-01..04 · OpenAPI/TS types up to date · TST-07 · image build.
TST-05/06/08/09/10 run nightly or before a release tag.
