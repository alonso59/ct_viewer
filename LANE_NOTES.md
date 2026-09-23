# Lane notes

Append-only handoff log between lanes and the integrator (docs/ops/AGENT_RUNBOOK.md).
Format: `## <date> · <lane> · <branch>`, then **Done**, **Requests for other paths**, **Open issues**.

## 2026-09-23 · Step 0 bootstrap · v3

**Done**
- v2 app moved to `legacy/`. v3 skeletons in `backend/` and `frontend/`; `Makefile`; `make fixtures` (13/13 QC codes, deterministic); `make check` green.
- Toolchain: Python 3.12 (uv venv at `backend/.venv`), Node native locally (RUNTIME=native).

**Open issues for later lanes**
- P1: `pyradiomics` is in the optional `[radiomics]` extra until the Python 3.12 spike passes (ADR-0006). Not installed by `make setup`.
- P1: Starlette warns that the TestClient's `httpx` backend is deprecated in favour of `httpx2`; revisit when adding API tests.
- Frontend pins: TypeScript ~5.9 (openapi-typescript and typescript-eslint reject 6+/7) and ESLint 9 (eslint-plugin-react rejects 10). Revisit when upstream supports them.
- `fingerprint_changed` fixture needs a test step: index, then modify `expected.json → mutate_after_index`, then revalidate.
- Extra warnings are expected alongside a defect's main code (e.g. `missing_seg` on the `unreadable_file` case); tests should assert inclusion, not exact sets.
