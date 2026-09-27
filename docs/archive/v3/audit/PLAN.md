# Audit plan (v3, after P7c) — Closed 2026-09-27

Scope: end-to-end quality audit of the web app: scientist workflows, navigation, visuals, doc ↔ code conformance, bugs, code quality, tests.
Read when: running or triaging an audit (A0..A7).
Depends: VISION (§Journeys G1..G4), UI_SHELL (UI-*), VIEWER (VW-*), NFR, TESTING (TST-*), ROADMAP.

Owner decisions (2026-09-25): all four golden paths (G1..G4) in scope · **fixtures only** (`.fixtures/synthetic`, no real data) · findings are reported first, fixed later in approved batches · first pain point to dig into: **navigation and discoverability** (A1).

## Ground rules

| # | Rule |
|---|---|
| G-1 | The panel set is fixed (UI_SHELL §Layout, §Left pane views). Audits look for gaps **inside** it; a proposal never adds a panel, view or entry level (UI-17). |
| G-2 | Functional reference is 3D Slicer, but "modern and cheap": a proposal must reuse existing components and stay within VISION §In scope. Out-of-scope items (mask editing, PACS, advanced stats…) are not findings. |
| G-3 | Visual reference is VS Code / GitHub Dark without literal copy (ADR-0023). A literal VS Code signal is a finding; a VS Code convention that helps orientation is not. |
| G-4 | Audits do not change code or docs (except typos in the audit's own files). Fixes happen in batches after owner approval (§Fix batches). |
| G-5 | Runtime stays as it is: one OCI image, Docker locally, udocker remotely, browser client (R3, R4, R6). udocker itself is verified in ROADMAP Step 4, not here; A0 only checks R3 statically. |
| G-6 | Hard rules R1..R9 and NFR-11/12/17 violations are always `P0`, whatever audit finds them. Exception (owner 2026-09-26): R8 drift that is documentation-only (no effect on code or users) is `P2`. |
| G-7 | Each audit is time-boxed (one session) and caps its report at ~25 findings; merge duplicates, drop trivia. |

## Findings format

One file per audit: `docs/audit/findings/A{n}-{slug}.md`, header block as in `docs/INDEX.md`, then one table:

| ID | Sev | Path | Finding | Evidence | Proposal | Refs | Effort |
|---|---|---|---|---|---|---|---|

- **ID**: `AUD-A1-07`. Stable; referenced from fix commits.
- **Sev**: `P0` blocks a golden path, loses/corrupts data or breaks a hard rule · `P1` a scientist hits it in normal work (friction, contradiction, wrong result, missing M requirement) · `P2` polish, cleanup, S/C requirement.
- **Path**: `G1`..`G4` or `—`. **Evidence**: file:line, screenshot in `docs/audit/findings/img/` (fixtures only, never PHI), or a failing command. **Refs**: requirement IDs. **Effort**: S (< 1 h) · M (≤ 1 day) · L (more; split or defer).
- A finding without evidence is not a finding.

## Golden paths (walked in A1 and A2, on the fixtures)

G1..G4 are defined in `product/VISION.md` §Journeys (steps and refs).

For every step record: clicks + keys, whether the next action was **visible without searching**, dead ends, waits > 1 s, and a screenshot at 1440×900 (plus 1280×800 and 2560×1440 for layout findings).

## Audits

Order is fixed; stop for owner review after A1 and after A3 (one triage each).

| # | Audit | Question it answers | Method | Output |
|---|---|---|---|---|
| A0 | Baseline | Is the tree healthy enough to audit? | `make check`; Playwright suite ×3 (Chromium + Firefox) to spot flakes; `make image` + `make container-smoke` on Docker; bundle size (NFR-07); timings of `make check` and E2E | `A0-baseline.md`: pass/fail, flaky specs, durations, NFR-07 number. Not a findings table unless something fails |
| A1 | **Navigation & discoverability** | Can a scientist find everything and always know where they are and what's next? | **Reachability matrix** (below) + G1..G4 walk focused on wayfinding; command palette and quick open coverage; keyboard-only pass of G3; empty/first-run states; breadcrumbs, active-item sync between Explorer ↔ editor tab ↔ Inspector ↔ status bar; view-only and Open mode variants | `A1-navigation.md` + filled matrix |
| A2 | Workflow function | Does each golden path complete, give correct results and match Slicer-level expectations? | G1..G4 end to end; compare outputs with the fixture oracle (`expected.json`), SciPy for G4 stats, 3D Slicer conventions for orientation/W/L/crosshair; error paths per step (UI-18: cause + actions); refresh/back button mid-path; two tabs | `A2-workflows.md` |
| A3 | Visual & readability | Is it easy to read and pleasant, in both themes, without looking like a VS Code clone? | Screenshot sweep of every view/tab/overlay in dark + light at the three sizes; token audit (hard-coded colours/px outside `theme/`); type scale and density; WCAG AA contrast on text and badges; loading / empty / error states; icon consistency (UI-15); ADR-0023 literal signals; motion (UI-16) | `A3-visual.md` + contact sheet |
| A4 | Docs ↔ code conformance | Do docs, code and ROADMAP tell the same story? | **Traceability script** (scratch, not committed): every `| XXX-nn |` requirement → hits in code/tests; list `M` requirements with no code or no test; `API.md` routes vs OpenAPI snapshot vs `frontend/src/api/mock/server.ts`; ROADMAP `[x]` claims spot-checked; doc-to-doc contradictions (same fact stated twice, R8); stale `Open questions` | `A4-conformance.md` + traceability CSV in scratch |
| A5 | Functional consistency & bugs | Where do features disagree or break? | Cross-feature consistency: effective phase (PHS-03) in Explorer vs Image view vs dashboard vs `dataset.jsonl`; curation rollup vs badges; seg set selection across viewer/radiomics/curation; SSE live vs refetch; `If-Match` 412 paths; view-only enforcement server-side; R1 writes. Targeted review of the high-risk modules: `backend/app/tasks/service.py`, `radiomics/service.py`, `ingest/service.py`, `frontend/src/api/http.ts`, `features/viewer/engine/NiivueViewer.ts`, `ImportWizard.tsx` | `A5-bugs.md` (each bug with a repro on the fixtures) |
| A6 | Code quality & tests | Is the code clean, non-repetitive and cheap to change? | Duplication (`npx jscpd`), dead code (`npx knip`, `vulture`), type escape hatches (`any`, `as`, `# type: ignore`, `noqa`), files > 500 lines, layering (features importing each other, plugins reaching into core), mock server drift vs real API; tests: coverage by golden path (which steps have no E2E), unit coverage of the A5 modules, slow tests, fixture gaps; developer loop cost (`make check` time, type generation, E2E startup) | `A6-code-tests.md` |
| A7 | Documentation structure | Is the doc set clean, stable and publishable (Sphinx + MyST) with a PRD, an SRS and an MVP, without breaking the agent router? | See §A7 below | `A7-docs.md` + target tree and migration map |

Tools are run through `npx`/`uvx` from the scratchpad; nothing is added to `package.json` or `pyproject.toml` during the audit (integrator files, ops/AGENT_RUNBOOK.md §Lanes).

### Reachability matrix (A1)

One row per thing a scientist works with; one column per way to reach it. A cell holds the click/key count, or `—` if not reachable that way. A finding is raised when a core object needs > 3 actions from the case tab, is reachable in only one way, or has no palette command.

| Object | Welcome | Activity bar view | Explorer / context menu | Case tab | Palette | Quick open | Shortcut |
|---|---|---|---|---|---|---|---|
| Case, scan, item, next/previous case | | | | | | | |
| Segmentation set, label visibility | | | | | | | |
| Phase selection, QC status, comment, labeling cell | | | | | | | |
| Correction queue, exports (CSV, `dataset.jsonl`) | | | | | | | |
| Task (converter, analyzers, radiomics, threshold), its runs and outputs | | | | | | | |
| Radiomics run → dashboard → analysis | | | | | | | |
| Variables, derived variable, external table | | | | | | | |
| Project settings tabs, share / view-only link, Close | | | | | | | |
| Plugin Library, reviewer name, theme, keybindings | | | | | | | |
| Problems (warnings), jobs, history | | | | | | | |

### A7 · documentation structure (owner decisions 2026-09-26)

Tool: **Sphinx + MyST** (Markdown stays the source; build offline, dev-only dependency, never in the image, R5). **SRS generated**: `product/SRS.md` holds the hand-written IEEE 29148 frame (purpose, scope, definitions, constraints, verification); the requirement table is built from the owner docs' `| ID | Requirement | Pri |` rows, so R8 holds. **PRD** = `product/VISION.md` grown into a PRD (problem, users, goals, success metrics, journeys G1..G4, non-goals). **MVP = the v3.0 release cut**: G1..G4, the M requirements behind them, no open P0/P1 audit findings, Docker + udocker verified; everything else is "after v3.0". Order: A7 audit → owner approval of the target tree → one restructure batch → P1 fix batches.

| Step | Check | Output |
|---|---|---|
| Inventory | Every file: header block, lines, owner prefixes, inbound links (INDEX, other docs), orphans, root files (`LANE_NOTES.md`, `README.md`) | table in `A7-docs.md` |
| Trial build | `sphinx-build -W` with `myst-parser` via `uvx` in the scratchpad (no repo changes): broken links/anchors, heading levels, tables, images, duplicate labels | warning list grouped by cause |
| Classification | product (PRD, MVP, NFR, GLOSSARY, ROADMAP) · requirements (SRS) · design (domain, backend, frontend) · operations · decisions (ADR) · process (audit, runbook, lane notes) · archive | proposed tree |
| Agent router | `AGENTS.md` + `INDEX.md` keep working with the same token budget; root-doc name clash (`index.md` vs `INDEX.md` on case-insensitive macOS) resolved | rule + chosen root doc |
| SRS generator | Design only: parser rules, output location (build-time vs committed), `make docs` / `make docs-srs`, failure on duplicate IDs (A4-06) | spec |
| MVP cut | G1..G4 → M requirements (A4 `trace.csv`) → open findings → release checklist | draft outline, not the final MVP |
| Migration map | old path → new path, what is merged, split (A4-17 runbook), published or excluded (`archive/`, runbook) | table |

## Triage and fix batches

1. After each triage point the owner marks findings `accept` / `defer` / `reject` in the findings file (extra column `Decision`).
2. Accepted findings are grouped into **fix batches** of one theme each (e.g. "FB1 · navigation", "FB2 · states & errors"), ordered P0 → P1 → P2, each small enough for one session.
3. Each batch: fixes + tests (a Playwright step for every G-path fix) + the owning doc updated (R8), commit message cites the `AUD-` IDs, `make check` and affected E2E green.
4. A batch that changes a decision needs a new ADR first (AGENTS.md §Workflow).

## Status

| Audit | Status | Findings (P0/P1/P2) | Triage |
|---|---|---|---|
| A0 Baseline | ✅ 2026-09-25 (`findings/A0-baseline.md`) | 1 / 1 / 3 | closed (all fixed) |
| A1 Navigation | ✅ 2026-09-25 (`findings/A1-navigation.md`) | 0 / 8 / 11 | closed (all fixed) |
| A2 Workflows | ✅ 2026-09-25 (`findings/A2-workflows.md`) | 1 / 8 / 7 | closed (all fixed) |
| A3 Visual | ✅ 2026-09-25 (`findings/A3-visual.md`) | 0 / 5 / 18 | closed (all fixed) |
| A4 Conformance | ✅ 2026-09-25 (`findings/A4-conformance.md`) | 0 / 1 / 16 | closed (all fixed) |
| A5 Bugs | ✅ 2026-09-26 (`findings/A5-bugs.md`) | 2 / 7 / 7 | closed (all fixed) |
| A6 Code & tests | ✅ 2026-09-26 (`findings/A6-code-tests.md`) | 0 / 5 / 14 | closed (all fixed) |
| A7 Docs structure | ✅ 2026-09-26 (`findings/A7-docs.md`); restructure batch applied 2026-09-26 | 0 / 0 / 12 | closed (all fixed) |
| A8 Activity bar (rail) | ✅ 2026-09-27 (`findings/A8-rail.md`, minimal audit after an owner report) | 0 / 0 / 2 | closed (all fixed, FB9) |

**Exit:** every audit reported; P0 findings fixed; accepted P1 findings fixed or scheduled in ROADMAP; G1..G4 each covered by one Playwright spec that walks the whole path.

**Closed 2026-09-27** (owner decisions 2026-09-27): exit met. 129 findings (P0 4 · P1 36 · P2 89), every Decision cell `fixed`; none deferred or rejected. Fix batches FB1..FB12, commits in `REMEDIATION.md` §Owner review. The audit folder is frozen history in `docs/archive/v3/audit/` since.
