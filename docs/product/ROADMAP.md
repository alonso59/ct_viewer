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
| P1 | Backend core: projects, import, index | ⬜ |
| P2 | Frontend shell + explorer | ⬜ |
| P3 | Viewer (NiiVue) | ⬜ |
| P4 | Curation + multi-user sync | ⬜ |
| P5 | Radiomics engine + settings + runs | ⬜ |
| P6 | Dashboard | ⬜ |
| P7 | Packaging: Docker + udocker, E2E, performance | ⬜ |
| P8 | Electron shell | ⬜ |

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
- [ ] Spikes: NiiVue mesh format (VW open questions), PyRadiomics on Python 3.12 (ADR-0006)
- [ ] `core/` (paths, fsio, errors, ids, locks), config (OPS-03)
- [ ] Projects + workspace (PRJ-01..06, 10, 11), fs browser (API-10)
- [ ] Ingest: parsers, normalizer, indexer, validator (IMP-01..08, 10, 11)
- [ ] Item streaming (API-23/24), job manager (BE-06), SSE bus (API-40)
- [ ] Fixtures (TST-11), TST-01..03, TST-07
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
| `backend/app/services/converter_metadata.py`, `qc_validator.py`, `path_resolver.py` | Reuse logic in `ingest/` and `core/paths` |
| `volume_cache`, `slice_renderer`, PNG slice API, `slice_cache` | Remove (replaced by client rendering) |
| `review_apply.py`, `metadata_sync.py` (source mutation) | Remove (conflicts with R1); keep as a reference for export shapes |
| `mesh_generator.py` | Reuse in the `imaging/` mesh job |
| Frontend (MUI pages) | Rewrite; reuse the W/L presets and label palette |
| `.webui/curation_review.csv` | Import via CUR-13 |
| `docs/archive/v2/*` | Frozen reference only |
