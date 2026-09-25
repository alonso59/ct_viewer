# UI Shell (QuPath layout × VS Code shell × GitHub Dark)

Scope: workbench layout, QuPath-style panes, toolbar, panels, status bar, commands, keybindings, theme, icons.
Read when: building shell, navigation, theming, icons, or keyboard UX.
Depends: frontend/ARCHITECTURE.md, ADR-0008, ADR-0010, ADR-0023. Viewer internals: VIEWER.md.

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
| Tasks | `tools` | Run analysis / scripts | Every task (TSK-01) with availability; runs with status (incl. `waiting_for_runner` + how to start the runner), outputs; annotation runs with Activate (ANZ-04) |
| Dashboards | `graph` | — | Completed runs → dashboard tab (views + Analysis panel, DB-08) |
| Search | `search` | — | Advanced filters on any visible variable, phase, status, warnings, VOI |
| Variables | `symbol-variable` | — | Variable catalog (VAR-*): type/level/missing %, Review badges, visibility, tags, derived variables, external table import |
| Labeling | `table` | — | Label tables of the project with fill progress (LBL-08); opens the table tab |
| Plugin Library | `extensions` | Extensions | Every installed plugin with status and **Open** (UI-22, PLG-05) |
| Settings *(bottom)* | `settings-gear` | Preferences | Theme, reviewer name, keybindings |

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| UI-01 | Shell regions as drawn: title bar, tool bar, activity bar, left pane, editor area, panel, status bar, optional inspector. | M |
| UI-02 | Features register views, editor types, tools, inspector sections, panel tabs, commands and status items in a registry, and the shell renders them. | M |
| UI-03 | Editor tabs: case, radiomics settings, run dashboard, correction queue, welcome, labeling table, project settings. Tabs support preview mode (italic until pinned), drag, split and close-others. | M |
| UI-04 | Workspace home (`/`) looks like the QuPath/VS Code welcome: New Project (name + optional default modality, PRJ-14), Open file or folder…, Convert DICOM… (UI-25), Open Recent (with thumbnail and progress), and a share-link copy button. | M |
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
| UI-17 | Three entry levels, no more: **Open** (a file or folder → viewer, no project, SRC-09), **Project** (a study), **Tasks** (act on a selection). Welcome and the palette offer "Open file or folder…" next to "New project". Open mode has exactly three actions: Save as NIfTI… (SRC-14), Add to project… (SRC-15), Create project from this. Open-mode layout: a title row (logo = home, "Open", path, "No project" badge) and, above the viewer, one **left-aligned** action row in workflow order: **Create project from this** (primary) · Add to project… · Save as NIfTI… │ Attach segmentation… │ the modality selector (only when assumed, VW-05). Nothing is pushed to the far right, so the actions stay in reach on wide (1440p+) screens. | M |
| UI-18 | Every error shows its cause (`detail`) and its next actions (`actions[]`) as buttons (SRC-11); a bare "Validation failed" is a bug. | M |
| UI-19 | Requirements are asked when a task needs them, not at import: a task's settings tab shows the preflight (TSK-04) with counts and one-click suggested tasks; a task that writes volumes asks for the `DERIVED` folder on first use (PRJ-13). | M |
| UI-20 | Every task uses the same tab: Selection · Settings (schema form) · Preflight/Estimate · Run; outputs appear as a segmentation set, a features run, an import or annotations. | M |
| UI-22 | Plugin Library view: one card per plugin (icon, name, version, what it adds, status + reason, **Open**); `pending` plugins are listed but cannot be opened (PLG-05/06/09). | M |
| UI-23 | Project settings tab: General · Display · Labels · Data · Plugins (PRJ-18); edits use `If-Match` and a 412 shows "changed by someone else — reload and reapply" (PRJ-15). | M |
| UI-24 | **Close**: File › Close project (and the palette) releases loaded volumes (VW-14) and returns to the workspace home without deleting anything; in Open mode a Close button, last in the action row, drops the session (`DELETE /open/{sid}`, API-07), releases the volumes and returns home. Other users are never affected. | M |
| UI-25 | Converter overlay window (ADR-0021): a modal work window with the steps source → settings → dry run → run with progress → result (Open · Create project · Add to project), reachable from Welcome, Open mode on DICOM, the Library and a project's Data tab. | M |
| UI-26 | View-only mode (`/v/{token}`, PRJ-17): the shell shows a "View only" badge, hides every editing control, command and shortcut, and keeps all viewer tools. | M |
| UI-21 | The app logo (§Brand) appears only as identity, never as decoration: browser tab icon, title-bar project switcher, workspace home header, Open-mode home button. | S |

Implementation (P7c Wave 4, UI-24): File › Close project (palette "Close project") goes to the workspace home with a page change, which releases every loaded volume; Open mode's Close (last in the action row) calls `DELETE /open/{sid}` and returns home. Open mode shows the CT tool bar under its action row (VW-22).

Implementation (P7c Wave 3): the converter overlay is the `dicom` plugin's `overlays` contribution (the shell renders overlays on every route; `plugins/dicom/ConverterOverlay.tsx` loads on first open). Entry points: Welcome "Convert DICOM…", Open mode "Convert DICOM…" (only when the session has DICOM items; starts on Settings with the path), the Library's Open and the Project › Convert DICOM command (also the Data tab), which inside a project offers "Into {project}" or "As a dataset". Settings = dataset name, organ focus, phase analyzer (on), anonymize; the dry run shows series found / to convert / skipped / size. Result for a dataset: Open · Create project from this (the import wizard on the dataset) · Add to project (pick a project; the wizard with `add`). The Data tab lists the active layers and downloads the dataset table (CSV / Parquet).

Implementation (P7c Wave 2): New project asks for a name and the default modality (CT · MR · Mixed). The settings tab (`/p/{pid}/settings`, Project › Project settings, Welcome) saves only the changed fields with the ETag of the version the form was loaded from; a 412 shows "Reload and reapply" (the same changes on the fresh version) and "Discard my changes". Labels import `.ctbl` / ITK-SNAP / `dataset.json` in the browser (`settings/labelFiles.ts`) and merge by value. View-only (`/v/{token}` redirects to `/p/view-{token}`): contributions flagged `writes` are hidden (views Curation, Tasks, Radiomics, Dashboards, Variables, Labels, Plugin Library; the curation inspector section; editors task, radiomics, run, queue, settings; every data-changing command and shortcut); Project, Search, Image, History, the viewer tools and the panels stay.

Implementation (P7b Wave 3): the Tasks view (activity bar) lists every task by kind with runner status and the recent runs; a task tab (`/p/{pid}/tasks/{task_id}`) has Selection (all active / current Explorer filter / item list; a segmentation set when the task reads masks; a folder or file for source tasks), Settings (the schema form), Preflight (counts, reasons, suggested tasks, the derived-folder prompt of UI-19), Estimate, Run, and the task's runs with their outputs (annotation runs can be activated per field). The Image view shows DICOM tags on demand. Open mode has Save as NIfTI… and Add to project…; the import wizard runs `dicom.convert` for DICOM sources.

Implementation (P7b Wave 2): "Open file or folder…" is on the workspace home and in the palette (File menu) and leads to `/open?path=`. `lib/ProblemCard` shows `detail` and `actions[]` as buttons where the screen has a handler (labels `problemAction.*`; e.g. `configure:…` stays a hint). The import wizard's detect step lists the API-19 candidates, preselects the best available one, and shows the `nifti-files` options next to it; a NIfTI file can be picked in the folder browser (SRC-05).

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
| `M` / `W` / `C` / `Z` | Tools: move/pan, window-level, crosshair, zoom* | `R` | Reset all views* (VW-10) |
| `F` | Fit the view under the pointer* (VW-26) | | |

\* Only active while the viewer has focus. Curation keys target the active item and the default target `seg`.

## Brand (UI-21)

| Rule | Detail |
|---|---|
| Master | `docs/brand/logo-master.png` (1254 px, transparent); derivatives in `frontend/public/brand/` (`logo-32/64/128/180.png`), generated from the master with `sips -z` |
| Placements | Favicon 32/64 + Apple touch icon 180 (`index.html`); title bar 18 px next to the project name; home header 48 px next to the app name; Open-mode home button 18 px. Nowhere else (no viewer, dialogs, loaders or watermarks) |
| Use | `theme/BrandMark` (`<img>`, 1×/2× source by size); decorative, so `alt=""` next to the visible app or project name |
| Integrity | Shown as is: no recolouring, filters, shadows, cropping, rotation or stretching; square aspect kept |
| Minimum size | 16 px; below 24 px the detail is lost, so use it only with the text name beside it |
| Clear space | At least `--sp-2` around it; never overlapping other content |
| Themes | The same artwork on GitHub Dark and Light (transparent background); no light/dark variants |
| Later | Electron (P8) app icons are derived from the master |

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

- **Typography:** `-apple-system, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif`. Sizes are 13 px UI, 12 px panels, 11 px badges; `ui-monospace` for numbers, except the viewer's slice index (VW-03, ADR-0023).
- **Shape:** 6 px radius on buttons, inputs and cards; 1 px borders; no shadows except overlays.
- **Badges:** Primer "Label" pills (outline in the status color, 11 px), used for phase chips and QC status.
- **Icons:** codicons (VS Code) plus the custom CT set (UI-15). Octicons are not mixed in.
- Viewport accent colors (per-plane borders and crosshairs) are owned by VW-04.
- GitHub Light values and the categorical palette (`--cat-1..8`, DB-07) are in `theme/tokens.css`; viewports stay black in both themes.
- The Design reference tab (Help → Open design reference) shows all tokens, type, badges and icons.
- **Identity signals decoupled from literal VS Code/GitHub chrome (ADR-0023), structure and density unchanged:** section/sidebar/panel-tab labels are sentence case, no `letter-spacing`, no `text-transform: uppercase` (was tracked uppercase, identical to VS Code's "EXPLORER"/"OUTLINE"); a pressed `.icon-btn[aria-pressed='true']` uses a darker flat "pressed" texture, not `--bg-selected` + a `--focus` inset outline (was identical to the search bar's "Match Case" toggle); `--focus`/`--accent` blue stays reserved for live interaction, never a resting toggle state. Viewport panel borders and plane colors follow VW-04.

## Prototype defaults (P0.5 → P2)

- Settings → "Simulate a second reviewer" is on by default in the mock build: a fake reviewer posts a decision every 45 s so live-sync toasts (UI-10, CUR-11) can be seen. It does not exist against the real API.
- The mock API (`frontend/src/api/mock/`) is seeded from `make fixtures` via `npm run mock:seed`; the seed is committed so the prototype runs standalone.

## Implementation notes (P2)

- Project view has a "Columns and colour" menu: extra columns and a colour stripe + legend from any visible case-level variable (VAR-10). The share link is the current deep link.
- Project and Search views show a clearable "N items" chip while an item-id filter is active (set by the dashboard's "Send to Explorer", DB-04).
- Bundles (PRJ-08/09): "Export bundle" on each home project card, on Welcome and in the palette (`project.exportBundle`); "Import project bundle…" on the home opens a report dialog (id change, per-alias resolve) with Relink when needed. "Compute full hashes" / "Recompute all" (IMP-09) on Welcome and in the palette; progress in the Jobs panel.
- Mock-only defaults ("Simulate a second reviewer", demo projects) exist only with `VITE_API_MODE=mock`; Settings hides them otherwise.

- Radiomics settings tab: left nav (Selection + schema groups with error badges), the form, and a side panel (validation list, summary, estimate, Run). The Radiomics view lists runs (progress, cancel, resume, failures, exports) and profiles.
