# Roadmap

Scope: phases, exit criteria, progress, v2 → v3 migration.
Read when: choosing what to work on next.
Depends: all docs (by ID).

Rules: work in phase order; mark tasks `[x]` when done; stop for user confirmation at every phase exit.
Order from 2026-09-24 (user decision): **P7b → P7c (done 2026-09-25) → quality audit (A0..A8, fix batches FB1..FB9) → pending plugins (VOI extractor, nnU-Net) → P7 remote part (Step 4: udocker, server checks) → P8 Electron**.

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
Lanes (branches and owned paths per step): ops/AGENT_RUNBOOK.md §Lanes.

## Phases

Finished phases and the done items of open ones (tasks, exit criteria): `docs/archive/v3/ROADMAP-done.md` — P0, P1, P1b, P2, P3, P4, P6, P7c, the native phase selection (ADR-0026) and dataset.jsonl (ADR-0025) amendments, all done 2026-09-23..25. Below: only phases with open items.

### P0.5 — UX design system & prototype (ADR-0010)
- [ ] Walkthrough with a curator and a researcher: open case → review → mark status → next case; configure → run → open outlier
**Exit:** user approves the look, layout and the main flows; design changes are reflected in UI_SHELL.md.

### P5 — Radiomics
- [ ] **Human check:** spot-check `backend/app/radiomics/ibsi_map.json` codes and the extended phantom reference values against the IBSI manual (written from memory by an agent); run the IBSI CT phantom (TST-06 part 2) once the dataset is available
**Exit:** TST-06 passes for the compliant features; a run over the fixtures is reproducible (NFR-15).

### P7 — Packaging
- [ ] Dockerfile, compose, `udocker-run.sh`, execution-mode benchmark (OPS-*) — Dockerfile, compose, `udocker-run.sh` done (lane/3-packaging); execution-mode benchmark on the remote server (Step 4)
- [ ] TST-05, TST-09, TST-10; README quick start — TST-10 under Docker and README quick start done (lane/3-packaging); TST-10 under udocker, TST-05, TST-09 in Step 4
- [ ] Move analytics views/analyses from API-process threads to job workers if slow at 3,000 cases (BE-12) — `Item.modality` done in Step 3b (VW-05 reads it); BE-12 still open
- [ ] Deferred from P1: Dataset820 import check on the remote server (`tools.import_check`, LANE_NOTES.md); rerun `tools.spikes.ibsi_phantom_smoke` inside the Linux image (build stage needs `gcc`); add a container-mode signal so an empty `ALLOWED_DATA_ROOTS` refuses to start (OPS-04) — IBSI smoke in the image and OPS-04 `CONTAINER_MODE` done (lane/3-packaging); Dataset820 check in Step 4
- [ ] Build the image for the server's architecture (`make image PLATFORM=linux/amd64` if the server is amd64), rerun `make container-smoke`, then `docker save` → udocker — amd64 build + TST-10 under Docker done (Step 3b, IBSI 20/20); `docker save` → udocker in Step 4
- [ ] **Decision (user):** radiomics selection by continuous ranges (`min..max`) in API-44/45, or keep "bin into a derived variable first"
- [ ] **Human checks:** open the exported correction-queue CSV in 3D Slicer (P4 exit); import a real v2 `curation_review.csv` (API-54)
**Exit:** the same image runs under Docker locally and udocker remotely; NFR targets are met.

### P7b — Sources, derived data, tasks & plugins (ADR-0013..0017)
Waves 1–4 done 2026-09-24 (exit met; archive).
- [ ] **Deferred until the P7b amendments are stable (user decision 2026-09-24):** `plugins/nnunet/` (`dataset.json` labels, `_0000` staging, batches; ADR-0016 §6) and its human check on a GPU host (one item and a batch)
- [ ] **Pending (user decision 2026-09-24):** a VOI extractor plugin that crops VOIs from a segmentation (reference code to be provided); it also settles the legacy `.npy` VOI axis order (IMP-10, SRC-12; default `xyz` until then). Keep `legacy/` until the owner decides to delete it (fully ported otherwise)
- [ ] **Human checks:** a converted DICOM series opened next to the original in 3D Slicer (orientation); anonymized sidecar reviewed for PHI

### Pending plugins (after P7c, before Step 4)
- [ ] VOI extractor plugin: crops VOIs (image + mask, per side) from a segmentation set; **requires a segmented mask**; reference code from the owner; settles the legacy `.npy` VOI axis order (SRC-12, IMP-10)
- [ ] nnU-Net segmentation plugin (`plugins/nnunet/`, external runtime, GPU), deferred from P7b; also owns nnU-Net dataset naming on import/export (`imagesTr/`/`labelsTr/`, `_0000` channels), removed from core `nifti-files` (ADR-0024)

### Quality audit (after P7c, before the pending plugins; owner decision 2026-09-25)
- [x] A0..A7 run 2026-09-25..26 per `docs/audit/PLAN.md`; findings in `docs/audit/findings/`
- [x] Fix batches FB1..FB7 (2026-09-26..27; one commit each, `docs/audit/REMEDIATION.md` §Owner review)
- [x] FB8 (tests, performance budget, code health; 2026-09-27)
- [x] A8 rail duplication audit and FB9 (owner decisions after FB8: registry upsert, 400 KiB budget + baseline warning, outlier share rule, dev tools gates, ADR-0027/0028 Accepted; 2026-09-27)
- [x] FB11 (shared run lifecycle + `tasks/service.py` split, AUD-A6-06; radiomics UI on the task routes API-43..47, aliases API-31/33/34/35/37 removed, AUD-A4-09; 2026-09-27)
- [ ] The deferred items (REMEDIATION §Deferred)
**Exit:** see `docs/audit/PLAN.md` §Status.

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
