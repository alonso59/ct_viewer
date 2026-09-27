# Testing

Scope: test layers, fixtures, safety and compliance tests, CI gates.
Read when: writing tests or adding a feature (every requirement ID should map to ≥1 test that names it; see "Requirement IDs in tests").
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
| TST-08 | Multi-user | Playwright (2 contexts) + Vitest | CUR-11 SSE sync, CUR-12 last-writer-wins; the API-40 handler on a real QueryClient (first-load race, per-set rows, reconnect `reset`: `api/liveState.test.ts`) |
| TST-09 | Performance | scripted bench | NFR-01..05 on the reference volume |
| TST-10 | Container smoke | `scripts/container-smoke.sh` (Docker), `scripts/container_smoke.py --url … --root …` (udocker) | Image boots under Docker and udocker; health OK; one item viewable |
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

ADR-0025/0026 (2026-09-25): `tests/test_phase.py` (PHS-*), `tests/test_dataset_export.py` (`dataset.jsonl` one line per item with the effective phase and layers; VAR-09 sensitive fields only on request, CSV and JSONL); `tests/test_labeling.py::test_reference_column_mirrors_a_comparable_variable` (LBL-09 / VAR-13) and `tests/test_api_variables.py` (`phase.effective` comparable); `tests/test_sidecars.py` (IMP-15: tag mapping, partial marker, derived root only, off by default); Vitest `features/phase/{model,PhaseButtons}.test.ts(x)`, `plugins/labeling/TableEditor.test.tsx` (LBL-09 read-only reference); Playwright `p7c-exit` (view-only refuses a phase write).

Fix batch FB1 (PHI and view-only boundary, 2026-09-26): `tests/test_view_redact.py` (AUD-A5-03: redactor rules, SSE/JSON forwarding, every view route and `/view/{t}/jobs` without pid or server path); `tests/test_bundle.py::test_export_turns_import_roots_and_warning_paths_into_alias_refs` (A5-02 residual); `tests/test_dicom.py::test_save_as_nifti` (A2-15 pseudonym); `tests/test_fs_api.py`, `tests/test_imaging.py::test_failure_logs_carry_alias_refs_not_paths`, `tests/test_metadata_ownership.py` (A5-16); Vitest `api/view.test.ts`, `features/open/navigate.test.ts`; Playwright `open-mode` (A1-19: `/open/{sid}`, reload, ended session), `view-only` (no pid or path in any read), `tasks-dicom` (wizard anonymize); Open-mode specs start from `e2e/openMode.ts`.

Fix batch FB3 (navigation and keyboard, 2026-09-26): Vitest `shell/keybindings.test.ts` (UI-12 dispatch: route scope, viewer context without DOM focus, typing, menus and modals, view-only; AUD-A2-02/A2-09/A6-04), `shell/registry.test.ts` (every view, panel tab and task has a command; menus from categories; route scopes), `shell/paletteMatch.test.ts` (ranking on the real commands), `shell/EditorArea.test.ts` (FE-04 history entries), `state/navContext.test.ts`, `features/explorer/navigate.test.ts` (navigation context, next unreviewed), `features/projects/share.test.ts`, `app/App.test.tsx` (palette on the home); pytest `tests/test_projects_api.py::test_archive_refused_while_a_job_runs` (AUD-A5-10); Playwright `e2e/g3-review.spec.ts` (G3 start: A → Alt+↓ → A, next unreviewed, queue navigation context, Back, Explorer reveal, title-bar entry points, About), `projects-bundle` (archive / restore).

Fix batch FB4 (Open mode, import and converter, 2026-09-26): pytest `tests/test_open_service.py` (AUD-A6-05 service: attach from a sibling `seg/` / `labelsTr/` of a single file, still guarded; refusal actions; modality from dataset rows, AUD-A2-03/07/10), `tests/test_sources.py::test_single_file_with_attached_mask_and_quiet_warnings` (A2-12), `tests/test_metadata_ownership.py` (A2-04 relative sidecar refs, A2-13 per-series dry run, A2-07 no-DICOM refusal), `tests/test_open_convert_once.py`; Vitest `features/open/model.test.ts` (mask carried, attach start), `features/import/{FolderBrowser,patternSuggest}.test.ts(x)` (A1-16, converter naming), `features/viewer/readout.test.ts` (VW-08), `features/viewer/engine/loadGate.test.ts` (A5-13), `lib/{ProblemCard,format}.test.ts(x)`, `plugins/dicom/ConverterOverlay.test.tsx` (series plan, name clash); Playwright journey specs `e2e/g1-open.spec.ts` (G1) and `e2e/g2-dicom.spec.ts` (G2), plus `open-mode`, `converter` (no-DICOM refusal) and `ct-tools` (case error cards).

Fix batch FB5 (radiomics, dashboard and analysis, 2026-09-26): pytest `tests/test_radiomics_api.py` (TSK-04/RAD-07 skips with plain causes and no `geometryTolerance` advice, AUD-A2-05; RAD-08 resume refuses changed inputs, A5-14; PHS-03 phase joined at read time with `phase_at_run`, A5-04), `tests/test_tasks.py::test_task_set_maps_the_labels_the_run_wrote` (A5-12), `tests/test_api_ingest.py::test_cases_filters` (one count definition, A2-08), `tests/test_projects_service.py::test_list_summary`; the TST-12 statistics tests are unchanged; Vitest `lib/format.test.ts` and `lib/NumberInput.test.tsx` (A3-04 / A3-15 number format, parsing `,` and `.`, units, middle ellipsis), `plugins/radiomics/RadiomicsView.test.tsx` (failures then skips, labelled actions), `i18n/keys.test.ts` (one run-state vocabulary, A3-10); Playwright journey spec `e2e/g4-radiomics.spec.ts` (G4, AUD-A6-01: settings → selection by variable + segmentation set → estimate → run → failures and skips → dashboard → outliers top 10 with `case_00062` first → viewer in one click → group comparison on a derived variable → wide CSV export).

Fix batch FB7 (docs conformance, 2026-09-27): Playwright `e2e/network-allowlist.spec.ts` (NFR-12, REL-06); pytest `tests/test_cache_budget.py` (OPS-03 `CACHE_MAX_GB`, AUD-A4-16), `tests/test_udocker_run.py` (OPS-09: the dry run equals the compose file's environment and mounts), `tests/test_sources.py::test_modality_codes_mri_is_mr` (DCM-12); Vitest `theme/theme.test.ts` (UI-11), `shell/EditorArea.test.ts` (FE-04 tabs per project). `make api-types` (in `make check`) regenerates `schema.d.ts` from the current OpenAPI and diffs (FE-03).

Requirement IDs in tests (AUD-A4-01): a new or touched test names the IDs it covers in its docstring, `describe`/`test` title or header comment; `make trace` writes the ID → code/test citation report into `build/trace/` (a report, not a gate).

Import wizard UX (owner addendum 2026-09-25): Vitest `features/import/patternSuggest.test.ts` (SRC-17: stems, groups only when the sample shows them, no guess below half, highlight segments).

P7c files (Wave 5): TST-19 in `tests/test_labeling.py` (levels, progress, typed cells, LWW, history, rename/hide, column edits clearing min/max/unit, table delete → 404 + no layers/variables → restore (LBL-10), `lbl.*` variables and layers, CSV import report, export, view-only, live events); Vitest `plugins/labeling/{model,TableEditor}.test.ts(x)`; Playwright `e2e/labeling.spec.ts` (two browsers, live sync, variable, view-only read-only).

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

All in `frontend/e2e/`, real backend on the fixtures (TST-05, TST-07 hook). Ports: `E2E_API_PORT`, `E2E_WEB_PORT`.

| Spec | Covers |
|---|---|
| `g1-open` · `g2-dicom` · `g3-review` · `g4-radiomics` | Journeys G1..G4 (VISION §Journeys, REL-02) |
| `network-allowlist` | NFR-12 / FE-06 / BE-11 (REL-06): no request or WebSocket outside the app origin across Home, Open mode, a case tab, radiomics, queue, settings and a dashboard; a foreign one is aborted and fails |
| `smoke` · `p2-flow` | App boots; P2 exit (49 cases / 89 scan rows on the fixtures, AUD-A2-08; share link in a second browser) |
| `p7c-exit` | The P7c exit criterion in one journey (`docs/archive/v3/ROADMAP-done.md` §P7c) |
| `tst08-multiuser` · `labeling` · `view-only` | TST-08 · TST-19 · TST-18 |
| `open-mode` · `tasks-dicom` · `converter` · `runner` | SRC-09..14 (TST-15) · DCM + UI-20 · UI-25 / TSK-13 · TST-14 external runner |
| `variables` · `projects-bundle` | API-16..18 · IMP-09 hash job, PRJ-08/09 export → import, archive / restore |
| `ct-tools` · `viewer-fov` | VW-17/22/23, UI-24 · VW-06/26 |

## CI gates

Lint + typecheck · TST-01..04 · OpenAPI/TS types up to date (`make api-types`) · requirement tables (`make reqs`) · TST-07 · image build.
TST-05/06/08/09/10 run nightly or before a release tag.
