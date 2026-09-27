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
| 3b | Orchestrator + sub-agents (one terminal) | — | — | Checks green |
| P7b | — | One sequential session (all waves) | — | Your check after Wave 1; P7b exit |
| 4 | Review | P7 on remote server (udocker, Dataset820, perf), after P7b | — | NFRs met |
| 5 | P8 Electron | — | — | Release |

## Lanes (parallel work; moved from ROADMAP 2026-09-27)

A lane edits **only** the paths it owns. Anything it needs elsewhere goes into its commit message as a note for the integrator.
Every lane may also tick its own lines in `product/ROADMAP.md`.

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
| 4 | P7 remote verification | `v3` | Shell (remote server) | `scripts/**`, `docs/ops/DEPLOYMENT.md` (udocker notes) |
| P7b | Waves 1–4, sequential | `v3` | one Claude shell session (user decision 2026-09-24) | per wave, see §P7b |
| 5 | P8 Electron | `lane/5-electron` | VS Code | `desktop/**` |

Shared files that only the integrator edits: `Makefile`, `backend/pyproject.toml` dependency list, `frontend/package.json`/lockfile (lanes may add dependencies in their own branch; the integrator resolves lockfile conflicts at merge), `AGENTS.md`, `docs/INDEX.md`.

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
  change elsewhere, note it for the integrator in your commit message and continue.
- Implement against requirement IDs; cite IDs in commit messages.
- Run the lane's checks before every commit. Never commit red.
- Use sub-agents in parallel for independent modules within your lane.
- Do not run npm/node outside a container on the remote server (AGENTS R4).
- Commits are local only. Never git push.
- Dev servers: port 5173 is taken by VS Code on the dev Mac; use the port given in the lane prompt.
- When the lane's exit criteria pass: tick the tasks in docs/product/ROADMAP.md
  (only your lines), commit with a summary (and integrator notes) in the message, and STOP.
- If a requirement is ambiguous or contradicts another, stop and ask. Do not guess.
```

---

## Finished steps

Steps 0 to 3b, P7b, P7c and the P7c addendum are done; their prompts are frozen in `archive/v3/AGENT_RUNBOOK-done.md`.

## Step 4: Shell on the remote server (P7)

```text
[LANE RULES]
Lane: P7. You are on the remote no-sudo server. Branch: v3 (after I merge Step 3).
Read: docs/ops/DEPLOYMENT.md, docs/ops/TESTING.md, docs/product/NFR.md.
Owns: scripts/**, docs/ops/DEPLOYMENT.md (udocker notes only).
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
