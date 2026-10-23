---
name: rw-cleanup
description: This repo's deslop / anti-AI-slop skill. Behavior-preserving cleanup of working code - dead code, redundant wrappers, speculative abstractions, defensive noise, low-value comments. Use after a feature works or when asked to simplify, deslop or clean up.
---

Code standards: `AGENTS.md`. Dead-code policy: `docs/ops/TESTING.md` §Rules. Run only on code that already works; confirm a green baseline first (`rw-verify`).

Rules: preserve behavior; delete before rewriting; no new abstractions or dependencies; no redesign; no style-only churn; no commits or staging; API changes belong to `rw-api-change`.

1. Scope to the diff: `git diff HEAD --name-only` plus untracked. Do not widen.
2. Tools, in order:
   - `make fix` (ruff check --fix, ruff format, eslint --fix); review the resulting diff.
   - `make deadcode`: knip (frontend files, exports, deps) and vulture >= 80 (backend, plugins, scripts, tests). Delete what is reported. Allowlist only a verified false positive, with the reason: `backend/vulture_allowlist.py`, `frontend/knip.json`.
3. Manual pass over the scoped files; remove:
   - unused imports, variables, parameters, functions, files, dependencies
   - duplicated logic; wrappers or one-line helpers that only forward; single-implementation abstractions, unused options and flags
   - indirection with one caller; intermediate variables used once; state derivable from props or other state
   - defensive checks the types or callers already guarantee; try/except that only logs and re-raises or swallows; fallbacks that cannot trigger
   - comments that restate code; boilerplate docstrings; needless type assertions (`as`, `cast`, `# type: ignore` the checker no longer needs)
   - convoluted conditionals and deep nesting: early return, flatten, merge branches
   Keep checks at real boundaries (user input, files, HTTP, subprocess) and comments that explain a non-obvious why.
4. Before deleting or moving a symbol: grep its importers and covering tests; update dependents in the same change. If unsure it is unused (dynamic import, plugin entry, re-export, test fixture), keep it.
5. One small step at a time; after each batch run `make lint typecheck` and the tests of touched files. If a test must change meaning, revert that step.
6. Finish with `make deadcode lint typecheck` plus the relevant gate from `rw-verify`. Report: removed items, kept-with-reason, commands run with pass/fail.
