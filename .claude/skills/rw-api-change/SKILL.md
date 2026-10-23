---
name: rw-api-change
description: Add or change a backend HTTP endpoint or response model and keep OpenAPI snapshot, frontend types, mock recording and API docs in sync.
---

Contract owners: `docs/backend/API.md` (API-* rows, problem+json slugs, BE-08), `docs/backend/ARCHITECTURE.md` (BE-*). Frontend types gate: FE-03.

1. Change `backend/app/api/v1/*` (api -> services -> core only).
2. Update the API-* row / slug in `docs/backend/API.md`.
3. `make gen-api` (writes `backend/tests/openapi.snapshot.json` and `frontend/src/api/schema.d.ts`).
4. Update `frontend/src/api/hooks.ts` / `index.ts` for the new shapes.
5. If an exchange used by the mock changed: `make record-mock`.
6. Gate: `make api-types lint typecheck`, then backend tests for the endpoint and `cd frontend && npx vitest run src/api`.
7. Stage the snapshot and `schema.d.ts` with the code; never hand-edit `schema.d.ts`.
