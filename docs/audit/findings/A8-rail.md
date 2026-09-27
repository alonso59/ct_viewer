# A8 · Activity bar (rail) duplication

Scope: minimal audit of the left activity bar ("rail"): icons multiply while the app is used.
Read when: fixing or reviewing the registry / activity bar (FB9).
Depends: audit/PLAN.md, UI_SHELL (UI-01/02), FE ARCHITECTURE.

Run 2026-09-27 on `version_3-dev` @ `dc1b637`, reported by the owner from the dev server (`:5173`, screenshot: Project ×3, Image ×4, Labels ×4, Tasks ×4, Search ×4, Settings ×3 …). Reproduced on a separate Vite dev server in mock mode (`:5290`) with headless Chromium.

## Reproduction

| Step | Rail buttons |
|---|---|
| Open project | 13 (Project … Settings, correct) |
| `touch src/features/library/index.ts` (Vite HMR, no content change) | 21 |
| `touch src/app/bootstrap.ts` | 35 |
| Without HMR: Home ↔ project ×3 via history, palette open/close, full reload | 13 every time |

Only hot module replacement triggers it; a full reload clears it. Production builds have no HMR, so released images are not affected, but every dev session is (and it looks like a product bug).

## Root cause

- `shell/registry.ts` keeps contributions in module-level arrays filled with `push` + `sort`: `view()`, `panelTab()`, `tool()`, `status()`, `inspector()`, `quickOpenProvider()`, `overlay()`, `imageSectionContent()`. Only `command()` and `editor()` use a `Map` keyed by id.
- `app/bootstrap.ts` guards with a module-level `let done = false`, and `plugins/host.ts` with a module-level `active` map. When Vite re-executes a feature/plugin/bootstrap module, those guards start fresh, but the `registry` singleton (not re-executed) keeps its arrays, so every `register*()` / `activate()` appends a second copy.
- The same happens to panel tabs, tool-bar items, status items, Inspector sections, quick-open providers and overlays (not only the rail); duplicated overlays/status items can also double side effects.

## Findings

| ID | Sev | Path | Finding | Evidence | Proposal | Refs | Effort | Decision |
|---|---|---|---|---|---|---|---|---|
| AUD-A8-01 | P2 | all | Registry contributions are appended, not keyed by id, so any re-registration (Vite HMR today, any future re-activation) duplicates rail views, panel tabs, tools, status items, Inspector sections, quick-open providers and overlays. | Table above; `shell/registry.ts:164-196` (`push`), `app/bootstrap.ts` `done` guard, `plugins/host.ts` `active` map | Upsert by `id` in every registry list (replace the existing entry, then sort), so registration is idempotent and a hot-reloaded module replaces its component instead of adding one; unit test: register every kind twice → counts unchanged and the second component wins | UI-02 | S | fixed 2026-09-27 FB9 (proposal) |
| AUD-A8-02 | P2 | — | No test guards registry idempotence; `plugins/host.test.ts` checks `activatePlugins` twice only through the host's own `active` map, which HMR resets. | `plugins/host.test.ts:7-8` | Covered by the A8-01 test (call the feature `register*()` functions twice, not only `activatePlugins`) | UI-02, FE ARCHITECTURE | S | fixed 2026-09-27 FB9 (proposal) |

Fixed in FB9: every registry list upserts by id (`shell/registry.ts`); `shell/registry.idempotent.test.ts` re-executes bootstrap, features and plugins with fresh guards. Rechecked 2026-09-27 on a mock-mode dev server (`:5291`, headless Chromium): 13 → 13 → 13 → 13 after touching `features/library/index.ts`, `app/bootstrap.ts` and `plugins/curation/index.ts` (each an HMR update).
