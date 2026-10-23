---
name: rw-verify
description: Run the smallest sufficient test/lint gate for a change in this repo and report results faithfully. Use before saying work is done or after editing backend, frontend, plugins or docs.
---

Commands run from the repo root. Gates and test layers: `docs/ops/TESTING.md`; dev loop: `docs/ops/DEV_ENV.md`. Rules: `AGENTS.md`.

Pick by what changed (`git status --short`), narrowest first:

| Changed | Run |
|---|---|
| backend/plugins/scripts | `cd backend && .venv/bin/python -m pytest -n 0 tests/<file>` then `make lint typecheck` |
| frontend | `cd frontend && npx vitest run <path>` then `npm run lint && npm run typecheck` |
| endpoint or schema | `rw-api-change` |
| runner / GPU / supervised | `make test-runner PYTEST_WORKERS=0 FULL_TESTS=1`; `make test-host` is opt-in |
| UI flow | `make e2e-one SPEC=<name>` (see TESTING.md for WebGL limits) |
| docs / requirement IDs | `make reqs` |

Before calling work done: `make check` (add `FULL_TESTS=1` for runner work). Bound workers on shared hosts: `PYTEST_WORKERS=2 VITEST_WORKERS=1`.

Report each command with pass/fail. On failure quote the output; never report green for a gate you did not run or that was skipped.
