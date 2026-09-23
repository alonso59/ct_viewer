# frontend/: local rules (root AGENTS.md still applies)

React 19 · TypeScript 5.9 strict · Vite · Vitest · ESLint 9 · i18next.

## Read for frontend work
- `docs/frontend/ARCHITECTURE.md` (stack, layout, FE-*)
- `docs/frontend/UI_SHELL.md` for shell, theme, icons, keybindings; `docs/frontend/VIEWER.md` for the viewer; `docs/frontend/DASHBOARD.md` for dashboards
- API contract: `docs/backend/API.md` + generated `src/api/schema.d.ts`. Do not read `backend/` internals or `legacy/`.

## Rules
- Feature-sliced: `src/features/<name>/` exposes only `index.ts`; never import another feature's internals. `src/shell/` has no domain logic.
- No hard-coded UI text: use `t()` with keys in `src/i18n/en.json` (FE-11; `react/jsx-no-literals` enforces it).
- No `any` (FE-01). Server data only through TanStack Query (FE-02). No external network or CDN (FE-06).
- Colors only from theme tokens (UI-11); icons are codicons + the custom CT set (UI-15). No MUI (ADR-0008).
- NiiVue is imported only in `src/features/viewer/engine/` (VIEWER.md wrapper contract).
- Pinned toolchain: TypeScript ~5.9 (openapi-typescript and typescript-eslint do not support 6+/7 yet); ESLint 9 (eslint-plugin-react does not support 10).

## Commands (from repo root)
- `make check`: lint, typecheck, unit tests (+ backend). Must be green before commit.
- `make dev-frontend`: Vite on 127.0.0.1:5173, proxying `/api`. `make gen-api` after backend contract changes.
- Remote servers: Node only through udocker (`RUNTIME=udocker`, `make setup-node` once; AGENTS R4).
