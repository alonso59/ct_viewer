# Roadmap

Scope: phases, exit criteria, progress, v2 → v3 migration.
Read when: choosing what to work on next.
Depends: all docs (by ID).

Rules: work in phase order; mark tasks `[x]` when done; stop for user confirmation at every phase exit.
Order: **P7b → P7c → quality audit (all done) → P7d nnU-Net planning → P7e nnU-Net generation → P7f job-safety planning → P7g supervised segmentation jobs → P7h CTFlow console (C0–C7) → P7i standalone DICOM converter → VOI extractor → P7 remote checks → P8 Electron**. P7i does not depend on P7h; its phases were implemented in one pass on 2026-11-03 (owner decision). P7l (agent interface, ADR-0048) is independent of P7k.

## Progress

| Phase | Title | Status |
|---|---|---|
| P0 | Documentation & ADRs | ✅ Done (2026-09-23) |
| P0.5 | UX design system & clickable prototype | 🟨 Built and approved 2026-09-23; curator/researcher walkthrough pending |
| P1 | Backend core: projects, import, index | ✅ 2026-09-23 (verified on `.fixtures/synthetic`; Dataset820 run deferred to P7 on the remote server, command in ops/TESTING.md §Dataset820 import check) |
| P1b | Study variables (backend): profiling, catalog, derived, external table; remove hard-coded `group` | ✅ 2026-09-24 |
| P2 | Frontend shell + explorer | ✅ 2026-09-24 |
| P3 | Viewer (NiiVue) | ✅ 2026-09-24 (synthetic reference; Dataset820 in P7) |
| P4 | Curation + multi-user sync | ✅ 2026-09-24 (human check pending: queue CSV in 3D Slicer) |
| P5 | Radiomics engine + settings + runs | ✅ 2026-09-24 (human check pending: IBSI map vs manual) |
| P6 | Dashboard + guided analysis | ✅ 2026-09-24 |
| P7 | Packaging: test image, E2E, performance | 🟨 Docker image done (arm64 947 MB, amd64 935 MB, TST-10 pass on both); udocker dropped (ADR-0051); remote checks (Step 4) moved to the end, after P7b (user decision 2026-09-24) |
| P7b | Sources, derived data, tasks & plugins (ADR-0013..0017) | ✅ 2026-09-24 (exit criterion met; deferred: `plugins/nnunet/`; human checks pending: 3D Slicer orientation, PHI review) |
| P7c | Plugin platform, neutral projects, CT tools, curation & labeling plugins (ADR-0018..0022) | ✅ 2026-09-25 (exit criterion met: `e2e/p7c-exit.spec.ts`; pending plugins VOI extractor and nnU-Net follow) |
| P7d | nnU-Net segmentation planning | ✅ 2026-10-21 (ADR-0032 accepted; Dataset220; 2–4 GPU policy) |
| P7e | nnU-Net segmentation generation | ✅ 2026-10-21 (TST-21 fake CLI, one-case GPU and two-case/two-GPU acceptance) |
| P7f | Supervised segmentation job planning and requirement audit | ✅ 2026-10-22: owner accepted ADR-0033 and authorized P7g |
| P7g | Supervised segmentation jobs, tests first | 🟨 ADR-0034 containment, one/two-GPU inference, catalog, pause/cancel/archive lifecycle verified by unit/API tests and on the GPU host; deployed to local production 2026-10-22; browser journeys and CI image build remain open (domain/SEGMENTATION_JOB_PLAN.md) |
| P7h | CTFlow console: commands, scripts, `ctflow` client (ADR-0041) | 🟨 C0–C7 done 2026-11-03, exit pending owner review (docs; attribution and project-run logs; catalog, targets, one-line evaluation; `ctflow` client; language and sessions; durable script runs; library; web console) |
| P7i | Standalone DICOM converter package, per-unit pinning, parallel units (ADR-0042) | 🟨 S0–S8 implemented 2026-11-03 in one pass (owner decision); release gates and non-ext4 lanes in ops/DICOM_STANDALONE_TEST_PLAN.md |
| P7j | Deployment options: native, HPC (ADR-0043, ADR-0051) | 🟨 Native deployed on `john` 2026-11-04; HPC acceptance pending a real cluster (OPS-20, OPS-23) |
| P7k | Cohort dashboard: K1 read-only grid, K2 clinical & labels, K3 Timeline (ADR-0045/0046, COHORT.md) | ✅ K1–K3 2026-11-05, exit accepted by the owner (ADR-0049 for K3); COH-11 not built. Accepted 2026-11-04; independent of P7g–P7j (owner decision) |
| P7l | Agent interface: agent origin, CTFlow commands, batch reassign, `rw-mcp` (ADR-0048) | ✅ 2026-11-05 (owner accepted the exit); independent of P7k |
| P8 | Electron shell | ⬜ |

Runbook steps 0–3 (bootstrap and parallel lanes) integrated 2026-09-23..24.
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
- [x] Dockerfile and compose (OPS-*) — done; `udocker-run.sh` and the execution-mode benchmark dropped by ADR-0051
- [ ] TST-05, TST-09, TST-10; README quick start — TST-10 under Docker and README quick start done; TST-05, TST-09 in Step 4
  - TST-09 partial bench 2026-11-11 on this host (Chromium with SwiftShader, no GPU, synthetic 512×512×600 int16 reference-size volume): NFR-01 6.2 s (download + inflate 1.8 s, NiiVue parse 1.1 s of which ~1.0 s is its robust-range scan the app never reads, full-volume texture upload 1.1 s, NiiVue 3D proxy setup 1.1 s); NFR-03 30 ms per filter edit and 60 fps scroll at 3,000 cases; NFR-04 10,000 items in 19.6 s; NFR-08 317 MB. NFR-01 needs a run with a GPU before any change; if it still misses, parse the full volume without constructing a NiiVue image (only the 3D proxy needs one) and build the 3D proxy when the 3D tile is first shown
- [ ] Move analytics views/analyses from API-process threads to job workers if slow at 3,000 cases (BE-12) — measured 2026-11-11 on a synthetic 3,000-case / 10,000-item project with a ~100-feature run: warm views and analyses 25–610 ms, first call after boot up to 1.3 s, `/health` delayed up to 0.7 s while one runs, API RSS 317 MB idle → ~940 MB after the views and kept. Kept in API threads (not slow by this measure); reopen with a real radiomics run or if the retained memory matters
- [ ] Deferred from P1: Dataset820 import check on the remote server (ops/TESTING.md §Dataset820 import check); rerun `tools.spikes.ibsi_phantom_smoke` inside the Linux image (build stage needs `gcc`); add a container-mode signal so an empty `ALLOWED_DATA_ROOTS` refuses to start (OPS-04) — IBSI smoke in the image and OPS-04 `CONTAINER_MODE` done; Dataset820 check in Step 4
- [x] Build the image for amd64 and rerun `make container-smoke` — done (IBSI 20/20); the `docker save` → udocker step dropped by ADR-0051
- [ ] **Decision (user):** radiomics selection by continuous ranges (`min..max`) in API-44/45, or keep "bin into a derived variable first"
- [ ] **Human checks:** open the exported correction-queue CSV in 3D Slicer (P4 exit); import a real v2 `curation_review.csv` (API-54)
**Exit:** the image passes TST-10 in CI and the native release runs on the server; NFR targets are met.

### P7b — Sources, derived data, tasks & plugins (ADR-0013..0017)
Done 2026-09-24 (exit met; archive).
- [x] The VOI extractor plugin (§Pending plugin after P7g), built 2026-11-09
- [ ] **Pending (user decision 2026-09-24):** keep `legacy/` until the owner decides to delete it (fully ported otherwise)
- [ ] **Human checks:** a converted DICOM series opened next to the original in 3D Slicer (orientation); anonymized sidecar reviewed for PHI

### P7d — nnU-Net segmentation planning
- [x] Define the generation-only boundary, model profiles, upstream pipeline preservation, multi-GPU partitioning, output indexing and verification (ADR-0032, SEG-*, TST-21)
- [x] Owner selected `Dataset220_KiTS2023`, approved a 2–4 GPU runner pool and accepted ADR-0032 (2026-10-21)
**Exit:** ADR-0032 is Accepted and no SEG-* question blocks implementation. P7e begins only after the phase-boundary confirmation.

### P7e — nnU-Net segmentation generation
- [x] Implement `plugins/nnunet/` in the five waves from SEGMENTATION.md; use the generic Tasks UI and existing TSK-09 index registration
- [x] Pass TST-21 locally with the fake CLI, then on `john-gpinedo` with one item and a two-case batch on GPUs 0 and 6 (2026-10-21)
**Exit:** generated masks form a new indexed segmentation set, source and existing masks remain byte-identical, partial failure/cancel/resume work, and the real profile completes on the GPU host.

### P7f — Supervised segmentation job planning

- [x] Audit existing model, GPU, lifecycle and isolation contracts against the owner's requested controls; record code evidence and platform limitations
- [x] Define proposed acceptance criteria, test cases, test-environment/CI audit, failure-investigation policy and tests-first implementation waves
- [x] Owner accepts ADR-0033 and confirms the P7g phase boundary (2026-10-22)
**Exit:** review `domain/SEGMENTATION_JOB_PLAN.md` and `ops/SEGMENTATION_JOB_TEST_PLAN.md`; ADR-0033 is Accepted before changing ADR-0032 policies.

### P7g — Supervised segmentation jobs, tests first

- [x] Accept ADR-0033; add bounded/full test gates, locked test environment and regression-driven initial runner fixes
- [x] Rebaseline failed strict host requirements through accepted ADR-0034; implement the per-attempt supervisor and pass the effective local/server containment gate
- [x] Verify official prediction/postprocessing with one and two GPUs, immutable sources/models, geometry and indexing
- [ ] Run the ordered implementation waves and their red/green checkpoints from `domain/SEGMENTATION_JOB_PLAN.md`
- [ ] Pass the required environment lanes from `ops/SEGMENTATION_JOB_TEST_PLAN.md`; real host safety/GPU acceptance is mandatory and missing capabilities remain explicit blockers
**Exit:** accepted criteria have requirement IDs, passing regression tests and real isolation/cleanup evidence; no unrelated process affected, no source/model mutation and no duplicate attempts/output registration.

### P7h — CTFlow console (ADR-0041, CTFLOW.md)

Each step is a vertical slice with its own tests; stop for owner confirmation after each. Frontend work (C7) is coordinated with the frontend owner.
- [x] C0 Owner decisions D1–D7 (2026-11-03); ADR-0041, CTFLOW.md, INDEX/SRS registration, glossary, PRD scope
- [x] C1 Attribution and logs (2026-11-03; frontend API types regenerate with the frontend owner): reviewer and origin on task, workspace, source-operation and batch-plan records; API-71 project-run kind (CTF-15/16; facts move to TSK-10 and API-71)
- [x] C2 (2026-11-03) Command catalog, manifest `command` key, target resolver, one-command evaluation with plan mode; parity test against API-45 (CTF-02..06, CTF-09)
- [x] C3 (2026-11-03) `ctflow` client: interactive, `-c`, runs/status/logs/attach/cancel, reviewer, exit codes (CTF-18)
- [x] C4 (2026-11-03) Language and interactive sessions with limits; safety test suite (CTF-07/08)
- [x] C5 (2026-11-03) Durable script runs: journal, replay after restart without duplicate children, bounded wait and `attention`, control cascade (CTF-10..14)
- [x] C6 (2026-11-03) Script library and presets (CTF-17)
- [x] C7 (2026-11-03) Web console panel (CTF-19)
**Exit:** a script started from `ctflow` survives the client and a server restart, its children appear in the web UI with reviewer and origin, and no CTFlow path writes runs or outputs outside the existing services.

### P7i — Standalone DICOM converter (ADR-0042, DICOM_STANDALONE_PLAN.md)

Owner decision 2026-11-03: all phases implemented in a row, then verified together (no per-phase stop, no P7g gate). Cases: `ops/DICOM_STANDALONE_TEST_PLAN.md`. DCM-26..34 are `S` (not a v3.0 dependency); release requires the test plan's §Release gates.
- [x] S0 (2026-11-03) ADR-0042 accepted; plan, test plan, DCM-26..34
- [x] S1 Characterization and baselines (tests and tools only): C01–C12, B01–B06 — characterization green and baselines recorded 2026-11-03 (test plan §S1 evidence); open: B06 non-ext4 lanes, temporary disk, repeated large runs
- [x] S2 One settings contract, shared atomic emission, private state, CLI artifact parity: A01–A08
- [x] S3 Behavior-preserving plan / execute / assemble split: A09
- [x] S4 `rw_dicom` package, CLI, Python API, generated schema, conda instructions: A10–A14
- [x] S5a Durable discovery in the package, bounded-memory planning: A15–A17
- [x] S5b Per-unit pinning, commit v2, version policy, settings split: A18–A24
- [x] S6 Incomplete datasets: A25–A29
- [x] S7 Parallel units and total memory budget: A30–A36, B07; owner sets worker defaults
- [x] S8 Measured optimizations only (stat-based checks need a new ADR)
**Exit:** a standalone conversion of the large reference dataset imports into ct_viewer with layers, equals a workspace conversion under the same settings, resumes after interruption without reconverting verified units, and its measured resource use is recorded.

### P7l — Agent interface (ADR-0048, CTFLOW.md)

Independent of P7k. Exit accepted 2026-11-05.
- [x] A1 Agent origin; `resume`/`retry`/`diagnose`/`batches`/`batch` commands (CTF-21..23)
- [x] A2 Batch operation reassign endpoint (API-70)
- [x] A3 `scripts/rw-mcp.py` (CTF-24, OPS-25)
- [x] A4 Cohort requirements for agents, in the Cohort plan (after the owner hands over the Cohort work)
**Exit:** an MCP client lists runs, diagnoses a failed operation, retries it and reassigns a batch through `rw-mcp` with the same results as the GUI and API.

### P7k — Cohort dashboard (ADR-0045, ADR-0046, COHORT.md)

Steps as COHORT.md; independent of P7g–P7j. After P7k, a separate cleanup decides the Search view.
- [x] Spec, ADR-0045 and ADR-0046 accepted, VAR-14 (2026-11-04)
- [x] K1 C1 Origin and category in the catalog (VAR-14)
- [x] K1 C2 Read endpoints (rows, summary)
- [x] K1 C3 Cohort view, tab, navigator, grid, filters
- [x] K1 C4 Compare scans, column summary, DICOM tags
- [x] K1 C5 Export (incl. SVG / light PNG in both dashboards), keyboard/ARIA, view-only, e2e journey
- [x] K2 Clinical & labels editing in the grid, pack templates, external tables retired, Balance check (COHORT §K2); COH-11 left out
- [x] K3 Timeline: ADR-0049 (event level, date policy), event tables, time-to-event variables, the view
**Exit:** on the synthetic fixtures and Dataset820, a user filters the cohort by a value from the column summary, compares a case's scans and opens one in the viewer; nothing in the Metadata section writes except the correction-queue flag.

### Pending plugin after P7g
- [x] VOI extractor plugin (v3.2.0, ADR-0050, VOI.md): candidates per scan, patient or batch with axial previews; sides from patient coordinates; `voi.extract` crops; the owner's writer used `xyz`, which settles SRC-12 — owner review and release pending

### Quality audit (after P7c, before the pending plugins; owner decision 2026-09-25)
- [x] Audits A0..A8 and fix batches FB1..FB12, 2026-09-25..27; **closed 2026-09-27**: 129 findings, all fixed. Frozen record: `docs/archive/v3/audit/` (PLAN §Status, REMEDIATION §Owner review). Its only deferred item, the udocker check on the remote server, is P7 above (Step 4).

### P8 — Electron
- [ ] Thin shell + preload bridge for native folder dialogs (ADR-0001)
**Exit:** the desktop app connects to a local native release (Linux), a local Docker compose backend for development and tests (Windows, macOS) and a forwarded remote one (ADR-0054).

## Migration from v2

| v2 asset | v3 action |
|---|---|
| `legacy/backend/app/services/converter_metadata.py`, `qc_validator.py`, `path_resolver.py` | Reuse logic in `ingest/` and `core/paths` |
| `legacy/…/volume_cache`, `slice_renderer`, PNG slice API, `slice_cache` | Remove (replaced by client rendering) |
| `legacy/…/review_apply.py`, `metadata_sync.py` (source mutation) | Remove (conflicts with R1); keep as a reference for export shapes |
| `legacy/…/mesh_generator.py` | Reuse in the `imaging/` mesh job |
| `legacy/frontend` (MUI pages) | Rewrite; reuse the W/L presets and label palette |
| `.webui/curation_review.csv` | Import via CUR-13 |
| `docs/archive/v2/*`, `legacy/**` | Frozen reference only; `legacy/` is git-ignored and read-only since tag `legacy-reference` (R9); `legacy/convert/` is ported; deleting the folder is left to the owner |
