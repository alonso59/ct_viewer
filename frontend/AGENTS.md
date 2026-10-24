# frontend/ map

React 19 · TypeScript ~5.9 strict · Vite · Vitest · Playwright · i18next. Pinned: TypeScript stays ~5.9 (openapi-typescript and typescript-eslint do not support 6+/7 yet); ESLint stays 9 (eslint-plugin-react does not support 10).

**Owns** (folder detail: `docs/frontend/ARCHITECTURE.md` §Folder layout)
- `src/shell/`: workbench chrome, command registry, keybindings; no domain logic.
- `src/features/<name>/`: product areas (projects, import, open, explorer, viewer, tasks, phase, variables, library, jobs).
- `src/plugins/<name>/`: first-party UI plugins (curation, labeling, radiomics, dashboard, dicom, analyzers, packs); `host.ts` activates them.
- `src/api/`: typed client over the generated schema, query keys, SSE; `src/state/` cross-feature stores; `src/i18n/`, `src/theme/`, `src/lib/` shared pieces.
- `e2e/`: Playwright specs against a real backend on the fixtures.

**Entry points:** `src/main.tsx` → `src/app/` (providers, router, bootstrap); `src/plugins/index.ts` (first-party list).

**Boundaries**
- A feature or plugin exposes only its `index.ts`; slices depend one way, no cycles (`src/app/boundaries.test.ts`). Cross-slice calls go through registry commands.
- NiiVue is imported only in `src/features/viewer/engine/` (VIEWER.md).
- UI text only through `t()` (FE-11); no `any` (FE-01); server data only through TanStack Query (FE-02); no external network or CDN (FE-06); colors from theme tokens (UI-11); codicons + CT icon set (UI-15); no MUI (ADR-0008).

**Tests:** Vitest next to the code (`*.test.ts(x)`; DOM tests start with `// @vitest-environment jsdom`), run against the recorded mock API (TESTING.md §Mock API). E2E: `make e2e-one SPEC=<name>`. Gate selection: skill `rw-verify`.

**Change together**
- Backend contract change → skill `rw-api-change` (never hand-edit `src/api/schema.d.ts`).
- New UI string → `src/i18n/en.json` (or `en.lazy.json` for lazy chunks).
- Initial bundle growth → `make bundle-size`; intended growth → `make bundle-baseline` (NFR-07).

**Read more:** shell, theme, icons, keys `docs/frontend/UI_SHELL.md`; viewer `docs/frontend/VIEWER.md`; dashboard `docs/frontend/DASHBOARD.md`; state, routes, API layer `docs/frontend/ARCHITECTURE.md`. Read headings first; these files are large.
