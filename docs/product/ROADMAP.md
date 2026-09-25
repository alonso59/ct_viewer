# Roadmap

Scope: phases, exit criteria, progress, v2 → v3 migration.
Read when: choosing what to work on next.
Depends: all docs (by ID).

Rules: work in phase order; mark tasks `[x]` when done; stop for user confirmation at every phase exit.
Order from 2026-09-24 (user decision): **P7b → P7c (done 2026-09-25) → pending plugins (VOI extractor, nnU-Net) → P7 remote part (Step 4: udocker, server checks) → P8 Electron**.

## Progress

| Phase | Title | Status |
|---|---|---|
| P0 | Documentation & ADRs | ✅ Done (2026-09-23) |
| P0.5 | UX design system & clickable prototype | 🟨 Built and approved 2026-09-23; curator/researcher walkthrough pending |
| P1 | Backend core: projects, import, index | ✅ 2026-09-23 (verified on `.fixtures/synthetic`; Dataset820 run deferred to P7 on the remote server, command in LANE_NOTES.md) |
| P1b | Study variables (backend): profiling, catalog, derived, external table; remove hard-coded `group` | ✅ 2026-09-24 |
| P2 | Frontend shell + explorer | ✅ 2026-09-24 |
| P3 | Viewer (NiiVue) | ✅ 2026-09-24 (synthetic reference; Dataset820 in P7) |
| P4 | Curation + multi-user sync | ✅ 2026-09-24 (human check pending: queue CSV in 3D Slicer) |
| P5 | Radiomics engine + settings + runs | ✅ 2026-09-24 (human check pending: IBSI map vs manual) |
| P6 | Dashboard + guided analysis | ✅ 2026-09-24 |
| P7 | Packaging: Docker + udocker, E2E, performance | 🟨 Docker image done (arm64 947 MB, amd64 935 MB, TST-10 pass on both); udocker + remote checks (Step 4) moved to the end, after P7b (user decision 2026-09-24) |
| P7b | Sources, derived data, tasks & plugins (ADR-0013..0017) | ✅ 2026-09-24 (Waves 1–4, exit criterion met; deferred: `plugins/nnunet/`; human checks pending: 3D Slicer orientation, PHI review) |
| P7c | Plugin platform, neutral projects, CT tools, curation & labeling plugins (ADR-0018..0022) | ✅ 2026-09-25 (Waves 1–5, exit criterion met: `e2e/p7c-exit.spec.ts`; pending plugins VOI extractor and nnU-Net follow) |
| P8 | Electron shell | ⬜ |

Step 0 bootstrap (legacy move, skeletons, Makefile, fixtures, `make check`): ✅ 2026-09-23.
Step 1 integrated 2026-09-23 · Step 2, Step 3 and Step 3b integrated 2026-09-24 (see LANE_NOTES.md).

## Lanes (parallel work; prompts in ops/AGENT_RUNBOOK.md)

A lane edits **only** the paths it owns. Anything it needs elsewhere goes into `LANE_NOTES.md` for the integrator.
Every lane may also append to `LANE_NOTES.md` and tick its own lines in this file.

| Step | Lane | Branch | Runs in | Owns |
|---|---|---|---|---|
| 0 | Bootstrap | `v3` | VS Code | Repo root, skeletons (done) |
| 1 | P0.5 design + prototype | `lane/1-design` | VS Code | `frontend/**` except `frontend/src/features/viewer/engine/**` |
| 1 | P1 backend core | `lane/1-backend` | Shell A | `backend/**` |
| 2 | P2 shell + explorer | `lane/2-shell` | VS Code | `frontend/**` except `features/{viewer,curation,radiomics,dashboard}/**` |
| 2 | P1b + P4-BE + P5-BE + P6-BE | `lane/2-backend` | Shell A | `backend/app/{variables,ingest,projects,curation,radiomics,analytics}/**`, `backend/tools/make_fixtures.py`, their routers in `backend/app/api/v1/`, their tests |
| 2 | P3 viewer | `lane/2-viewer` | Shell B | `frontend/src/features/viewer/**`, `backend/app/imaging/mesh*` |
| 3 | P4-FE + P6-FE | `lane/3-curation-dashboard` | VS Code | `frontend/src/features/{curation,dashboard}/**` |
| 3 | P5-FE radiomics form | `lane/3-radiomics-ui` | Shell A | `frontend/src/features/radiomics/**` |
| 3 | P7-prep packaging | `lane/3-packaging` | Shell B | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `scripts/udocker-run.sh`, `.env.example`, `README.md` |
| 4 | P7 remote verification | `v3` | Shell (remote server) | `scripts/**`, `docs/ops/DEPLOYMENT.md` (udocker notes), `LANE_NOTES.md` |
| P7b | Waves 1–4, sequential | `v3` | one Claude shell session (user decision 2026-09-24) | per wave, see §P7b |
| 5 | P8 Electron | `lane/5-electron` | VS Code | `desktop/**` |

Shared files that only the integrator edits: `Makefile`, `backend/pyproject.toml` dependency list, `frontend/package.json`/lockfile (lanes may add dependencies in their own branch; the integrator resolves lockfile conflicts at merge), `AGENTS.md`, `docs/INDEX.md`.

## Phases

### P0 — Documentation
- [x] Docs tree, router, ADR-0001..0010
- [x] User decisions recorded (2026-09-23): archive-only projects, phases NC/CMP/NP/EP/UNK, Slicer crosshair colours, v2 statuses, English i18n-ready, name, 500–3,000-case scale, defaults accepted
**Exit:** user approves the docs; open questions are resolved or explicitly deferred.

### P0.5 — UX design system & prototype (ADR-0010)
- [x] Design tokens: GitHub Dark + Light (`theme/tokens.css`), typography, spacing, radius (UI-11)
- [x] Custom CT icon set drawn to codicon rules (UI-15)
- [x] Wireframes: Welcome/home · Import wizard · Workbench with 2×2 case · Radiomics settings form · Dashboard · Correction queue
- [x] Clickable prototype: the real shell components (`shell/`) on a mock API layer seeded from the synthetic fixtures, with no backend. It becomes the P2 foundation rather than a throwaway.
- [ ] Walkthrough with a curator and a researcher: open case → review → mark status → next case; configure → run → open outlier
**Exit:** user approves the look, layout and the main flows; design changes are reflected in UI_SHELL.md.

### P1 — Backend core
- [x] Spikes: NiiVue mesh format (VW open questions), PyRadiomics on Python 3.12 (ADR-0006)
- [x] `core/` (paths, fsio, errors, ids, locks), config (OPS-03)
- [x] Projects + workspace (PRJ-01..06, 10, 11), fs browser (API-10)
- [x] Ingest: parsers, normalizer, indexer, validator (IMP-01..08, 10, 11)
- [x] Item streaming (API-23/24), job manager (BE-06), SSE bus (API-40)
- [x] Fixtures (TST-11), TST-01..03, TST-07
**Exit:** import the synthetic dataset and Dataset820 via API; warnings match the fixture defects; TST-07 green.

### P1b — Study variables, backend (ADR-0011)
- [x] Remove `group` from the ingest core (`ingest/models.py`, `normalize.py`, `cases.py`, `service.py` filter); keep it only as a variable when present
- [x] `variables/`: profiling + type/level inference (VAR-01..04), catalog overrides + tags (VAR-05, VAR-11), derived bin/recode/dominant (VAR-06), raw_metadata allowlist (VAR-08), exclusions (VAR-09)
- [x] External case-keyed table import (VAR-07); `index/variables.parquet`; `var.{name}` list filters (API-16..18)
- [x] Project presets (PRJ-12): `ccrcc`, `generic-ct`, `none`; phase mapping from `project.json`
- [x] Fixtures extended per TESTING §Variables; tests for every inference rule
**Exit:** the reference `metadata.jsonl` profiles as documented in VARIABLES.md (hb/lb continuous case-level, sn Review, no `group` assumed), with no code naming `hb/lb/sn`.

### P2 — Shell + explorer
- [x] Wire the P0.5 prototype shell to the real API: regions, tool bar, command palette, quick open (UI-01..08, 11, 13)
- [x] Workspace home, new project, import wizard (UI-04, IMP-01..03)
- [x] Project view with thumbnails (UI-08, IMP-12, API-26), Image/Labels/Search views, Problems panel (UI-09)
- [x] Variables view (UI_SHELL, VAR-*): catalog table, Review badges, overrides, derived variables, external table; replace the prototype's `group` filter/column/colour with variable-driven ones (VAR-10) (built on the mock; the real API-16..18 lands with lane/2-backend, LANE_NOTES)
- [x] Project creation offers a study preset (PRJ-12)
**Exit:** a user creates a project, imports data, browses cases, and shares a link that opens in a second browser.

### P3 — Viewer
- [x] NiiVue wrapper (`ViewerHandle`), layouts, MPR interaction (VW-01..08, 11..14)
- [x] 3D + meshes (VW-09, API-25), toolbar (VW-10)
**Exit:** NFR-01/02 met on the reference volume; all layouts work; the adaptive states render correctly.

### P4 — Curation
- [x] Reviewer identity, events, reducer, inspector form, shortcuts (CUR-01..08, 14, UI-12) — backend API-50/51 (lane/2-backend), FE lane/3-ui
- [x] Queue + exports + v2 import (CUR-09, 10, 13), live sync (CUR-11/12) — backend API-52..54 + SSE, FE + TST-08 (`e2e/tst08-multiuser.spec.ts`) lane/3-ui
**Exit:** TST-08 green; exported queue CSV opens paths in 3D Slicer.

### P5 — Radiomics
- [x] Engine adapter + schema + IBSI map (RAD-01, 12), validation (RAD-04)
- [x] Profiles, selection, estimate, runs, resume, outputs (RAD-03, 05..11)
- [x] Schema-driven settings form (RAD-01/02), engine defaults on open, live + server validation (RAD-04), profiles, selection by any variable (RAD-05), estimate, runs list with progress (lane/3-radiomics, LANE_NOTES)
- [ ] **Human check:** spot-check `backend/app/radiomics/ibsi_map.json` codes and the extended phantom reference values against the IBSI manual (written from memory by an agent); run the IBSI CT phantom (TST-06 part 2) once the dataset is available
**Exit:** TST-06 passes for the compliant features; a run over the fixtures is reproducible (NFR-15).

### P6 — Dashboard + guided analysis (ADR-0012)
- [x] Not built in P1, schedule with P5/P6: full-hash job (IMP-09, API-15) and project bundles (PRJ-08/09) — Step 3b (backend + Projects view UI, `e2e/projects-bundle.spec.ts`)
- [x] Analytics views (API-38), dashboard tab, filters, click-through, linked selection (DB-01..07) — FE lane/3-ui (DB-04 "send to Explorer" filters the explorer by item id since Step 3b)
- [x] Measurements panel for the active item (UI-14)
- [x] Backend `analytics/`: analysis spec, unit (one row per case), test choice, FDR, effect sizes, descriptives, REC rules, export (ANA-01..09, API-39), TST-12
- [x] Analysis panel + Group comparison / Association / Balance check views (DB-08/09)
- [x] Remove the leftover `group` from `FeatureRow` and the dashboard; colour/split by variable
- [x] End-to-end check of the Variables view against the real API-16..18 (`e2e/variables.spec.ts`)
**Exit:** an injected fixture defect is visible as an outlier and opens in the viewer in one click; a two-group and a three-group comparison on a derived variable return tests matching SciPy, with q-values and at least one triggered recommendation.

### P7 — Packaging
- [ ] Dockerfile, compose, `udocker-run.sh`, execution-mode benchmark (OPS-*) — Dockerfile, compose, `udocker-run.sh` done (lane/3-packaging); execution-mode benchmark on the remote server (Step 4)
- [ ] TST-05, TST-09, TST-10; README quick start — TST-10 under Docker and README quick start done (lane/3-packaging); TST-10 under udocker, TST-05, TST-09 in Step 4
- [ ] Move analytics views/analyses from API-process threads to job workers if slow at 3,000 cases (BE-12) — `Item.modality` done in Step 3b (VW-05 reads it); BE-12 still open
- [ ] Deferred from P1: Dataset820 import check on the remote server (`tools.import_check`, LANE_NOTES.md); rerun `tools.spikes.ibsi_phantom_smoke` inside the Linux image (build stage needs `gcc`); add a container-mode signal so an empty `ALLOWED_DATA_ROOTS` refuses to start (OPS-04) — IBSI smoke in the image and OPS-04 `CONTAINER_MODE` done (lane/3-packaging); Dataset820 check in Step 4
- [ ] Build the image for the server's architecture (`make image PLATFORM=linux/amd64` if the server is amd64), rerun `make container-smoke`, then `docker save` → udocker — amd64 build + TST-10 under Docker done (Step 3b, IBSI 20/20); `docker save` → udocker in Step 4
- [x] Follow-ups from Step 3 (LANE_NOTES.md), done in Step 3b: move the SPA mount from `scripts/container_app.py` into `app/main.py` (BE ARCHITECTURE); move `features/radiomics/api.ts` into the `Api` surface and update the mock; update `e2e/p2-flow.spec.ts` counts (50 cases / 89 scans); SSE sends a comment right after opening (Firefox "live" delay); explorer item-id filter for DB-04 and an exported `useExplorerFilter()` for RAD-05; align `pyproject` version with the image tag
- [ ] **Decision (user):** radiomics selection by continuous ranges (`min..max`) in API-33/34, or keep "bin into a derived variable first"
- [ ] **Human checks:** open the exported correction-queue CSV in 3D Slicer (P4 exit); import a real v2 `curation_review.csv` (API-54)
**Exit:** the same image runs under Docker locally and udocker remotely; NFR targets are met.

### P7b — Sources, derived data, tasks & plugins (ADR-0013..0017)
- [x] ADR-0013..0017 accepted; contracts in SOURCES, TASKS, DICOM_CONVERTER, ANALYZERS and the owning docs; R1 reworded (2026-09-24)
- [x] Wave 1 · contracts (2026-09-24; LANE_NOTES "P7b Wave 1"): `format_version` 2 migration (`path_roots.role`, `masks`, `segmentations`, `default_seg`, `annotation_sources`); `ALLOWED_DERIVED_ROOTS` + overlap check (OPS-11/12, BE-15); PRJ-13; generic task framework (manifests, protocol, builtin runtime, TSK-01..10) with radiomics as `radiomics.pyradiomics` + API-30..37 aliases (RAD-13); `?seg=` on API-24, API-27; FE API layer
- [x] Wave 2 · sources (2026-09-24; LANE_NOTES "P7b Wave 2"; the legacy VOI axis check moves to Wave 3, which may read `legacy/`): detect (API-19), `nifti-files` adapter, single-file import, identity registry (SRC-01..08); Open mode for NIfTI, label maps and NumPy (API-07/08, VW-21; DICOM in Open mode comes with the converter in Wave 3); NumPy axis rules (SRC-12) and a check of the legacy VOI axis order (IMP-10); `actions[]` on every refusal (SRC-11, UI-18); FE import wizard + Open
- [x] Wave 3 · converter + analyzers (2026-09-24; LANE_NOTES "P7b Wave 3"; the legacy VOI axis-order check stays open: `legacy/convert/` has no VOI writer): port `legacy/convert/` (reference only, R9) → `plugins/dicom/`, split `plugins/analyzers/` (phase, target, readiness); task wrappers; input = a dataset root, one patient/series folder, or a single DICOM file (DCM-01, DCM-10); DICOM in Open mode through the convert stage into `.scratch/` (SRC-13); sidecars + `anonymize` (DCM-04/05, NFR-17); incremental dataset (DCM-07); CUR-15; annotations + activation (ANZ-04, API-48); generic Tasks view + preflight (UI-17..20); TST-13, TST-16; **owner addendum 2026-09-24:** Open mode offers exactly Save as NIfTI… (SRC-14, API-09, `{derived}/_open/{date}/`, write-once, no overwrite, optional `anonymize: basic`), Add to project… (SRC-15) and Create project from this; docs first (SOURCES, ADR-0014 §4, PROJECT_FORMAT write rules, API, UI-17, VW-21); TST-15 save cases
- [x] Wave 4 · external runtime (2026-09-24; LANE_NOTES "P7b Wave 4"; VW-19 shows one set at a time): queue + `scripts/rw-runner.py` (TSK-11, BE-14); fake `segment.threshold` plugin (TST-14, CI); segmentation-set selector (VW-19) and `seg_id` in radiomics selection (RAD-05) and curation
- [ ] **Deferred until the P7b amendments are stable (user decision 2026-09-24):** `plugins/nnunet/` (`dataset.json` labels, `_0000` staging, batches; ADR-0016 §6) and its human check on a GPU host (one item and a batch)
- [ ] **Pending (user decision 2026-09-24):** a VOI extractor plugin that crops VOIs from a segmentation (reference code to be provided); it also settles the legacy `.npy` VOI axis order (IMP-10, SRC-12; default `xyz` until then). Keep `legacy/` until the owner decides to delete it (fully ported otherwise)
- [ ] **Human checks:** a converted DICOM series opened next to the original in 3D Slicer (orientation); anonymized sidecar reviewed for PHI
**Exit:** a NIfTI folder, a single NIfTI, a single DICOM file and a standalone segmentation open in Open mode; a DICOM folder converts into a project with sidecars and active phase annotations; the fake plugin (CI) adds a segmentation set through the external runner; a radiomics run on a chosen `seg_id` records it; TST-07/13/14/15/16 green.

### P7c — Plugin platform & neutral projects (ADR-0018..0022, accepted 2026-09-24)
Owner decisions (2026-09-24): first-party plugins only in v3; `metadata.jsonl` is the converter's artifact (contract v1, no phase/curation/group fields), plugin data in layers; plugins installed per workspace and enabled by default (management later); projectless converter output in `{derived}/_datasets/{name}/`; default modality per project and a view-only link: yes.
- [x] Docs (2026-09-24): ADR-0018..0022 accepted; PLUGINS.md (PLG-) and LABELING.md (LBL-) are owners; TASKS (TSK-01/13), PROJECT_FORMAT (v3, PRJ-14..18), API (API-03 ETag, 28, 49, 56..62), INPUT_METADATA, DICOM_CONVERTER (DCM-13/14), ANALYZERS, VARIABLES (VAR-12), CURATION, VIEWER (VW-17, 22..25), UI_SHELL (UI-22..26), FE/BE ARCHITECTURE, DATA_MODEL, VISION, GLOSSARY, TESTING (TST-17..20) updated
- [x] Wave 1 · platform (2026-09-25; LANE_NOTES "P7c Wave 1"): `plugin.json` + registry activation (PLG-01..08), Plugin Library view, repackage converter, analyzers, radiomics, dashboard/analysis and curation as plugins (no behaviour change); `PLUGINS_ROOT` limited to the host runner of first-party plugins
- [x] Wave 2 · neutral projects (2026-09-25; LANE_NOTES "P7c Wave 2"; the viewer applies `display` in Wave 4, VW-25): New project = name (+ optional default modality); packs (ccRCC pack) applied from Project settings; settings tabs (General, Display incl. DICOM window and convention, Labels incl. `.ctbl` / ITK-SNAP / `dataset.json` import, Data, Plugins); `If-Match` on API-03; view-only link `/v/{token}`; `format_version` 3 migration
- [x] Wave 3 · converter & metadata (2026-09-25; LANE_NOTES "P7c Wave 3"): clean converter output in the app and the CLI (no `phase_guess`, `curated_*`, `group`, `curation.csv`); legacy fields still accepted on import; layers model + dataset table export; converter overlay window; workspace tasks and `_datasets/`; phase analyzer chained by default
- [x] Wave 4 (2026-09-25; LANE_NOTES "P7c Wave 4"; the flaky E2E was fixed in Wave 2) · CT tools in the case tab and Open mode (VW-22/23, ADR-0021 Must + Should), including numeric W/L, DICOM header window, HU probe, header info, slab MIP/MinIP, distance/angle/ROI; Close for projects and Open sessions (UI-24); fix the flaky cold-run E2E `tasks-dicom.spec.ts` (LANE_NOTES)
- [x] Wave 5 (2026-09-25; LANE_NOTES "P7c Wave 5") · core event store; Curation & QC plugin on it (no data change); Labeling table plugin (LBL-01..08)
- [x] **Owner addendum 2026-09-25 · viewer field of view** (2026-09-25; LANE_NOTES "P7c addendum · field of view"): independent zoom/pan per view, link toggle off by default (VW-06); per-view Fit to window button + `F` (VW-26); global Reset unchanged (VW-10); `fitView(tile)` on `ViewerHandle`; Vitest + one Playwright check (zoom one view, the others unchanged; fit restores it, slice index kept)
**Exit:** a user converts a DICOM folder without a project from the converter overlay, opens the dataset with the full CT tool set, creates a neutral project from it, applies the ccRCC pack, labels cases in a patient-level table and a CT-level table, curates items, and shares a view-only link that cannot write; every plugin is reachable from the Library; `make check`, Playwright and NFR-07 green.

### Pending plugins (after P7c, before Step 4)
- [ ] VOI extractor plugin: crops VOIs (image + mask, per side) from a segmentation set; **requires a segmented mask**; reference code from the owner; settles the legacy `.npy` VOI axis order (SRC-12, IMP-10)
- [ ] nnU-Net segmentation plugin (`plugins/nnunet/`, external runtime, GPU), deferred from P7b; also owns nnU-Net dataset naming on import/export (`imagesTr/`/`labelsTr/`, `_0000` channels), removed from core `nifti-files` (ADR-0024)

### P8 — Electron
- [ ] Thin shell + preload bridge for native folder dialogs (ADR-0001)
**Exit:** the desktop app connects to a local Docker backend and a forwarded remote one.

## Migration from v2

| v2 asset | v3 action |
|---|---|
| `legacy/backend/app/services/converter_metadata.py`, `qc_validator.py`, `path_resolver.py` | Reuse logic in `ingest/` and `core/paths` |
| `legacy/…/volume_cache`, `slice_renderer`, PNG slice API, `slice_cache` | Remove (replaced by client rendering) |
| `legacy/…/review_apply.py`, `metadata_sync.py` (source mutation) | Remove (conflicts with R1); keep as a reference for export shapes |
| `legacy/…/mesh_generator.py` | Reuse in the `imaging/` mesh job |
| `legacy/frontend` (MUI pages) | Rewrite; reuse the W/L presets and label palette |
| `.webui/curation_review.csv` | Import via CUR-13 |
| `docs/archive/v2/*`, `legacy/**` | Frozen reference only; `legacy/` is git-ignored and read-only since tag `legacy-reference` (R9); delete it after P7b Wave 3 has ported `legacy/convert/` (ported 2026-09-24; deleting the folder is left to the owner) |
