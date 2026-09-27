# UI Shell (QuPath layout × VS Code shell × GitHub Dark)

Scope: workbench layout, QuPath-style panes, toolbar, panels, status bar, commands, keybindings, theme, icons.
Read when: building shell, navigation, theming, icons, or keyboard UX.
Depends: frontend/ARCHITECTURE.md, ADR-0008, ADR-0010, ADR-0023, ADR-0028. Viewer internals: VIEWER.md.

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
│ ◧ Dataset820 ▾   File Edit View Go Tasks Help            [⌕ Go to case… ⌘P]    │ title bar
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
An optional right **Inspector** (curation form, labels of the case / scan (LBL-03), layers, W/L) toggles with `Ctrl/Cmd+Alt+B`; it is closed by default to keep the QuPath feel.

## Left pane views (activity bar)

| View | Codicon | QuPath analog | Content |
|---|---|---|---|
| Project | `files` | Project tab | Case list with **axial thumbnails** (IMP-12), status and warning badges; expands to phase → scan → items |
| Image | `info` | Image tab | Properties of the active item: geometry, spacing, dtype, phase (canonical/raw/source), paths (advanced) |
| Curation | `checklist` | Annotations | Decisions for the active case/item, a quick status bar, the correction queue |
| Labels | `tag` | Classes list | Project label map: swatch, visibility, opacity, hotkey; a name or colour saves on blur / Enter / picker close, 412 → reload + reapply (PRJ-15) |
| History | `history` | Workflow | Curation event log for the case (CUR-14) |
| Radiomics | `beaker` | — | Profiles, runs, "New run" |
| Tasks | `run-all` | Run analysis / scripts | Every task (TSK-01) with availability; runs with status (incl. `waiting_for_runner` + how to start the runner), outputs; annotation runs with Activate (ANZ-04) |
| Dashboards | `graph` | — | Completed runs → dashboard tab (views + Analysis panel, DB-08) |
| Search | `search` | — | Advanced filters on any visible variable, phase, status, warnings, VOI |
| Variables | `symbol-variable` | — | Variable catalog (VAR-*): type/level/missing %, Review badges, visibility, tags, derived variables, external table import |
| Labeling | `table` | — | Label tables of the project with fill progress (LBL-08); opens the table tab |
| Plugin Library | `extensions` | Extensions | Every installed plugin with status and **Open** (UI-22, PLG-05) |
| Settings *(bottom)* | `settings-gear` | Preferences | Theme, interface size (UI-27), reviewer name, project list rows, keybindings |

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| UI-01 | Shell regions as drawn: title bar, tool bar, activity bar, left pane, editor area, panel, status bar, optional inspector. | M |
| UI-02 | Features register views, editor types, tools, inspector sections, panel tabs, commands and status items in a registry, and the shell renders them. | M |
| UI-03 | Editor tabs: case, radiomics settings, run dashboard, correction queue, welcome, labeling table, project settings. Tabs support preview mode (italic until pinned), drag, split and close-others. | M |
| UI-04 | Workspace home (`/`) looks like the QuPath/VS Code welcome: New Project (name + optional default modality, PRJ-14), Open file or folder…, Convert DICOM… (UI-25), Open Recent (with thumbnail and progress) followed by the converted workspace datasets (name, series, Open · Create project; AUD-A2-14), and a share-link copy button. | M |
| UI-05 | Command palette `Ctrl/Cmd+Shift+P` on every route (workspace home, Open mode, project) shows the commands of that route, word and prefix matches first; quick open `Ctrl/Cmd+P` jumps to a case or item (on the home and in Open mode: to a project). The title-bar search box opens quick open. Neither opens over a modal, and Escape closes the topmost overlay. | M |
| UI-06 | Tool bar (QuPath style) holds viewer tools and toggles, shown only while the active editor is a viewer (a case tab, Open mode); other editors leave it empty (AUD-A3-20). The active tool is marked with `--bg-pressed` (≥ 3:1 against the bars, no blue; AUD-A3-02); each button has a tooltip with its shortcut. | M |
| UI-07 | Status bar shows project, live/offline SSE state, job progress, cursor ijk/RAS/HU, W/L, reviewer (click to change). | M |
| UI-08 | Project list: compact rows (`--h-row-compact`, 22 px at Compact size) or rows with thumbnail (`--h-row-thumb`, 56 px at Compact; default), virtualized, navigable with the keyboard; the badge follows the curation rollup (CUR-08). An item is named `case · phase · scope · side` (scan number when the phase is not loaded); the raw `item_id` is only in the tooltip and in copy actions (AUD-A1-13). | M |
| UI-09 | The Problems panel lists QC warnings (IMP-08) grouped by case; clicking one opens the item. | M |
| UI-10 | Notifications are toasts at bottom-right, e.g. "case_00042 updated by Dr. AP". | S |
| UI-11 | Dark (Primer's GitHub Dark values) is the default theme and Light (GitHub Light values) the alternative; Settings names them **Dark · Light · System** (AUD-A3-23). All colors come from tokens (`theme/tokens.css`; a unit test rejects raw colours elsewhere, AUD-A3-17). The Settings choice (`dark`, `light`, `system`) decides; `dark` applies until the user picks another, whatever the OS preference. | M |
| UI-12 | Keybindings (below) are overridable in Settings and stored in `localStorage`. | S |
| UI-13 | Layout state (pane sizes, visibility, open tabs) persists per project. The side bar, panel and inspector toggle from one title-bar **Layout** menu (ADR-0028). The panel's default height is min(220 px, 20 % of the window); on a case tab it stays closed until a panel tab has content for the item (a feature row, a problem), unless the user chose (AUD-A3-01). | S |
| UI-14 | Measurements panel: features of the active item from the selected run (API-36 `item_id` filter), with a robust z-score column; outliers are marked. | S |
| UI-15 | CT-specific icons (axial/sagittal/coronal plane, W/L, crosshair, layout grid, outline, VOI L/R) are a custom SVG set drawn to codicon rules: 16 px grid, `currentColor`, same stroke weight. Set (`theme/icons/CtIcon.tsx`): plane-axial/sagittal/coronal, view-3d, window-level, crosshair (tool), crosshair-lines (show/hide crosshair), layout-four-up/conventional/three-mpr/one-up, label-overlay, label-outline, voi-left/right, slice-stack. | M |
| UI-16 | Motion is limited to ≤150 ms fades/slides and respects `prefers-reduced-motion` (durations 0, spinners stop; AUD-A3-18). | S |
| UI-17 | Three entry levels, no more: **Open** (a file or folder → viewer, no project, SRC-09), **Project** (a study), **Tasks** (act on a selection). Welcome and the palette offer "Open file or folder…" next to "New project". Open mode has exactly three actions: Save as NIfTI… (SRC-14), Add to project… (SRC-15), Create project from this. Open-mode layout: a title row (logo = home, "Open", path, "No project" badge) and, above the viewer, one **left-aligned** action row in workflow order: **Create project from this** (primary) · Add to project… · Save as NIfTI… │ Attach segmentation… │ the modality selector (only when assumed, VW-05). Nothing is pushed to the far right, so the actions stay in reach on wide (1440p+) screens. | M |
| UI-18 | Every error shows its cause (`detail`) and its next actions (`actions[]`) as buttons (SRC-11); a bare "Validation failed" is a bug. The title is the problem in plain words (`problemTitle.{slug}` for API problems), never a raw exception or a slug chip, and never a server setting name. | M |
| UI-19 | Requirements are asked when a task needs them, not at import: a task's settings tab shows the preflight (TSK-04) with counts and one-click suggested tasks; a task that writes volumes asks for the `DERIVED` folder on first use (PRJ-13). | M |
| UI-20 | Every task uses the same tab: Selection · Settings (schema form) · Preflight/Estimate · Run; outputs appear as a segmentation set, a features run, an import or annotations. | M |
| UI-22 | Plugin Library view: one card per plugin (icon, name, version, what it adds, status + reason, **Open**); `pending` plugins are listed but cannot be opened (PLG-05/06/09). | M |
| UI-23 | Project settings tab: General · Display · Labels · Data · Plugins (PRJ-18); edits use `If-Match` and a 412 shows "changed by someone else — reload and reapply" (PRJ-15). | M |
| UI-24 | **Close**: File › Close project (and the palette) releases loaded volumes (VW-14) and returns to the workspace home without deleting anything; in Open mode a Close button, last in the action row, drops the session (`DELETE /open/{sid}`, API-07), releases the volumes and returns home. Other users are never affected. | M |
| UI-25 | Converter overlay window (ADR-0021): a modal work window with the steps source → settings (a taken dataset name is said there) → dry run (every series with its plan, skip reason and size, DCM-06) → run with progress → result (Open · Create project · Add to project), reachable from Welcome, Open mode on DICOM, the Library and a project's Data tab. | M |
| UI-26 | View-only mode (`/v/{token}`, PRJ-17): the shell shows a "View only" badge, hides every editing control, command and shortcut, and keeps all viewer tools. | M |
| UI-21 | The app logo (§Brand) appears only as identity, never as decoration: browser tab icon, title-bar project switcher, workspace home header, Open-mode home button. | S |
| UI-27 | Settings › **Interface size**: Compact · Default · Large (per browser). Every font size, control and row height is a token that the size sets (`<html data-size>`); Compact is the P7 scale (13 px UI), Default 14 px, Large 16 px (AUD-A3-16). | S |

Implementation (P7c Wave 4, UI-24): File › Close project (palette "Close project") goes to the workspace home with a page change, which releases every loaded volume; Open mode's Close (last in the action row) calls `DELETE /open/{sid}` and returns home. Open mode shows the CT tool bar under its action row (VW-22).

Implementation (P7c Wave 3): the converter overlay is the `dicom` plugin's `overlays` contribution (the shell renders overlays on every route; `plugins/dicom/ConverterOverlay.tsx` loads on first open). Entry points: Welcome "Convert DICOM…", Open mode "Convert DICOM…" (only when the session has DICOM items; starts on Settings with the path), the Library's Open and the Project › Convert DICOM command (also the Data tab), which inside a project offers "Into {project}" or "As a dataset". Settings = dataset name, organ focus, phase analyzer (on), anonymize; the dry run shows series found / to convert / skipped / size. Result for a dataset: Open · Create project from this (the import wizard on the dataset) · Add to project (pick a project; the wizard with `add`). The Data tab lists the active layers and downloads the dataset table (CSV / Parquet).

Implementation (P7c Wave 2): New project asks for a name and the default modality (CT · MR · Mixed). The settings tab (`/p/{pid}/settings`, Project › Project settings, Welcome) saves only the changed fields with the ETag of the version the form was loaded from; a 412 shows "Reload and reapply" (the same changes on the fresh version) and "Discard my changes". Labels import `.ctbl` / ITK-SNAP / `dataset.json` in the browser (`settings/labelFiles.ts`) and merge by value. View-only (`/v/{token}` redirects to `/p/view-{token}`): contributions flagged `writes` are hidden (views Curation, Tasks, Radiomics, Dashboards, Variables, Labels, Plugin Library; the curation inspector section; editors task, radiomics, run, queue, settings; every data-changing command and shortcut); Project, Search, Image, History, the viewer tools and the panels stay.

Implementation (P7b Wave 3): the Tasks view (activity bar) lists every task by kind with runner status and the recent runs; a task tab (`/p/{pid}/tasks/{task_id}`) has Selection (all active / current Explorer filter / item list; a segmentation set when the task reads masks; a folder or file for source tasks), Settings (the schema form), Preflight (counts, reasons, suggested tasks, the derived-folder prompt of UI-19), Estimate, Run, and the task's runs with their outputs (annotation runs can be activated per field). The Image view shows DICOM tags on demand. Open mode has Save as NIfTI… and Add to project…; the import wizard runs `dicom.convert` for DICOM sources.

Implementation (P7b Wave 2): "Open file or folder…" is on the workspace home and in the palette (File menu) and leads to `/open/{sid}` (the path never enters the URL, SOURCES §Open mode). `lib/ProblemCard` shows `detail` and `actions[]` as buttons where the screen has a handler (labels `problemAction.*`; e.g. `configure:…` stays a hint). The import wizard's detect step lists the API-19 candidates in plain words with the reason on its own line (internal adapter names in the tooltip, AUD-A1-15), preselects the best available one, and shows the `nifti-files` options next to it; a NIfTI file can be picked in the folder browser (SRC-05). The folder browser (API-10) has a filter box for folders over 12 entries and type-to-select in the list; at a shared root there is no Parent row, only "All shared folders" when there are several (AUD-A1-16). Error cards of a case tab offer next steps: an unknown case → Go to case… · Close tab; a missing image → Relink data root… · Show in Problems (AUD-A3-03, AUD-A2-07).

## Commands, menus and navigation

| Topic | Rule |
|---|---|
| Menus (AUD-A1-09) | File · Edit · View · Go · Tasks · Help, derived from command categories (`shell/menus.ts`): File = `cat.file`, `cat.project`; Edit = curation, phase, edits; View = shell toggles, viewer, **Views ›** and **Panels ›** (every activity-bar view and panel tab); Go = next / previous / next unreviewed case, next problem, queue, latest dashboard; Tasks = every task (`Task: Run …`, TSK-01) incl. radiomics and DICOM; Help = Welcome, Keyboard shortcuts, design reference, About. No menu is named after a plugin; `menu: false` keeps a command palette-only |
| Scope (AUD-A1-01) | A command's `scope` (`home`, `open`, `project`; default project) decides where the palette, menus and keys offer it. Home: New project, Open file or folder, Convert DICOM, Import project bundle, Open recent project (`Ctrl/Cmd+P`), theme, Keyboard shortcuts, About. Open mode: the viewer commands too |
| Coverage (AUD-A1-06) | Every view and panel tab has `view.show.*` / `panel.show.*`, every listed task `task.run.*` (registry test); share links, phase set, fit, next segmentation set, latest dashboard, dataset exports and New label table are commands |
| Navigation context (AUD-A1-04) | A case opened from Outliers, the correction queue, Problems or a label table remembers that list: `Alt+↓/↑` follow it and the case header shows e.g. "Outliers 3/22 ›" with × (back to Explorer order). An Explorer or quick-open open drops it. "Next unreviewed" = next case in Explorer order whose CUR-08 `review_state` is not `reviewed`, wrapping |
| Explorer (AUD-A1-03) | The Project view follows the active case: cursor and scroll move to its row (its item row when the case is expanded); it does not expand cases by itself |
| Sharing (AUD-A1-11) | The title-bar share button is a menu: Copy edit link · Copy view-only link (created on first use, PRJ-17); both keep the current tab's deep link (`/v/{token}/case/…` opens that case read-only). A view-only workbench shows only its own link |
| Help (AUD-A4-05) | About: version (API-01), "Research use only · not a medical device" (NFR-16), main open-source licences; the status-bar project item's tooltip repeats the version and the notice. Keyboard shortcuts lists every bound command |
| Archive (AUD-A4-03) | File › Archive project… and the home card's archive button ask first (PRJ-06); the home's **Archived** toggle lists archived projects with Restore |

## Default keybindings

| Keys | Command | Keys | Command |
|---|---|---|---|
| `Ctrl/Cmd+Shift+P` | Command palette | `Ctrl/Cmd+P` | Quick open case (home, Open mode: open recent project) |
| `Ctrl/Cmd+B` | Toggle left pane | `Ctrl/Cmd+J` | Toggle panel |
| `Ctrl/Cmd+Alt+B` | Toggle inspector | `Alt+W` | Close tab (browsers reserve `Ctrl/Cmd+W`; Electron uses `Ctrl/Cmd+W`) |
| `Alt+↓` / `Alt+↑` | Next / previous case (navigation list, else filtered Explorer order) | `F8` | Next problem |
| `Alt+Shift+↓` | Next unreviewed case (AUD-A1-04) | `Ctrl/Cmd+\` | Split editor |
| `A` | Mark accepted* | `Shift+1` / `Shift+2` | Needs minor / major correction* |
| `X` | Rejected* | `Q` | Add to correction queue* |
| `1`–`9` | Toggle label visibility* | `L` | Cycle viewer layout* |
| `M` / `W` / `C` / `Z` | Tools: move/pan, window-level, crosshair, zoom* | `R` | Reset all views* (VW-10) |
| `F` | Fit the view under the pointer* (VW-26) | `Esc` | Restore a maximized view* |
| `Ctrl/Cmd+,` | Settings | `Ctrl/Cmd+Shift+E` / `F` | Project / Search view |

\* Only while a viewer is shown (a case tab, or Open mode) and focus is not in a text field or menu; DOM focus inside the viewer is not needed, so `A → Alt+↓ → A` records both cases (AUD-A2-02). Curation keys wait until the new case's item has loaded and target it with the default target `seg`. No shortcut fires while a dialog is open (AUD-A2-09).

## Brand (UI-21)

| Rule | Detail |
|---|---|
| Master | `docs/brand/logo-master.png` (1254 px, transparent); derivatives in `frontend/public/brand/` (`logo-32/64/128/180.png`), generated from the master with `sips -z` |
| Placements | Favicon 32/64 + Apple touch icon 180 (`index.html`); title bar 18 px next to the project name; home header 48 px next to the app name; Open-mode home button 18 px. Nowhere else (no viewer, dialogs, loaders or watermarks) |
| Use | `theme/BrandMark` (`<img>`, 1×/2× source by size); decorative, so `alt=""` next to the visible app or project name |
| Integrity | Shown as is: no recolouring, filters, shadows, cropping, rotation or stretching; square aspect kept |
| Minimum size | 16 px; below 24 px the detail is lost, so use it only with the text name beside it |
| Clear space | At least `--sp-2` around it; never overlapping other content |
| Themes | The same artwork on Dark and Light (transparent background); no light/dark variants |
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
| `--tab-active-indicator` | `var(--fg)` (ADR-0028) | `--accent` | `#2F81F7` |
| `--bg-statusbar` | `#0D1117` | `--bg-viewport` | `#000000` |
| `--ok` | `#3FB950` | `--warn` | `#D29922` |
| `--error` | `#F85149` | `--done` | `#A371F7` |
| `--btn-primary` | `#238636` | `--bg-hover` | `#1F2428` |
| `--bg-pressed` (active toggle) | `#5F6874` (Light `#818B98`) | `--bg-viewport-overlay` | `#000000A6` |

- **Typography:** `-apple-system, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif`. Sizes (UI-27, Default · Compact): UI 14 · 13 px, panels 13 · 12, badges 12 · 11, chips `--fs-chip` 13 · 11, headings 17 · 16, titles 22 · 20, home title `--fs-hero` 30 · 28; no px font size outside `tokens.css`. `ui-monospace` for numbers, except the viewer's slice index (VW-03, ADR-0023).
- **Shape:** 6 px radius on buttons, inputs and cards; 1 px borders; no shadows except overlays.
- **Badges:** Primer "Label" pills (outline in the status color, `--fs-chip`), used for phase chips and QC status; a pressed chip is `--fg` on `--bg-selected` (AUD-A3-19). Segmented controls (`.seg`, `theme/base.css`) are as wide as their options (AUD-A3-08).
- **Icons:** codicons (VS Code) plus the custom CT set (UI-15). Octicons are not mixed in.
- Viewport accent colors (per-plane borders and crosshairs) are owned by VW-04.
- Light values and the categorical palette (`--cat-1..8`, DB-07) are in `theme/tokens.css`; viewports stay black in both themes.
- The Design reference tab (Help → Open design reference) shows all tokens, type, badges and icons.
- **Identity signals decoupled from literal VS Code/GitHub chrome (ADR-0023), structure and density unchanged:** section/sidebar/panel-tab labels are sentence case, no `letter-spacing`, no `text-transform: uppercase` (was tracked uppercase, identical to VS Code's "EXPLORER"/"OUTLINE"); a pressed `.icon-btn[aria-pressed='true']` uses the flat `--bg-pressed` fill (AUD-A3-02), not `--bg-selected` + a `--focus` inset outline (was identical to the search bar's "Match Case" toggle); `--focus`/`--accent` blue stays reserved for live interaction, never a resting toggle state. Viewport panel borders and plane colors follow VW-04.

## Prototype defaults (P0.5 → P2)

- The mock API (`frontend/src/api/mock/`) replays responses recorded from the backend on the fixtures (`make record-mock`, TESTING §Mock API); the recording is committed so the prototype runs standalone. It shows one demo project and changes nothing on writes; there are no server events (the simulated second reviewer is gone, FB8).

## Implementation notes (P2)

- Project view has a "Columns and colour" menu: extra columns and a colour stripe + legend from any visible case-level variable (VAR-10). The share link is the current deep link.
- Project and Search views show a clearable "N items" chip while an item-id filter is active (set by the dashboard's "Send to Explorer", DB-04).
- Bundles (PRJ-08/09): "Export bundle" on each home project card, on Welcome and in the palette (`project.exportBundle`); "Import project bundle…" on the home opens a report dialog (id change, per-alias resolve) with Relink when needed. "Compute full hashes" / "Recompute all" (IMP-09) on Welcome and in the palette; progress in the Jobs panel.
- Mock-only settings (Settings › Prototype: reset the prototype's tabs and layout) exist only with `VITE_API_MODE=mock`; Settings hides them otherwise.

- Radiomics settings tab: left nav (Selection + schema groups with error badges), the form, and a side panel (validation list, summary, estimate, Run). The Radiomics view lists runs (progress, cancel, resume, failures, exports) and profiles.

## Implementation notes (FB5, FB6)

- **Numbers (AUD-A3-04, owner 2026-09-25):** English format everywhere (`lib/format.ts`): a point as the decimal separator; counts keep the English thousands separator, measured values never get one. Number fields are `NumberInput` (`lib/ui.tsx`): a text field with `inputmode="decimal"` and spin-button semantics that accepts `,` or `.`; ↑/↓ step. Feature values (`fmtValue` / `fmtColumn`): 3 significant digits (whole numbers keep their integer digits), scientific above 1e5 or below 1e-3, for a whole column once one cell needs it; tabular figures; the unit from the feature class (`featureUnit`: shape → mm/mm²/mm³, original first-order intensities → HU on CT) (AUD-A3-15).
- **Run and job states (UI-15, TSK-06; AUD-A3-10):** one sentence-case vocabulary (`runStatus.*`, `RunStatusBadge` in `lib/badges.tsx`) in the Tasks, Radiomics, Dashboard and Jobs views; a job's `succeeded` reads "Completed".
- **Truncation (UI-08, AUD-A3-13):** `.truncate` (one line, ellipsis) always carries the full value in `title`; paths use a middle ellipsis (`midEllipsis`).
- **Panel per editor type (UI-13, AUD-A1-18):** the bottom panel's visibility is remembered per editor type; it starts closed on full-height editors (radiomics settings, dashboards, tasks, project settings) and open elsewhere.
- **Form editors (UI-20, AUD-A3-06):** content at most `--form-max-width` (1200 px), centred; the radiomics settings side panel moves under the form when the editor is narrower than 1040 px (about a 1366 px window with the side bar), and segmented controls wrap.
- **Two-line list rows (AUD-A3-21):** `.list-row-2` (title, meta lines, labelled trailing actions) for the Dashboards and Radiomics views; empty states use `.empty`.
- **One icon per meaning (UI-15, AUD-A3-11/12):** a missing thumbnail is a muted `slice-stack` on `--bg-inset` with a tooltip (real slices stay on black); "No segmentation" `label-outline`; analyzer tasks `symbol-property`; each radiomics settings group its own codicon; `circle-slash` only means Rejected.
- **Task outputs (TSK-09, AUD-A3-09):** a run's outputs are named links (segmentation set → shown in the viewer, features → its dashboard, import → Explorer); API paths and ids only in the tooltip. User-facing strings never cite requirement or ADR IDs (`i18n/keys.test.ts`, AUD-A1-14).
