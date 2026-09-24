# Agent Runbook (for humans)

Scope: copy-paste prompts to build the roadmap with several Claude Code sessions in parallel.
Read when: you (the human) start a step. Agents: do not read this file unless told to.
Depends: product/ROADMAP.md.

## How it works

- **Integration branch:** `v3`. Each lane works on its own branch in its own **git worktree**, so parallel sessions never share a working copy.
- **Integrator:** the VS Code session. At the end of every step it merges the lane branches into `v3`, runs all checks, and stops for your approval (AGENTS.md workflow rule).
- **Gates you cannot skip:** the P0.5 prototype approval, the P1 check on the real Dataset820 data, and the P7 udocker test on the remote server.
- For long shell runs, switch the permission mode with `Shift+Tab` so the agent is not blocked on every edit.

## Schedule

| Step | VS Code extension (integrator) | Shell A | Shell B | Gate |
|---|---|---|---|---|
| 0 | Bootstrap (sequential) | — | — | Checks green |
| 1 | P0.5 design + prototype | P1 backend core | — | You approve the prototype; P1 exit |
| 2 | P2 shell + explorer (+ Variables view) | P1b variables, P4-BE curation, P5-BE radiomics, P6-BE analytics + stats | P3 viewer | Merge + checks |
| 3 | P4-FE curation, P6-FE dashboard | P5-FE radiomics form | P7-prep image + scripts | Merge + checks |
| 4 | Review | P7 on remote server (udocker, Dataset820, perf) | — | NFRs met |
| 5 | P8 Electron | — | — | Release |

## Worktree setup (run once per step, from the repo root)

```bash
cd "/Volumes/Mac/Mac external/Documents/ct_viewer"
git worktree add "../ct_viewer-wt/A" -b lane/<step>-A v3    # Shell A
git worktree add "../ct_viewer-wt/B" -b lane/<step>-B v3    # Shell B
cd "../ct_viewer-wt/A" && claude                           # then paste the lane prompt
```

After merging, clean up with `git worktree remove "../ct_viewer-wt/A"`.

## LANE RULES (paste this at the top of every lane prompt)

```text
LANE RULES
- Read AGENTS.md, then docs/INDEX.md, then ONLY the docs listed for this lane.
- You own ONLY the paths listed under "Owns". Do not edit anything else; if you need a
  change elsewhere, write it in LANE_NOTES.md at the repo root and continue.
- Implement against requirement IDs; cite IDs in commit messages.
- Run the lane's checks before every commit. Never commit red.
- Use sub-agents in parallel for independent modules within your lane.
- Do not run npm/node outside a container on the remote server (AGENTS R4).
- Commits are local only. Never git push.
- Dev servers: port 5173 is taken by VS Code on the dev Mac; use the port given in the lane prompt.
- When the lane's exit criteria pass: tick the tasks in docs/product/ROADMAP.md
  (only your lines), write a summary in LANE_NOTES.md, commit, and STOP.
- If a requirement is ambiguous or contradicts another, stop and ask. Do not guess.
```

---

## Step 0: Bootstrap (VS Code, sequential)

```text
You are the integrator. Branch: create `v3` from `docs/v3` and work on it.
Read AGENTS.md, docs/INDEX.md, docs/product/ROADMAP.md, docs/backend/ARCHITECTURE.md,
docs/frontend/ARCHITECTURE.md, docs/ops/DEV_ENV.md, docs/ops/TESTING.md.

Tasks:
1. `git mv` the v2 app to legacy/ (legacy/backend, legacy/frontend, legacy/Makefile,
   legacy/Dockerfile, legacy/docker-compose.yml, legacy/webui.sh). Keep udocker.py and
   udocker-1.3.17/ at the root. Agents must not read legacy/ except for the reuse items
   in ROADMAP §Migration.
2. Scaffold empty v3 skeletons matching the module layouts in both ARCHITECTURE docs:
   backend (pyproject with [dev] and [umap] extras, pytest, ruff, mypy) and frontend
   (Vite + React 19 + TS strict, Vitest, ESLint, Playwright config, i18n/en.json).
3. Add a Makefile with the targets in DEV_ENV.md (RUNTIME=native|docker|udocker).
4. Implement `make fixtures` (TST-11): a deterministic synthetic dataset containing
   every IMP-08 defect.
5. Add a `make check` target that runs lint, type check and unit tests for both sides,
   passing on the empty skeletons.
6. Add backend/CLAUDE.md and frontend/CLAUDE.md (≤ 30 lines each): the local rules and
   the docs to read for that side only.
7. Add a "Lanes" table to ROADMAP.md with lane → owned paths, matching AGENT_RUNBOOK.
Exit: `make fixtures && make check` passes. Commit to v3 and STOP.
```

## Step 1

### VS Code: P0.5 design + prototype
```text
[LANE RULES]
Lane: P0.5. Branch: lane/1-design (worktree optional; you may work in the main checkout).
Read: docs/frontend/UI_SHELL.md, docs/frontend/ARCHITECTURE.md, docs/frontend/VIEWER.md
(layouts only), docs/adr/0010-qupath-layout-github-dark.md.
Owns: frontend/** (except frontend/src/features/viewer/engine/**).
Build ROADMAP P0.5: tokens.css (GitHub Dark + Light, UI-11), the CT icon set (UI-15, SVG,
codicon rules), and the shell regions and views from UI_SHELL with a mock API layer seeded
from `make fixtures` output. Viewports are placeholders showing the 2×2 layout and
per-plane accent colours (VW-04). Wireframe screens: home, import wizard, workbench,
radiomics settings, dashboard, correction queue.
Checks: make check (frontend). Start the dev server so I can click through it.
Exit: I approve the prototype in this chat. Then update UI_SHELL.md with any design
changes, commit and STOP.
```

### Shell A: P1 backend core
```text
[LANE RULES]
Lane: P1. Branch: lane/1-backend in worktree ../ct_viewer-wt/A.
Read: docs/backend/ARCHITECTURE.md, docs/backend/API.md, docs/domain/PROJECT_FORMAT.md,
docs/domain/INPUT_METADATA.md, docs/domain/DATA_MODEL.md, docs/ops/TESTING.md,
docs/adr/0006-radiomics-engine-adapter.md (spike only).
Owns: backend/**.
Order: (1) spikes: PyRadiomics on Python 3.12 + IBSI phantom smoke test; NiiVue mesh
format. Record the results in LANE_NOTES.md and draft a superseding ADR if needed.
(2) core/ + config. (3) Then in parallel sub-agents: projects/ + fs API; ingest/;
imaging/ streaming + thumbnails (IMP-12); jobs/ + events/ SSE.
Checks: make check (backend), TST-01..03, TST-07 against the fixtures.
Exit: ROADMAP P1 exit criteria on the fixtures. The Dataset820 check is done by me
later; list the exact command for it in LANE_NOTES.md. Commit and STOP.
```

**Integrator after Step 1 (VS Code):**
```text
Merge lane/1-design and lane/1-backend into v3. Resolve conflicts using the docs as the
authority. Apply the requests in LANE_NOTES.md or list them for me. Run make check +
make fixtures + TST-07. Regenerate API types (make gen-api) and swap the prototype's mock
layer to the real API for the endpoints P1 delivered. Report and STOP.
```

## Step 2

### VS Code: P2 shell + explorer
```text
[LANE RULES]
Lane: P2. Branch: lane/2-shell.
Read: docs/frontend/UI_SHELL.md, docs/frontend/ARCHITECTURE.md, docs/backend/API.md,
docs/domain/INPUT_METADATA.md (import wizard only), docs/domain/VARIABLES.md.
Owns: frontend/** except frontend/src/features/viewer/**, features/curation/**,
features/radiomics/**, features/dashboard/**.
Build ROADMAP P2 against the real API, including the Variables view and replacing the
prototype's hard-coded `group` with variable-driven filters/columns/colours. API-16..18
are built in parallel by lane/2-backend: code against API.md + the mock until the merge.
The dashboard's `group` usage is left to lane P6-FE (Step 3). Checks: make check, Playwright smoke for the
new-project → import → browse → share-link flow. Exit: ROADMAP P2 exit. Commit and STOP.
```

### Shell A: backend for curation, radiomics, analytics
```text
[LANE RULES]
Lane: P1b + P4-BE + P5-BE + P6-BE. Branch: lane/2-backend in worktree ../ct_viewer-wt/A.
Read: docs/domain/VARIABLES.md, docs/domain/ANALYSIS.md, docs/domain/CURATION.md,
docs/domain/RADIOMICS.md, docs/frontend/DASHBOARD.md (views table only),
docs/backend/API.md, docs/backend/ARCHITECTURE.md, docs/ops/TESTING.md.
Owns: backend/app/{variables,ingest,projects,curation,radiomics,analytics}/**,
backend/tools/make_fixtures.py, their routers in backend/app/api/v1/, and their tests.
Order: (1) P1b first: remove hard-coded `group` from ingest, build variables/ and
presets, extend fixtures (TESTING §Variables). (2) Then parallel sub-agents:
curation (events, reducer, queue, exports, v2 import, SSE publish); radiomics (adapter,
schema, ibsi_map.json, validation, profiles, runs, resume, outputs); analytics
(API-38 views + API-39 guided statistics, recommendations, TST-12).
Never name study fields (hb/lb/sn/group) in code.
Checks: make check, TST-06 (IBSI), TST-12, NFR-15 reproducibility. Exit: all listed
API-16..18, 3x, 5x endpoints pass contract tests. Commit and STOP.
```

### Shell B: P3 viewer
```text
[LANE RULES]
Lane: P3. Branch: lane/2-viewer in worktree ../ct_viewer-wt/B.
Read: docs/frontend/VIEWER.md, docs/adr/0003-client-rendering-niivue.md, API-23..25 in
docs/backend/API.md, and the P1 spike results in LANE_NOTES.md.
Owns: frontend/src/features/viewer/**, backend/app/imaging/mesh*.
Build the ViewerHandle wrapper, layouts and interactions VW-01..16. Add a standalone
dev harness route that loads a fixture item.
Checks: make check, and TST-09 on the reference volume (NFR-01/02). Exit: ROADMAP P3
exit. Commit and STOP.
```

**Integrator after Step 2:** same as after Step 1, and also mount the viewer in the case editor tab.

## Step 3

Before starting: `colima start` (Docker daemon for Shell B). Worktrees: `../ct_viewer-lane3-{ui,radiomics,packaging}`.

### VS Code / Terminal 1: P4-FE curation + P6-FE dashboard (port 5174)
```text
[LANE RULES]
Lane: P4-FE + P6-FE. Branch: lane/3-ui (this worktree). Dev server port: 5174.
Read: frontend/CLAUDE.md, docs/domain/CURATION.md, docs/frontend/DASHBOARD.md,
docs/domain/ANALYSIS.md, docs/domain/VARIABLES.md (§Implementation notes),
docs/frontend/UI_SHELL.md (keybindings, Measurements panel UI-14), docs/backend/API.md.
Owns: frontend/src/features/{curation,dashboard}/**, and the variables/FeatureRow parts
of frontend/src/api/{types,http,mock}.ts.
Build the curation UI (CUR-*, UI-12) and the dashboard + Analysis panel (DB-01..09, UI-14)
on the real API-38/39/50..54. Remove the leftover `group` from FeatureRow and the
dashboard (colour/split by variable). Run an end-to-end check of the Variables view
against the real API-16..18 (adapter in api/http.ts) and fix what breaks.
Checks: make check, TST-08 multi-user test. Exit: ROADMAP P4 + P6 exits. Commit and STOP.
```

### Terminal 2: P5-FE radiomics form (port 5175)
```text
[LANE RULES]
Lane: P5-FE. Branch: lane/3-radiomics (this worktree). Dev server port: 5175.
First: VIRTUAL_ENV=backend/.venv uv pip install -e 'backend[radiomics]' (needs a C compiler).
Read: frontend/CLAUDE.md, docs/domain/RADIOMICS.md (incl. §Implementation notes), API-30..37.
Owns: frontend/src/features/radiomics/**.
Build the schema-driven settings form (RAD-01/02/04) with engine defaults shown on open,
plus profiles, selection by any variable (RAD-05), estimate and the runs list with progress.
Checks: make check, form unit tests for every validation rule, one real run on the fixtures.
Exit: ROADMAP P5 exit. Commit and STOP.
```

### Terminal 3: P7-prep packaging (Docker)
```text
[LANE RULES]
Lane: P7-prep. Branch: lane/3-packaging (this worktree).
Read: docs/ops/DEPLOYMENT.md, docs/adr/0007-single-image-docker-udocker.md,
docs/adr/0006-radiomics-engine-adapter.md, docs/ops/DEV_ENV.md.
Owns: Dockerfile, .dockerignore, docker-compose.yml, scripts/**, .env.example, README.md,
backend/app/config.py (+ its test).
Build OPS-01..10 and TST-10 for Docker. The image installs the `[radiomics]` extra
(gcc only in the build stage) and runs `tools.spikes.ibsi_phantom_smoke` inside the Linux
image (deferred from P1). Add a container-mode signal so an empty ALLOWED_DATA_ROOTS
refuses to start (OPS-04). Write scripts/udocker-run.sh (OPS-09) from the same .env.
Checks: image builds, health OK, IBSI smoke passes in the image, image size ≤ 1.5 GB,
make check. Exit: docker compose up serves the app. Commit and STOP.
```

**Integrator after Step 3:** merge, reconcile `frontend/package.json` + lockfile, `make gen-api`, `make check`, and report the image size.

## Step 3b: close pending items from one terminal with sub-agents (no udocker)

Open one Claude terminal in the main checkout (`ct_viewer`, branch `v3`) and paste:

```text
You are the orchestrator for "Step 3b" of this repo. Work locally on branch v3; never git push.
Read AGENTS.md, docs/INDEX.md, docs/product/ROADMAP.md (§P6, §P7) and the last three
"Step 3" entries of LANE_NOTES.md. Do NOT read docs/archive/** or legacy/**.

Goal: close the pending engineering items below. Out of scope (leave untouched, keep them
listed as open): anything needing the remote server or udocker (Step 4, Dataset820, TST-10
under udocker, exec-mode benchmark), the human checks (IBSI map vs manual, queue CSV in 3D
Slicer, real v2 import), and the user decision on continuous ranges in radiomics selection.

Use sub-agents (Agent tool, isolation "worktree", run in background) with disjoint file
ownership. Give each sub-agent: its task list, the docs to read, the paths it owns, and the
rule "run make check before committing; never commit red; commit locally on your branch;
write a short summary for the orchestrator". Waves:

Wave 1 (parallel)
- A · backend (owns backend/**, scripts/**, Dockerfile, docker-compose.yml, Makefile VERSION):
  1. Mount the SPA in app/main.py when STATIC_ROOT/index.html exists (/assets static,
     index.html fallback for client routes, /api/* never falls back); keep
     scripts/container_app.py only as the entry that prints the OPS-04 refusal, or drop it.
  2. SSE (API-40): send a comment line right after the stream opens (Firefox "live" delay).
  3. Add `modality` to the item record (DATA_MODEL Item) from metadata `modality`.
  4. IMP-09 / API-15 full-hash job, and PRJ-08/09 project bundle export/import (API-06).
  5. One source for the version: backend/pyproject.toml; Makefile VERSION and compose
     RW_VERSION read it. Refresh the OpenAPI snapshot.
- B · frontend API layer for radiomics (owns frontend/src/api/** radiomics parts,
  frontend/src/features/radiomics/api.ts, hooks.ts): move features/radiomics/api.ts into the
  Api surface (surface.ts/http.ts/types.ts/hooks.ts/keys.ts) with generated types, add a
  validation query key, update the mock so the settings tab works with VITE_API_MODE=mock,
  delete the obsolete prototype radiomics members.

Wave 2 (after merging A and B into v3 and running make gen-api)
- C · frontend features (owns frontend/src/features/{explorer,projects,dashboard,viewer}/**,
  frontend/src/features/radiomics/SelectionForm.tsx, frontend/e2e/**, i18n additions):
  1. Explorer item-id filter (CaseFilter + Project view) so dashboard "Send to Explorer"
     (DB-04) filters for real; export a read-only useExplorerFilter() and offer
     "Use the current Explorer filter" in the radiomics selection (RAD-05).
  2. Viewer reads item.modality (drop the extra.modality fallback) for VW-05.
  3. UI for bundles (export/import in the Projects view) and "Compute full hashes".
  4. Update e2e/p2-flow.spec.ts to the current fixture counts; run the Playwright suite
     (Chromium + Firefox) and fix what fails in C's paths.
- D · optional, in parallel with C (owns nothing in git): if the Docker daemon is up,
  build the image for linux/amd64 (`make image PLATFORM=linux/amd64`) and run
  `make container-smoke` against it. If emulation makes it take > 60 min, stop and report.

Integration after each wave (you do this yourself, not a sub-agent): merge with --no-ff,
keep all LANE_NOTES.md entries on conflict, use the docs as the authority for other
conflicts, npm install, make gen-api, make fixtures && make check. Keep initial JS
≤ 300 KB gzip (NFR-07; strings used only in lazy chunks go to i18n/en.lazy.json).
Update the owning docs (API.md, DATA_MODEL.md, PROJECT_FORMAT.md, DEPLOYMENT.md,
VIEWER.md, FE/BE ARCHITECTURE) and tick ROADMAP lines. Write one "Step 3b" entry in
LANE_NOTES.md with results (tests, initial JS size, amd64 image size if built).
Commit locally and STOP. If make check cannot be made green, leave the work on a branch
step3b-wip, keep v3 at its last green commit, and explain.
```

## Step 4: Shell on the remote server (P7)

```text
[LANE RULES]
Lane: P7. You are on the remote no-sudo server. Branch: v3 (after I merge Step 3).
Read: docs/ops/DEPLOYMENT.md, docs/ops/TESTING.md, docs/product/NFR.md.
Owns: scripts/**, docs/ops/DEPLOYMENT.md (udocker notes only), LANE_NOTES.md.
1. Load the image I transferred (udocker load), create and run it via scripts/udocker-run.sh.
2. Verify the udocker notes (bind address, ro mounts, execution mode P1 vs F3) and
   correct DEPLOYMENT.md with what you measured.
3. Import Dataset820 via the API; run TST-05, TST-09 and TST-10 against it.
Exit: all NFRs met or gaps listed with numbers. Commit and STOP.
```

## Step 5: VS Code, P8 Electron

```text
[LANE RULES]
Lane: P8. Branch: lane/5-electron.
Read: docs/adr/0001-web-first-electron-later.md, docs/ops/DEPLOYMENT.md §Electron,
docs/frontend/ARCHITECTURE.md (FE-07).
Owns: desktop/**.
Build a thin Electron shell loading PUBLIC_BASE_URL with a preload bridge for native
folder dialogs. Exit: ROADMAP P8 exit. Commit and STOP.
```
