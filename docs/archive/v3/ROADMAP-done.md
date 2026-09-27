# Roadmap: finished phases (archive)

Scope: task lists and exit criteria of the finished v3 phases and amendments, moved verbatim from `product/ROADMAP.md` on 2026-09-27 (AUD-A7-11), plus the done items of phases that still have open ones.
Read when: never, unless a task says so (frozen history; results in LANE_NOTES.md, open work in ROADMAP).
Depends: product/ROADMAP.md.

### P0 — Documentation
- [x] Docs tree, router, ADR-0001..0010
- [x] User decisions recorded (2026-09-23): archive-only projects, phases NC/CMP/NP/EP/UNK, Slicer crosshair colours, v2 statuses, English i18n-ready, name, 500–3,000-case scale, defaults accepted
**Exit:** user approves the docs; open questions are resolved or explicitly deferred.

### P0.5 — UX design system & prototype (ADR-0010), done items
- [x] Design tokens: GitHub Dark + Light (`theme/tokens.css`), typography, spacing, radius (UI-11)
- [x] Custom CT icon set drawn to codicon rules (UI-15)
- [x] Wireframes: Welcome/home · Import wizard · Workbench with 2×2 case · Radiomics settings form · Dashboard · Correction queue
- [x] Clickable prototype: the real shell components (`shell/`) on a mock API layer seeded from the synthetic fixtures, with no backend. It becomes the P2 foundation rather than a throwaway.

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

### P5 — Radiomics, done items
- [x] Engine adapter + schema + IBSI map (RAD-01, 12), validation (RAD-04)
- [x] Profiles, selection, estimate, runs, resume, outputs (RAD-03, 05..11)
- [x] Schema-driven settings form (RAD-01/02), engine defaults on open, live + server validation (RAD-04), profiles, selection by any variable (RAD-05), estimate, runs list with progress (lane/3-radiomics, LANE_NOTES)

### P6 — Dashboard + guided analysis (ADR-0012)
- [x] Not built in P1, schedule with P5/P6: full-hash job (IMP-09, API-15) and project bundles (PRJ-08/09) — Step 3b (backend + Projects view UI, `e2e/projects-bundle.spec.ts`)
- [x] Analytics views (API-38), dashboard tab, filters, click-through, linked selection (DB-01..07) — FE lane/3-ui (DB-04 "send to Explorer" filters the explorer by item id since Step 3b)
- [x] Measurements panel for the active item (UI-14)
- [x] Backend `analytics/`: analysis spec, unit (one row per case), test choice, FDR, effect sizes, descriptives, REC rules, export (ANA-01..09, API-39), TST-12
- [x] Analysis panel + Group comparison / Association / Balance check views (DB-08/09)
- [x] Remove the leftover `group` from `FeatureRow` and the dashboard; colour/split by variable
- [x] End-to-end check of the Variables view against the real API-16..18 (`e2e/variables.spec.ts`)
**Exit:** an injected fixture defect is visible as an outlier and opens in the viewer in one click; a two-group and a three-group comparison on a derived variable return tests matching SciPy, with q-values and at least one triggered recommendation.

### P7 — Packaging, done items
- [x] Follow-ups from Step 3 (LANE_NOTES.md), done in Step 3b: move the SPA mount from `scripts/container_app.py` into `app/main.py` (BE ARCHITECTURE); move `features/radiomics/api.ts` into the `Api` surface and update the mock; update `e2e/p2-flow.spec.ts` counts (50 cases / 89 scans); SSE sends a comment right after opening (Firefox "live" delay); explorer item-id filter for DB-04 and an exported `useExplorerFilter()` for RAD-05; align `pyproject` version with the image tag

### P7b — Sources, derived data, tasks & plugins (ADR-0013..0017), done items and exit
- [x] ADR-0013..0017 accepted; contracts in SOURCES, TASKS, DICOM_CONVERTER, ANALYZERS and the owning docs; R1 reworded (2026-09-24)
- [x] Wave 1 · contracts (2026-09-24; LANE_NOTES "P7b Wave 1"): `format_version` 2 migration (`path_roots.role`, `masks`, `segmentations`, `default_seg`, `annotation_sources`); `ALLOWED_DERIVED_ROOTS` + overlap check (OPS-11/12, BE-15); PRJ-13; generic task framework (manifests, protocol, builtin runtime, TSK-01..10) with radiomics as `radiomics.pyradiomics` + API-30..37 aliases (RAD-13); `?seg=` on API-24, API-27; FE API layer
- [x] Wave 2 · sources (2026-09-24; LANE_NOTES "P7b Wave 2"; the legacy VOI axis check moves to Wave 3, which may read `legacy/`): detect (API-19), `nifti-files` adapter, single-file import, identity registry (SRC-01..08); Open mode for NIfTI, label maps and NumPy (API-07/08, VW-21; DICOM in Open mode comes with the converter in Wave 3); NumPy axis rules (SRC-12) and a check of the legacy VOI axis order (IMP-10); `actions[]` on every refusal (SRC-11, UI-18); FE import wizard + Open
- [x] Wave 3 · converter + analyzers (2026-09-24; LANE_NOTES "P7b Wave 3"; the legacy VOI axis-order check stays open: `legacy/convert/` has no VOI writer): port `legacy/convert/` (reference only, R9) → `plugins/dicom/`, split `plugins/analyzers/` (phase, target, readiness); task wrappers; input = a dataset root, one patient/series folder, or a single DICOM file (DCM-01, DCM-10); DICOM in Open mode through the convert stage into `.scratch/` (SRC-13); sidecars + `anonymize` (DCM-04/05, NFR-17); incremental dataset (DCM-07); CUR-15; annotations + activation (ANZ-04, API-48); generic Tasks view + preflight (UI-17..20); TST-13, TST-16; **owner addendum 2026-09-24:** Open mode offers exactly Save as NIfTI… (SRC-14, API-09, `{derived}/_open/{date}/`, write-once, no overwrite, optional `anonymize: basic`), Add to project… (SRC-15) and Create project from this; docs first (SOURCES, ADR-0014 §4, PROJECT_FORMAT write rules, API, UI-17, VW-21); TST-15 save cases
- [x] Wave 4 · external runtime (2026-09-24; LANE_NOTES "P7b Wave 4"; VW-19 shows one set at a time): queue + `scripts/rw-runner.py` (TSK-11, BE-14); fake `segment.threshold` plugin (TST-14, CI); segmentation-set selector (VW-19) and `seg_id` in radiomics selection (RAD-05) and curation
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
- [x] **Owner addendum 2026-09-25 · import wizard UX** (2026-09-25; LANE_NOTES "Import wizard UX"): unmatched / orphan / ignored counts next to the Preview counts, tables scroll on their own, stacked `nifti-files` Preview, zero KPIs muted (IMP-03); "Skip for now" (IMP-13); inline alias validation (IMP-14); pattern suggester (SRC-17); pattern placeholder shows the real default (SRC-04, ADR-0024)
- [x] **Owner addendum 2026-09-25 · label table edit/delete** (2026-09-25; LANE_NOTES "Label table edit/delete"): column header menu Edit column… / Delete column… (LBL-02); table menu Edit table… (rename, restore deleted columns) / Delete table… with Deleted tables → Restore (LBL-10, soft delete, events kept); API-56 `hidden` + `?deleted=true`
**Exit:** a user converts a DICOM folder without a project from the converter overlay, opens the dataset with the full CT tool set, creates a neutral project from it, applies the ccRCC pack, labels cases in a patient-level table and a CT-level table, curates items, and shares a view-only link that cannot write; every plugin is reachable from the Library; `make check`, Playwright and NFR-07 green.

### Amendment — native phase selection (ADR-0026, after P7c; done 2026-09-25)
- [x] Backend: `phase` namespace on the core event store (PHS-01/02/08); effective-phase join at read time (PHS-03); native routes (not under `/plugins/`, API-63..65)
- [x] Frontend: one-click phase buttons in the case/scan header and Explorer (PHS-01); drop `wrong_phase_suspected` and the curation phase target/flow (CUR-06 removed)
- [x] `dataset_table`/`dataset.jsonl` `phase_source` provenance (PHS §Where the effective phase surfaces); `exports/phase_selections.json` (PHS-06, replaces `phase_proposals.json`)
- [x] Labeling reference columns (LBL-09) + `comparable` variable flag (VAR-13); `phase.effective` / `phase.analyzer` layer variables (VAR-12)

### Amendment — dataset.jsonl and reconstructed sidecars (ADR-0025; done 2026-09-25)
- [x] `dataset.jsonl` (API-59 `format=jsonl`): one line per item, layers flat, per-file records as `refs`; VAR-09 sensitive fields left out of every dataset-table format unless asked
- [x] Reconstructed sidecars on `metadata-v1` import, opt-in (IMP-15)
