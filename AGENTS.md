# AGENTS.md

Entry point for Claude Code and Codex: global rules and routing only. Facts live in the files routed below.

## Product in one line

Local-first, browser-based CT workbench: inspect NIfTI and DICOM volumes (single
files open without a project), visualize segmentations (never edited in place),
curate datasets, run tasks (DICOM conversion, metadata analyzers, radiomics,
segmentation models such as nnU-Net), and review feature QC in a dashboard. QuPath-style layout in a VS Code shell (GitHub Dark,
codicons) with a 3D Slicer-style 2×2 CT viewer.

## Start here

| Task touches | Read first | Then only if needed |
|---|---|---|
| `backend/` (API process, tools, pytest) | `backend/AGENTS.md` | one section of the owning doc (`docs/INDEX.md`) |
| `frontend/` (UI, viewer, dashboard, e2e) | `frontend/AGENTS.md` | one section of `docs/frontend/*.md` |
| `plugins/`, `scripts/rw-runner.py` (tasks, DICOM, nnU-Net, runner, GPU) | `plugins/AGENTS.md` | one section of `docs/domain/TASKS.md` or the owning doc |
| An HTTP endpoint or response model | skill `rw-api-change` | its row in `docs/backend/API.md` |
| Domain rules, product scope, deployment, dev env, test layers | `docs/INDEX.md` | one routed section |
| Why something is the way it is | `docs/adr/README.md` | one ADR |
| Verify · review · clean up | skills `rw-verify` · `rw-review` · `rw-cleanup` | — |

## Navigation (token budget)

- Go straight to the area map. Do not list or scan the repository recursively, and do not read areas the task does not touch.
- Large docs: `grep -n '^#' <file>` first, then read only the section you need.
- Find code with targeted search (`rg -n <symbol> <mapped dir>`), not repo-wide sweeps.
- Trust the maps and docs for structure; open implementation only after the task is narrowed to a few files.
- Never open generated files (`frontend/src/api/schema.d.ts`, `frontend/src/api/openapi.json`, `frontend/src/api/mock/*.json`, `backend/tests/openapi.snapshot.json`); regenerate them (`make gen-api`, `make record-mock`). `.ignore` keeps them out of search.
- Skip `docs/archive/**`, `legacy/**`, `build/`, `.udocker/` and `udocker-1.3.17/` unless the task names them (archive: frozen v2 docs, finished v3 runbook steps, the closed v3 audit).
- Stop gathering context once the change and its dependents are clear. Before changing behavior, read the owning doc section.

## Hard rules

| # | Rule |
|---|---|
| R1 | Never write to `source` roots (images, masks, input metadata). App state lives in the project folder; task outputs are written only into `derived` roots. Exceptions: CUR-16 (ADR-0029), PRJ-19 managed-folder writes (ADR-0030). See ADR-0002, ADR-0014. |
| R2 | No accounts, no passwords. Reviewer name is a free-text stamp. See ADR-0004. |
| R3 | One OCI image must run on Docker (local) **and** udocker (remote, no sudo). No compose-only features. See ADR-0007. |
| R4 | No sudo, apt, brew, or system installs on remote servers. Node runs only inside a container there. |
| R5 | No telemetry, no CDN, no external network calls at runtime. |
| R6 | Web app first. Electron starts only after roadmap phase P7 is done. See ADR-0001. |
| R7 | Do not suggest SSH tunnel commands; VS Code Remote handles port forwarding. |
| R8 | One fact, one place. Reference requirement IDs (e.g. `CUR-04`) instead of restating them. |
| R9 | `legacy/**` is read-only reference (git-ignored, `chmod a-w`; tag `legacy-reference`). Never import, build, lint, test or edit it; no code or doc may depend on it, so it can be deleted at any time. Read it only when a task says to port from it (e.g. `legacy/convert/` in P7b Wave 3). |

## Workflow

- Current phase and exit criteria: `docs/product/ROADMAP.md`. Work one phase at a time; stop for user confirmation between phases.
- Changing a decision in `docs/adr/` requires a new ADR that supersedes it.
- When behavior changes, update the single doc that owns it (`docs/INDEX.md` lists owners by ID prefix).
- Before calling work done: `rw-verify` picks the gate; `make check` is the full gate.

## Code standards

- Simplest solution that works; no speculative architecture, flags or abstractions for hypothetical needs.
- Prefer deleting code over adding it. Remove dead code, unused exports and duplicated logic you touch.
- No helper for a one-liner, no single-function `utils` file, no factory for two objects.
- Comments only for non-obvious *why*; never restate the code. Rename instead of explaining a name.
- Before editing a file, check what imports it and which tests cover it; update dependents in the same change.
- Refactor in small steps with tests green; do not mix behavior changes into a refactor.
- Review for correctness, rule violations (R1–R9), duplication and needless complexity before calling work done.
