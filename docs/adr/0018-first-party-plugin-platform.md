# ADR-0018 First-party plugin platform and Plugin Library
Status: Proposed · Date: 2026-09-24
Amends: ADR-0016 (tasks become one contribution type; no third-party plugins in v3), TSK-01

**Context.** The converter, the analyzers, radiomics, the dashboard and curation are all wired as separate features. The owner wants one model where every domain tool is a plugin, reachable from a single Library, with a small core underneath. Loading third-party code at runtime conflicts with R5 and with the NFR-07 budget, and the owner has ruled it out for this version.

**Decision.** Details: PLUGINS.md (PLG-*).
1. **Core vs plugins.**
   - The core is the shell, the viewer with its CT tools, Open mode, neutral projects (ADR-0019), the plugin host, the metadata table (ADR-0020), the event store (ADR-0022), jobs, SSE and roots.
   - Every domain tool is a plugin.
2. **First-party only in v3.**
   - Every plugin lives in this repo under `plugins/<id>/`, with a `plugin.json` manifest, a backend part (Python) and a frontend part (`frontend/src/plugins/<id>/`, lazy chunks).
   - Third-party plugins and marketplaces are out of scope.
   - `PLUGINS_ROOT` only points the host runner (TSK-11) at the host copy of first-party plugins with an `external` runtime.
3. **Contribution points** (declared in `plugin.json`, registered through the shell registry, UI-02):
   - `tasks` (TSK protocol);
   - `views`, `editors`, `panels`, `commands`;
   - `overlays` (modal work windows, e.g. the converter);
   - `columns` (metadata layers, ADR-0020);
   - `packs` (study packs, ADR-0019).
4. **Installation.** All shipped plugins are installed per workspace and enabled by default. Per-project enable/disable and plugin management come later (PLG-10).
5. **Plugin Library.** It is one activity-bar view listing every plugin with its version, what it adds, and a status (`ready`, `needs runner`, `needs derived root`, `needs segmentation`, `pending`). Each entry has an **Open** action to the plugin's main surface. It is the single entry point for tools.
6. **Existing features are repackaged** as plugins without behaviour changes: converter, analyzers, radiomics, dashboard/analysis, curation. Their routes and data stay where they are, and new plugins mount under `/api/v1/plugins/{id}/`.

**Consequences.**
- \+ One mental model and one place to find tools.
- \+ The core stays small.
- \+ No runtime code loading.
- − A repackaging pass with no user-visible change.
- − Third-party extension waits for a later version.
- Owner docs on acceptance: PLUGINS.md (new, PLG-), TASKS (TSK-01), FE/BE ARCHITECTURE, UI_SHELL (Library view), VISION, INDEX, GLOSSARY.

**Rejected.**
- Third-party JS loaded at runtime: R5, NFR-07, trust.
- Declarative-only external plugins: not needed while every plugin is first-party.
