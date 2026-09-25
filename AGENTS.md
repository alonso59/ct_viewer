# AGENTS.md

Agent entry point. Keep this file short; details live in `docs/`.

## Read order (token budget)

1. This file.
2. `docs/INDEX.md` — pick **only** the docs routed for your task.
3. Never read `docs/archive/**` (frozen history: v2, finished v3 runbook steps) unless the task says so (e.g. v2 migration).

## Product in one line

Local-first, browser-based CT workbench: inspect NIfTI and DICOM volumes (single
files open without a project), visualize segmentations (never edited in place),
curate datasets, run tasks (DICOM conversion, metadata analyzers, radiomics,
segmentation models such as nnU-Net), and review feature QC in a dashboard. QuPath-style layout in a VS Code shell (GitHub Dark,
codicons) with a 3D Slicer-style 2×2 CT viewer.

## Hard rules

| # | Rule |
|---|---|
| R1 | Never write to `source` roots (images, masks, input metadata). App state lives in the project folder; task outputs are written only into `derived` roots. See ADR-0002, ADR-0014. |
| R2 | No accounts, no passwords. Reviewer name is a free-text stamp. See ADR-0004. |
| R3 | One OCI image must run on Docker (local) **and** udocker (remote, no sudo). No compose-only features. See ADR-0007. |
| R4 | No sudo, apt, brew, or system installs on remote servers. Node runs only inside a container there. |
| R5 | No telemetry, no CDN, no external network calls at runtime. |
| R6 | Web app first. Electron starts only after roadmap phase P7 is done. See ADR-0001. |
| R7 | Do not suggest SSH tunnel commands; VS Code Remote handles port forwarding. |
| R8 | One fact, one place. Reference requirement IDs (e.g. `CUR-04`) instead of restating them. |
| R9 | `legacy/**` is read-only reference (git-ignored, `chmod a-w`; tag `legacy-reference`). Never import, build, lint, test or edit it; no code or doc may depend on it, so it can be deleted at any time. Read it only when a task says to port from it (e.g. `legacy/convert/` in P7b Wave 3). |

## Workflow

- Current phase and exit criteria: `docs/product/ROADMAP.md`.
- Work one phase at a time; stop for user confirmation between phases.
- Changing a decision in `docs/adr/` requires a new ADR that supersedes it.
- When behavior changes, update the single doc that owns it (see ownership in `docs/INDEX.md`).
- Coding best-practice skills: `.codex/skills/` (read only the skill relevant to the task).
