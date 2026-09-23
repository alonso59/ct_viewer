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
| `make test` | Backend + frontend unit tests |
| `make e2e` | Playwright against a running dev stack |
| `make image` | Build the OCI image (Docker only) |
| `make udocker-run` | `scripts/udocker-run.sh` |

## Rules

- No machine-specific absolute paths in repo files; use `.env` (`DATA_HOST`, `WORKSPACE_HOST`, `ALLOWED_DATA_ROOTS`).
- On remote servers: never use sudo/apt; Node runs only through udocker (AGENTS R4).
- Remote port forwarding is handled by VS Code (AGENTS R7).
- The dev workspace defaults to `./.workspace/` (gitignored).
