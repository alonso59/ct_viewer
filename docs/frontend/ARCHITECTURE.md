# Frontend Architecture

Scope: stack, folder layout, state, routing, boundaries.
Read when: writing any frontend code. UI look: UI_SHELL.md. Viewer: VIEWER.md.
Depends: backend/API.md, ADR-0001, ADR-0003, ADR-0008, ADR-0018.

## Stack

| Concern | Choice |
|---|---|
| Core | React 19, TypeScript (strict), Vite |
| Server state | TanStack Query; SSE events patch or invalidate caches |
| UI state | Zustand (small stores per concern) |
| Routing | React Router v7 (library mode) |
| Docking layout | dockview (VS Code-like tabs, splits, drag-to-dock) |
| Primitives | Radix UI (menu, dialog, select, tooltip, tabs), styled by our tokens; **no MUI** (ADR-0008) |
| Icons | `@vscode/codicons` (bundled font/SVG) |
| Command palette | cmdk |
| i18n | i18next + react-i18next; English only in v3 |
| Tables / trees | TanStack Table + TanStack Virtual |
| Viewer | `@niivue/niivue` (ADR-0003) |
| Charts | Apache ECharts (canvas; large-scatter mode) |
| API client | `openapi-typescript` + `openapi-fetch` (generated types) |
| Tests | Vitest + Testing Library; Playwright E2E |

## Folder layout (feature-sliced)

```text
frontend/src/
├── app/          # providers, router, bootstrap, error boundary
├── shell/        # ActivityBar, SideBar, EditorArea(dockview), Panel, StatusBar, CommandPalette, keybindings
├── features/
│   ├── projects/   # workspace home, new project, relink, bundle export/import (lazy report), full-hash action
│   ├── import/     # import wizard: adapter detect, NIfTI pattern preview, identity (IMP-*, SRC-*)
│   ├── open/       # Open mode: file/folder → viewer without a project; NumPy axis dialog (SRC-09..12)
│   ├── tasks/      # generic schema form, selection, preflight, estimate, runs, annotations (TSK-*, ANZ-*)
│   ├── explorer/   # case tree, filters, quick open
│   ├── viewer/     # NiiVue wrapper, layouts, tools, overlays, 3D (VW-*)
│   ├── library/    # Plugin Library view (UI-22, PLG-05)
│   └── jobs/
├── plugins/        # host.ts (FrontendPlugin, activatePlugins, openerOf) + index.ts (FIRST_PARTY)
│   ├── curation/   # inspector form, history, queue (CUR-*)
│   ├── radiomics/  # schema-driven settings form, profiles, runs (RAD-*)
│   ├── dashboard/  # views (DB-*)
│   ├── dicom/      # converter command (overlay: P7c Wave 3)
│   └── analyzers/  # opens the analyzer task tabs
├── api/          # generated schema.d.ts, client, query keys, useProjectEvents (SSE)
├── state/        # cross-feature stores: reviewer, layout, viewerSync
├── i18n/         # en.json (all UI strings); other locales later
├── theme/        # tokens.css (dark/light), codicon import
└── lib/
```

**Boundaries:** a feature or plugin exposes only its `index.ts` (plugins export `plugin: FrontendPlugin`). Features and plugins never import another one's internals; plugins may use feature `index.ts` exports.
`shell/` holds no domain logic; features register views and commands through a registry (UI-02).

## Routes

| Path | Opens |
|---|---|
| `/` | Workspace home (projects) |
| `/p/:pid` | Workbench shell for the project |
| `/p/:pid/case/:cid?item=&layout=` | Workbench + case editor tab |
| `/p/:pid/run/:rid?view=` | Workbench + dashboard tab |
| `/p/:pid/radiomics` | Workbench + radiomics settings tab |
| `/p/:pid/task/:tid` | Workbench + task settings tab |
| `/p/:pid/settings` | Workbench + project settings tab (UI-23) |
| `/p/:pid/labeling/:tid` | Workbench + label table tab (LBL-03) |
| `/v/:token` | View-only workbench (UI-26, API-60) |
| `/open/:sid` | Open mode viewer (no project); `/open` with a path in the history state opens it and replaces itself with `/open/{sid}` (`features/open/navigate.ts`, SOURCES §Open mode) |

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| FE-01 | TypeScript `strict`; no `any` in `features/`. | M |
| FE-02 | Server data only via TanStack Query; query keys centralized in `api/keys.ts`. | M |
| FE-03 | API types generated from OpenAPI (`npm run gen:api`); CI checks they are up to date. | M |
| FE-04 | The URL encodes project, case, item and layout; open editor tabs persist per project in `localStorage`. | M |
| FE-05 | Lazy-load the viewer, radiomics and dashboard chunks; initial JS ≤ 300 KB gzip (NFR-07). | S |
| FE-06 | No runtime network calls outside the app origin; fonts and icons are bundled. | M |
| FE-07 | Electron readiness: no Node or DOM-global hacks; the API base URL is configurable. | M |
| FE-08 | Keyboard- and screen-reader-friendly tree, tabs and dialogs (ARIA roles, focus rings). | S |
| FE-09 | Every async surface has loading, empty and error states (problem+json `title`/`detail`). | M |
| FE-10 | The reviewer name comes from `state/reviewer` and is sent as `X-Reviewer` on writes. | M |
| FE-11 | No hard-coded UI strings: all text goes through `t()` with keys in `i18n/en.json`. Dates and numbers use `Intl`. A lint rule flags literal JSX text. | M |

## API layer (P2)

- `src/api/surface.ts` defines the `Api` interface; `http.ts` implements it against the backend (adapting wire shapes such as the variables `Catalog`), `mock/` implements it for the prototype. Every feature goes through it, radiomics included (API-30..37, types from `schema.d.ts`; validation key `keys.validation`). The mock's radiomics members lazily load the live schema fixture and the form's validation rules. The http client resolves `fetch` per call so tests can stub it.
- Env: `VITE_API_MODE` (`http` | `mock`), `VITE_API_BASE` (FE-07), `VITE_PORT`, `VITE_API_PROXY` (dev proxy target; it flushes SSE headers so the stream opens immediately).
- Initial JS is 289 KB gzip (Step 3b; gzip -9 of the entry script in `dist/index.html` plus its static-import closure, i.e. the `modulepreload` set); NFR-07 allows 300 KB, so new eager dependencies need a lazy boundary.
- `CaseFilter.itemIds` (DB-04) is applied client-side on API-20 results (the case id is the `item_id` prefix); `features/explorer` exports a read-only `useExplorerFilter()` and `showItemsInExplorer(ids)`.

- i18n is split: `i18n/en.json` (eager) and `i18n/en.lazy.json`, loaded by `i18n/lazy.ts` from lazy chunks (dashboard, analysis, curation, queue, radiomics settings). Put strings used only in a lazy chunk into `en.lazy.json` (NFR-07). The key-coverage tests merge both files.
- Initial JS after P7b: 295.1 KB gzip (same method). The import wizard is its own chunk (`features/import/LazyImportWizard.tsx`); its store and `FolderBrowser` stay eager. Brand images are static files (`public/brand/`, UI-21), never imported into JS.
