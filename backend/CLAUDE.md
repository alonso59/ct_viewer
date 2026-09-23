# backend/: local rules (root AGENTS.md still applies)

Python 3.12 · FastAPI · Pydantic v2. Package `app/`, dev tools in `tools/`, tests in `tests/`.

## Read for backend work
- `docs/backend/ARCHITECTURE.md` (layout, BE-*), `docs/backend/API.md` (API-*)
- The domain doc that owns your feature: `docs/domain/{PROJECT_FORMAT,INPUT_METADATA,DATA_MODEL,CURATION,RADIOMICS}.md`
- Tests: `docs/ops/TESTING.md`. Do not read `frontend/` or `legacy/` (except ROADMAP §Migration items).

## Rules
- Layering: `api/v1` → services (`projects|ingest|imaging|curation|radiomics|analytics|jobs|events`) → `core`. Services never import `api`.
- All path access via `core.paths` (BE-02); source files opened `rb` only (BE-03, R1).
- Errors are problem+json with slugs from API.md (BE-08). No outbound network (BE-11).
- Heavy work (radiomics, meshes, thumbnails, npy conversion) runs in job workers, never in the API process (BE-12).
- Every endpoint change updates the OpenAPI contract; run `make gen-api` and commit `frontend/src/api/schema.d.ts`.
- QC codes: `app/ingest/codes.py` is the single source; keep it equal to INPUT_METADATA.md.

## Commands (from repo root)
- `make check`: ruff, ruff format, mypy --strict, pytest (+ frontend). Must be green before commit.
- `make fixtures`: synthetic dataset in `.fixtures/synthetic/` with `expected.json` listing every defect.
- `make dev-backend`: API on 127.0.0.1:8000 with the workspace in `.workspace/`.
- Remote server: `make setup-backend VENV=$CONDA_PREFIX` inside the conda env.
