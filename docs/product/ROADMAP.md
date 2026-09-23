# Roadmap

Scope: phases, exit criteria, progress, v2 → v3 migration.
Read when: choosing what to work on next.
Depends: all docs (by ID).

Rules: work in phase order; mark tasks `[x]` when done; stop for user confirmation at every phase exit.

## Progress

| Phase | Title | Status |
|---|---|---|
| P0 | Documentation & ADRs | ✅ Done (2026-09-23) |
| P0.5 | UX design system & clickable prototype | ⬜ |
| P1 | Backend core: projects, import, index | ✅ 2026-09-23 (verified on `.fixtures/synthetic`; Dataset820 run deferred to P7 on the remote server, command in LANE_NOTES.md) |
| P2 | Frontend shell + explorer | ⬜ |
| P3 | Viewer (NiiVue) | ⬜ |
| P4 | Curation + multi-user sync | ⬜ |
| P5 | Radiomics engine + settings + runs | ⬜ |
| P6 | Dashboard | ⬜ |
| P7 | Packaging: Docker + udocker, E2E, performance | ⬜ |
| P8 | Electron shell | ⬜ |

Step 0 bootstrap (legacy move, skeletons, Makefile, fixtures, `make check`): ✅ 2026-09-23.

## Lanes (parallel work; prompts in ops/AGENT_RUNBOOK.md)

A lane edits **only** the paths it owns. Anything it needs elsewhere goes into `LANE_NOTES.md` for the integrator.
Every lane may also append to `LANE_NOTES.md` and tick its own lines in this file.

| Step | Lane | Branch | Runs in | Owns |
|---|---|---|---|---|
| 0 | Bootstrap | `v3` | VS Code | Repo root, skeletons (done) |
| 1 | P0.5 design + prototype | `lane/1-design` | VS Code | `frontend/**` except `frontend/src/features/viewer/engine/**` |
| 1 | P1 backend core | `lane/1-backend` | Shell A | `backend/**` |
| 2 | P2 shell + explorer | `lane/2-shell` | VS Code | `frontend/**` except `features/{viewer,curation,radiomics,dashboard}/**` |
| 2 | P4-BE + P5-BE + P6-BE | `lane/2-backend` | Shell A | `backend/app/{curation,radiomics,analytics}/**`, their routers in `backend/app/api/v1/`, their tests |
| 2 | P3 viewer | `lane/2-viewer` | Shell B | `frontend/src/features/viewer/**`, `backend/app/imaging/mesh*` |
| 3 | P4-FE + P6-FE | `lane/3-curation-dashboard` | VS Code | `frontend/src/features/{curation,dashboard}/**` |
| 3 | P5-FE radiomics form | `lane/3-radiomics-ui` | Shell A | `frontend/src/features/radiomics/**` |
| 3 | P7-prep packaging | `lane/3-packaging` | Shell B | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `scripts/udocker-run.sh`, `.env.example`, `README.md` |
| 4 | P7 remote verification | `v3` | Shell (remote server) | `scripts/**`, `docs/ops/DEPLOYMENT.md` (udocker notes), `LANE_NOTES.md` |
| 5 | P8 Electron | `lane/5-electron` | VS Code | `desktop/**` |

Shared files that only the integrator edits: `Makefile`, `backend/pyproject.toml` dependency list, `frontend/package.json`/lockfile (lanes may add dependencies in their own branch; the integrator resolves lockfile conflicts at merge), `AGENTS.md`, `docs/INDEX.md`.

## Phases

### P0 — Documentation
- [x] Docs tree, router, ADR-0001..0010
- [x] User decisions recorded (2026-09-23): archive-only projects, phases NC/CMP/NP/EP/UNK, Slicer crosshair colours, v2 statuses, English i18n-ready, name, 500–3,000-case scale, defaults accepted
**Exit:** user approves the docs; open questions are resolved or explicitly deferred.

### P0.5 — UX design system & prototype (ADR-0010)
- [ ] Design tokens: GitHub Dark + Light (`theme/tokens.css`), typography, spacing, radius (UI-11)
- [ ] Custom CT icon set drawn to codicon rules (UI-15)
- [ ] Wireframes: Welcome/home · Import wizard · Workbench with 2×2 case · Radiomics settings form · Dashboard · Correction queue
- [ ] Clickable prototype: the real shell components (`shell/`) on a mock API layer seeded from the synthetic fixtures, with no backend. It becomes the P2 foundation rather than a throwaway.
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

### P2 — Shell + explorer
- [ ] Wire the P0.5 prototype shell to the real API: regions, tool bar, command palette, quick open (UI-01..08, 11, 13)
- [ ] Workspace home, new project, import wizard (UI-04, IMP-01..03)
- [ ] Project view with thumbnails (UI-08, IMP-12, API-26), Image/Labels/Search views, Problems panel (UI-09)
**Exit:** a user creates a project, imports data, browses cases, and shares a link that opens in a second browser.

### P3 — Viewer
- [ ] NiiVue wrapper (`ViewerHandle`), layouts, MPR interaction (VW-01..08, 11..14)
- [ ] 3D + meshes (VW-09, API-25), toolbar (VW-10)
**Exit:** NFR-01/02 met on the reference volume; all layouts work; the adaptive states render correctly.

### P4 — Curation
- [ ] Reviewer identity, events, reducer, inspector form, shortcuts (CUR-01..08, 14, UI-12)
- [ ] Queue + exports + v2 import (CUR-09, 10, 13), live sync (CUR-11/12)
**Exit:** TST-08 green; exported queue CSV opens paths in 3D Slicer.

### P5 — Radiomics
- [ ] Engine adapter + schema + IBSI map (RAD-01, 12), validation (RAD-04)
- [ ] Profiles, selection, estimate, runs, resume, outputs (RAD-03, 05..11)
- [ ] Schema-driven settings form (RAD-01/02)
**Exit:** TST-06 passes for the compliant features; a run over the fixtures is reproducible (NFR-15).

### P6 — Dashboard
- [ ] Analytics views (API-38), dashboard tab, filters, click-through, linked selection (DB-01..07)
- [ ] Measurements panel for the active item (UI-14)
**Exit:** an injected fixture defect is visible as an outlier and opens in the viewer in one click.

### P7 — Packaging
- [ ] Dockerfile, compose, `udocker-run.sh`, execution-mode benchmark (OPS-*)
- [ ] TST-05, TST-09, TST-10; README quick start
**Exit:** the same image runs under Docker locally and udocker remotely; NFR targets are met.

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
| `docs/archive/v2/*`, `legacy/**` | Frozen reference only; `legacy/` is removed after P7 |
