# UI Shell (QuPath layout × VS Code shell × GitHub Dark)

Scope: workbench layout, QuPath-style panes, toolbar, panels, status bar, commands, keybindings, theme, icons.
Read when: building shell, navigation, theming, icons, or keyboard UX.
Depends: frontend/ARCHITECTURE.md, ADR-0008, ADR-0010. Viewer internals: VIEWER.md.

## Concept

| Borrowed from | What |
|---|---|
| **QuPath** | Project-centric left pane with tabs (Project · Image · Curation · Labels · History), an image list with thumbnails, a tool toolbar above the viewer, and a Measurements table for the selected object |
| **VS Code** | Activity bar, editor tabs + splits, bottom panel, status bar, command palette, quick open, keybindings |
| **GitHub Dark** | Colors, borders, density, and badge/label style (Primer) |
| **3D Slicer** | The central 2×2 CT viewer (axial / sagittal / coronal / 3D), the addition beyond QuPath |

## Layout

```text
┌────────────────────────────────────────────────────────────────────────────────┐
│ ◧ Dataset820 ▾   File Edit View Project Radiomics Help   [⌕ Go to case… ⌘P]    │ title bar
├────────────────────────────────────────────────────────────────────────────────┤
│ ✥ ◐ ⌖ 🔍 │ ▦ 2×2 ▾ │ ◉ Overlay  ◌ Outline │ W/L [Soft tissue ▾] │ ↺ │ 📷          │ tool bar (QuPath style)
├──┬──────────────────────┬──────────────────────────────────────────────────────┤
│AB│ PROJECT  ▾           │ [case_00042 · NP · full ×] [Run NP tumor ×]          │ editor tabs
│  │ ⌕ filter cases       │ ┌─────────────────────────┬─────────────────────────┐│
│▣ │ ┌──┐ case_00041  ✓   │ │ Axial            114/600│ Sagittal         256/512││
│🛈 │ │▓▓│ A · NP CMP      │ │                         │                         ││
│☑ │ └──┘                 │ ├─────────────────────────┼─────────────────────────┤│
│🏷 │ ┌──┐ case_00042  ⚠ 2 │ │ Coronal          240/512│ 3D                      ││
│⟲ │ │▓▓│ A · NP CMP NC   │ │                         │                         ││
│⚗ │ └──┘   ▾ NP 01 full ●│ └─────────────────────────┴─────────────────────────┘│
│📈│         NP 01 VOI L  ├──────────────────────────────────────────────────────┤
│  │                      │ MEASUREMENTS │ PROBLEMS 2 │ HISTORY │ OUTPUT │ JOBS   │ panel
│⚙ │ ─ Image ─────────────│ feature              value   z     (run: NP tumor)  │
│  │ 512×512×600 · int16  │ firstorder_Mean      38.2   0.4                      │
│  │ 0.78×0.78×1.0 mm     │ shape_MeshVolume   42 113   3.9 ⚠                    │
├──┴──────────────────────┴──────────────────────────────────────────────────────┤
│ ⎇ Dataset820 · ● live · ⟳ radiomics 42/320        ijk 212,188,114 · HU 38 · W400 L50 · Dr. AP │
└────────────────────────────────────────────────────────────────────────────────┘
```

AB = activity bar. The left pane has a QuPath-style split: the active view on top, and a compact **Image** properties section below it (collapsible). Image is also a full activity-bar view; views that need the height (Search, Radiomics, Dashboards, Settings) hide the section.
An optional right **Inspector** (curation form, layers, W/L) toggles with `Ctrl/Cmd+Alt+B`; it is closed by default to keep the QuPath feel.

## Left pane views (activity bar)

| View | Codicon | QuPath analog | Content |
|---|---|---|---|
| Project | `files` | Project tab | Case list with **axial thumbnails** (IMP-12), status and warning badges; expands to phase → scan → items |
| Image | `info` | Image tab | Properties of the active item: geometry, spacing, dtype, phase (canonical/raw/source), paths (advanced) |
| Curation | `checklist` | Annotations | Decisions for the active case/item, a quick status bar, the correction queue |
| Labels | `tag` | Classes list | Project label map: swatch, visibility, opacity, hotkey |
| History | `history` | Workflow | Curation event log for the case (CUR-14) |
| Radiomics | `beaker` | — | Profiles, runs, "New run" |
| Dashboards | `graph` | — | Completed runs → dashboard tab |
| Search | `search` | — | Advanced filters (group, phase, status, warnings, VOI) |
| Settings *(bottom)* | `settings-gear` | Preferences | Theme, reviewer name, keybindings |

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| UI-01 | Shell regions as drawn: title bar, tool bar, activity bar, left pane, editor area, panel, status bar, optional inspector. | M |
| UI-02 | Features register views, editor types, tools, inspector sections, panel tabs, commands and status items in a registry, and the shell renders them. | M |
| UI-03 | Editor tabs: case, radiomics settings, run dashboard, correction queue, welcome. Tabs support preview mode (italic until pinned), drag, split and close-others. | M |
| UI-04 | Workspace home (`/`) looks like the QuPath/VS Code welcome: New Project, Open Recent (with thumbnail and progress), and a share-link copy button. | M |
| UI-05 | Command palette `Ctrl/Cmd+Shift+P` shows all commands; quick open `Ctrl/Cmd+P` jumps to a case or item. The title-bar search box opens quick open. | M |
| UI-06 | Tool bar (QuPath style) holds viewer tools and toggles; the active tool is highlighted; each button has a tooltip with its shortcut. | M |
| UI-07 | Status bar shows project, live/offline SSE state, job progress, cursor ijk/RAS/HU, W/L, reviewer (click to change). | M |
| UI-08 | Project list: 22 px rows (compact) or 56 px rows with thumbnail (default), virtualized, navigable with the keyboard; the badge follows the curation rollup (CUR-08). | M |
| UI-09 | The Problems panel lists QC warnings (IMP-08) grouped by case; clicking one opens the item. | M |
| UI-10 | Notifications are toasts at bottom-right, e.g. "case_00042 updated by Dr. AP". | S |
| UI-11 | GitHub Dark is the default theme and GitHub Light the alternative; all colors come from tokens (`theme/tokens.css`). The Settings choice (`dark`, `light`, `system`) decides; `dark` applies until the user picks another, whatever the OS preference. | M |
| UI-12 | Keybindings (below) are overridable in Settings and stored in `localStorage`. | S |
| UI-13 | Layout state (pane sizes, visibility, open tabs) persists per project. | S |
| UI-14 | Measurements panel: features of the active item from the selected run (API-36 `item_id` filter), with a robust z-score column; outliers are marked. | S |
| UI-15 | CT-specific icons (axial/sagittal/coronal plane, W/L, crosshair, layout grid, outline, VOI L/R) are a custom SVG set drawn to codicon rules: 16 px grid, `currentColor`, same stroke weight. Set (`theme/icons/CtIcon.tsx`): plane-axial/sagittal/coronal, view-3d, window-level, crosshair (tool), crosshair-lines (show/hide crosshair), layout-four-up/conventional/three-mpr/one-up, label-overlay, label-outline, voi-left/right, slice-stack. | M |
| UI-16 | Motion is limited to ≤150 ms fades/slides and respects `prefers-reduced-motion`. | S |

## Default keybindings

| Keys | Command | Keys | Command |
|---|---|---|---|
| `Ctrl/Cmd+Shift+P` | Command palette | `Ctrl/Cmd+P` | Quick open case |
| `Ctrl/Cmd+B` | Toggle left pane | `Ctrl/Cmd+J` | Toggle panel |
| `Ctrl/Cmd+Alt+B` | Toggle inspector | `Alt+W` | Close tab (browsers reserve `Ctrl/Cmd+W`; Electron uses `Ctrl/Cmd+W`) |
| `Alt+↓` / `Alt+↑` | Next / previous case (filtered order) | `F8` | Next problem |
| `A` | Mark accepted* | `Shift+1` / `Shift+2` | Needs minor / major correction* |
| `X` | Rejected* | `Q` | Add to correction queue* |
| `1`–`9` | Toggle label visibility* | `L` | Cycle viewer layout* |
| `M` / `W` / `C` / `Z` | Tools: move/pan, window-level, crosshair, zoom* | `R` | Reset view* |

\* Only active while the viewer has focus. Curation keys target the active item and the default target `seg`.

## Theme tokens: GitHub Dark (Primer)

Values follow the GitHub Dark Default VS Code theme; check them against the pinned theme version when implementing.

| Token | Value | Token | Value |
|---|---|---|---|
| `--bg-editor` | `#0D1117` | `--fg` | `#E6EDF3` |
| `--bg-sidebar` | `#010409` | `--fg-muted` | `#7D8590` |
| `--bg-activitybar` | `#010409` | `--border` | `#30363D` |
| `--bg-panel` | `#010409` | `--border-muted` | `#21262D` |
| `--bg-overlay` (menus, popovers) | `#161B22` | `--focus` | `#1F6FEB` |
| `--bg-tab-active` | `#0D1117` | `--bg-tab-inactive` | `#010409` |
| `--tab-active-indicator` | `#F78166` | `--accent` | `#2F81F7` |
| `--bg-statusbar` | `#0D1117` | `--bg-viewport` | `#000000` |
| `--ok` | `#3FB950` | `--warn` | `#D29922` |
| `--error` | `#F85149` | `--done` | `#A371F7` |
| `--btn-primary` | `#238636` | `--bg-hover` | `#1F2428` |

- **Typography:** `-apple-system, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif`. Sizes are 13 px UI, 12 px panels, 11 px badges; `ui-monospace` for numbers.
- **Shape:** 6 px radius on buttons, inputs and cards; 1 px borders; no shadows except overlays.
- **Badges:** Primer "Label" pills (outline in the status color, 11 px), used for phase chips and QC status.
- **Icons:** codicons (VS Code) plus the custom CT set (UI-15). Octicons are not mixed in.
- Viewport accent colors (per-plane borders and crosshairs) are owned by VW-04.
- GitHub Light values and the categorical palette (`--cat-1..8`, DB-07) are in `theme/tokens.css`; viewports stay black in both themes.
- The Design reference tab (Help → Open design reference) shows all tokens, type, badges and icons.

## Prototype defaults (P0.5 → P2)

- Settings → "Simulate a second reviewer" is on by default in the mock build: a fake reviewer posts a decision every 45 s so live-sync toasts (UI-10, CUR-11) can be seen. It does not exist against the real API.
- The mock API (`frontend/src/api/mock/`) is seeded from `make fixtures` via `npm run mock:seed`; the seed is committed so the prototype runs standalone.
