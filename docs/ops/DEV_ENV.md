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

`make help` lists every target with its purpose, by group (setup, dev, check, E2E, docs, image, deploy); the Makefile is the single source.

Knobs: `RUNTIME=native|docker|udocker` selects how Node commands run (default: `native` locally, `udocker` if `node` is missing); `VENV` selects the Python env (`$CONDA_PREFIX` on remote servers); `PYTEST_WORKERS` / `VITEST_WORKERS` bound test workers (`PYTEST_WORKERS=0` runs serially); `FULL_TESTS=1` requires radiomics and refuses skipped coverage; `make -j4 check` runs the independent gates in parallel.

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
- Full verification uses `backend/requirements-ci.lock` (Python 3.12, uv 0.9.2); sync into an explicitly selected disposable venv, then install `backend` editable with `--no-deps`. Pass that absolute venv as `VENV` to Make. The existing development environment need not be upgraded.
- `Dockerfile.verify` is CI-only: Node 22 and Python 3.12 on matching Debian bases, locked Python/Node dependencies, browser binaries installed by the locked Playwright CLI. It is separate from the product image; its strict source allowlist excludes data, local settings, venvs and legacy reference. Image publication depends on this verification workflow.
