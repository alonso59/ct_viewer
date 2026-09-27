# Dev Environment

Scope: running backend + frontend during development, locally and on a remote no-sudo server.
Read when: setting up a machine or changing Makefile/dev scripts.
Depends: DEPLOYMENT.md.

## Modes

| Mode | Backend | Frontend | When |
|---|---|---|---|
| Local (macOS/Linux with Docker) | Native Python 3.12 venv/conda **or** dev container | Native Node 22 **or** dev container | Daily development |
| Remote (no sudo) | Conda env `rw` (Python 3.12), native | Node 22 inside udocker container `rw-node` (R4) | Server-side data access |

## Make targets (runtime-agnostic)

`RUNTIME=docker|udocker|native` selects how Node commands run (default: `native` locally, `udocker` if `node` is missing).

| Target | Does |
|---|---|
| `make setup` | Create the Python env, install `backend[dev]`, install frontend deps (via RUNTIME) |
| `make dev-backend` | `uvicorn app.main:app --reload --host $HOST --port 8000` |
| `make dev-frontend` | Vite dev server on 5173, proxying `/api` → 8000 |
| `make fixtures` | Generate the synthetic test dataset (TST-11) |
| `make gen-api` | Regenerate TS types from OpenAPI (FE-03) |
| `make test` | Backend unit tests in parallel (`pytest -n auto --dist loadscope`, pytest-xdist: one worker per test module, so module fixtures run once) + frontend unit tests |
| `make deadcode` | Dead-code gate (part of `make check`): `knip` (frontend unused files, exports, dependencies; `frontend/knip.json`) + `vulture` (backend, confidence ≥ 80; false positives go to `backend/vulture_allowlist.py`) |
| `make coverage` | Vitest coverage (`@vitest/coverage-v8`) → `build/coverage/frontend/` (summary printed; a report, not a gate) |
| `make bundle-baseline` | Record the current initial JS in `frontend/bundle-baseline.json` (commit it) after an intended growth (NFR-07) |
| `make check` | The CI gate: lint, types, unit tests, `make deadcode`, API types, `make bundle-size` (NFR-07), requirement check; `make -j4 check` runs the parts in parallel |
| `make fix` | Autofix: `ruff check --fix`, `ruff format`, `eslint --fix` |
| `make e2e` | Playwright, both browsers, own servers (`SPEC=…`, `PROJECT=chromium\|firefox` narrow it) |
| `make e2e-one SPEC=…` | One spec in one browser (Chromium unless `PROJECT=`) |
| `make e2e-servers` | The E2E backend + web server in the foreground; then `E2E_REUSE=1 make e2e-one SPEC=…` reuses them |
| `make record-mock` | Re-record the mock API from the backend on the fixtures (TESTING §Mock API) |
| `make image` | Build the OCI image (Docker only) |
| `make udocker-run` | `scripts/udocker-run.sh` |
| `make reqs` | Requirement tables check (part of `make check`; SRS §1.5) |
| `make docs` · `make docs-srs` · `make trace` | Docs site → `build/docs/` (pinned Sphinx via `uvx`) · SRS review table → `build/docs-srs/` · ID → code/test citations → `build/trace/` |

## Rules

- No machine-specific absolute paths in repo files; use `.env` (`DATA_HOST`, `WORKSPACE_HOST`, `ALLOWED_DATA_ROOTS`).
- On remote servers: never use sudo/apt; Node runs only through udocker (AGENTS R4).
- Remote port forwarding is handled by VS Code (AGENTS R7).
- The dev workspace defaults to `./.workspace/` (gitignored).

## Notes

- Port 5173 is held by VS Code on the dev Mac: use `VITE_PORT` (lanes used 5174/5175).
- `make e2e` starts its own backend (port 8011) and Vite (5174) on a temporary workspace (removed afterwards unless `E2E_KEEP=1`); run `make fixtures` first and keep 5174 free, or set `E2E_API_PORT` / `E2E_WEB_PORT`.
- Dev-only tools (`backend[dev]`: pytest-xdist, vulture; `frontend` devDependencies: knip, @vitest/coverage-v8) are never in the image (the Dockerfile installs `backend[radiomics]` and the built frontend only; R5).
- PyRadiomics is optional: `VIRTUAL_ENV=backend/.venv uv pip install -e 'backend[radiomics]'` (needs a C compiler). Without it, 3 test modules are skipped.
