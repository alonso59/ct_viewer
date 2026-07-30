# README - UX/UI Architecture

## ccRCC CT Dataset Curation WebUI

**Document purpose:** define the user experience and interface layout architecture for the medical curation workflow.
**Audience:** product owner, medical curators, research scientists, frontend/backend developers, and QA reviewers.
**Scope:** visual architecture, interaction model, navigation, layout rules, component roles, and UX acceptance criteria.
**Non-scope:** backend API specification, segmentation editing, PACS functionality, 3D Slicer replacement features, radiomics dashboards, implementation code, or deployment packaging.

---

## 1. Product North Star

The product is a focused two-screen medical curation tool for ccRCC CT datasets.

The medical researcher or medical doctor should be able to answer, without understanding internal folders or file paths:

1. Which dataset is loaded?
2. Which case am I reviewing?
3. Which scan, phase, scope, and side are active?
4. Am I comparing complete CT or VOI data?
5. Are kidney, tumor, or cyst overlays visible?
6. Are there missing files or active warnings?
7. Is the segmentation/VOI acceptable for this case?
8. Should this case be accepted, rejected, marked cannot assess, or sent to correction?
9. Can I save and move to the next case confidently?

The interface should feel like a purpose-built medical review cockpit, not a developer dashboard, data spreadsheet, PACS clone, or 3D Slicer clone.

---

## 2. Product Context

### 2.1 Primary user

The primary user is a medical researcher or medical doctor acting as a data curator.

Expected usage:

* individual review mode;
* 5-10 cases per session;
* primary input by mouse;
* minimal training;
* self-explanatory controls and visible status labels.

### 2.2 Supported hardware

Target displays:

* minimum supported resolution: `1280x720`;
* target review resolution: `1440x1000`;
* maximum expected resolution: `2560x1440`;
* common hardware: 27-inch monitor or 14-inch laptop.

At `1440x1000`, the Main Review Screen must show the left module panel, fixed 2×2 viewer workspace without page-level scrolling.

### 2.3 Primary task

The most frequent and highest-priority task is phase determination/correction and comparison between original CT and VOIs.

Routine decisions must be possible without page-level scrolling:

* phase correction;
* scan or VOI exclusion;
* case-level QC decision.

Review is case by case. The review focus is kidney and tumor, with cyst overlay available when present.

---

## 3. Core Product Boundaries

### 3.1 What this product is

* A two-screen medical curation interface.
* A case-first CT/SEG/VOI review tool.
* A phase and source verification interface.
* A segmentation-quality QC cockpit.
* A controlled curation-state writer.
* A correction-queue generator for external editing workflows.

### 3.2 What this product is not

* Not a PACS viewer.
* Not a DeepUnity clone.
* Not a 3D Slicer clone.
* Not a segmentation editor.
* Not a reporting system.
* Not a radiomics dashboard.
* Not a model-training dashboard.
* Not a file manager.
* Not a spreadsheet browser.

### 3.3 Source-data safety rule

The UI may expose explicit curation decisions and controlled review operations, but it must never make source-data changes silently.

Allowed routine curation concepts:

* case-level segmentation QC status;
* phase correction with confirmation;
* scan or VOI exclusion decision;
* curation comment;
* correction queue state;
* reviewer and timestamp metadata;
* warning visibility.

Not part of routine medical review:

* voxel editing;
* segmentation painting;
* raw file-path navigation;
* uncontrolled moving or renaming of files;
* silent mutation of `database.csv`, `manifest.csv`, NIfTI, SEG, or VOI data.

---

## 4. UX Principles

### 4.1 Case-first, not file-first

The doctor selects and reviews a case, not a path.

The system maps underlying dataset records to human review concepts:

* case;
* scan;
* phase;
* scope;
* side;
* complete CT;
* VOI;
* segmentation;
* warning;
* QC decision.

Raw paths may exist in advanced metadata, but they should never drive routine review.

### 4.2 Image-centered

The viewer is the dominant visual surface. The layout must prioritize CT images and overlays over metadata and forms.

At target desktop size, the doctor should see:

* current case identity;
* active scan/source status;
* fixed 2×2 viewer;
* left navigation and source controls;
* right QC decision panel;
* active warnings.

### 4.3 Stable routine workflow

The review flow is always:

```text
Dataset Load Screen -> Main Review Screen -> Save & Next -> next case
```

Routine review actions stay in the Main Review Screen. The user should not need to navigate to a separate selection page or metadata page to complete ordinary curation.

### 4.4 Progressive disclosure

Primary controls are always visible. Secondary information is available through collapsible sections, the bottom drawer, or the Case Data modal.

Always visible:

* active case identity;
* persistent case navigator in the left panel footer;
* active scan/source (Sources module);
* viewer overlay popover for overlay settings, opacity, and W/L presets;
* viewer grid;
* module selector (switches between Review / Sources / QC / Case Data / Warnings / History);
* warning badge count.

Secondary (accessible via left panel module selector):

* inventory detail (Sources module);
* warning detail (Warnings module);
* QC history (History module);
* Save & Next action (QC module);
* raw metadata (Case Data modal);
* technical paths (Case Data modal, hidden by default).

### 4.5 Predictable action placement

Routine curation decisions are performed in the **QC module** of the left panel.

The doctor should not search for where to accept, reject, mark cannot assess, queue correction, comment, or save and move next.

---

## 5. Information Architecture

The application has two primary user-facing screens:

1. **Dataset Load Screen** - choose and validate the dataset.
2. **Main Review Screen** - review cases, compare sources, inspect overlays, handle warnings, record QC, and move case by case.

```text
Dataset Load Screen -> Main Review Screen
                         ├── compact top header bar
                         ├── left module panel (module selector + module content)
                         │     ├── Review   — source summary, warnings count, QC shortcut
                         │     ├── Sources  — phase-filtered source cards + collapsible inventory detail
                         │     ├── QC       — QC status buttons, comment, Save & Next
                         │     ├── Case Data — case info chips + Open Case Data modal button
                         │     ├── Warnings — warning detail
                         │     └── History  — curation decision history
                         ├── fixed 2×2 viewer workspace (fills all remaining space)
                         └── Case Data modal (overlay, not a route)
```

The `/cases` page is not a primary product surface in v1. If a route or implementation artifact exists for cases, it should not be the main user-facing review workflow.

The Main Review Screen contains a persistent case navigator in the left panel footer and all routine review actions.

---

## 6. Dataset Load Screen

### 6.1 Purpose

The Dataset Load Screen answers:

* Which dataset is active?
* Is the dataset ready for review?
* How many cases exist?
* Can I start or resume review?
* Are there dataset-level warnings before review begins?
* Did I select a backend/server path that the application can actually read?

### 6.2 Primary content

The active dataset readiness card should be visually dominant.

Recommended visible fields:

* dataset name;
* dataset availability status;
* case count;
* reviewed count if available;
* cases with warnings;
* SEG availability;
* VOI availability;
* Start Review action;
* Resume Review action.

### 6.3 Secondary content

Dataset discovery, path setup, and validation details should remain available, but visually secondary.

The path field is a configuration control, not the main review workflow.

### 6.4 Dataset Discovery Workflow

The setup screen supports two safe selection modes:

* browse a backend-accessible dataset folder;
* browse a backend-accessible `database.csv` file.

When `database.csv` is selected directly, the backend infers the dataset root from the parent folder, a shallow sample of path columns, or configured roots such as `/data`. The active workspace stores the inferred dataset root and the selected `database.csv` path so the Main Review Screen uses the same validated database file.

The backend file browser is not a general file manager. It shows only configured roots and only one directory level per request. Allowed roots are `DATASET_DIR` when available, entries from `DATASET_ROOTS`, `DATA_ROOT`, and `/data` when mounted. The browser must never navigate outside those roots.

Manual path entry remains available for advanced users and is labeled: `Backend/server path, not local browser path`.

When `/data` is available, the UI states that host `DATASET_DIR` is mounted inside the app as `/data`. This reduces confusion when Docker Compose maps a host path such as `/Volumes/INTENSO/dataset` into the container as `/data`.

### 6.5 Lightweight Validation Modal

On folder or `database.csv` selection, the UI opens a validation progress modal with these visible steps:

* Checking path;
* Finding `database.csv`;
* Reading CSV;
* Checking columns;
* Sampling files;
* Building summary.

Validation is intentionally shallow. It may parse `database.csv`, count rows/cases, inspect required columns, and sample referenced CT/SEG/VOI paths. It must not load all NIfTI volumes, recursively crawl dataset folders, freeze the UI, mutate CT/VOI/SEG/mask files, or edit `database.csv`.

Completion behavior:

* progress reaches 100%;
* the bar is green when there are no blocking errors;
* the modal shows Success / Warnings / Errors counts with clear color treatment;
* OK is available after completion;
* blocking errors prevent activation;
* warnings allow activation by default.

---

## 7. Main Review Screen

### 7.1 Purpose

The Main Review Screen is the routine medical curation screen. It is optimized for image review, phase/source correction, CT-to-VOI comparison, warnings, and case-level QC.

It must allow the doctor to:

* select the current case from an always-visible case navigator;
* inspect scan `0` complete CT by default when opening a case;
* switch scan, phase, scope, and side from the left panel;
* compare CT and VOI inside the 2×2 layout;
* show or hide kidney, tumor, and cyst overlays;
* review warning badges;
* open Case Data when more context is needed;
* save a case-level QC decision;
* move to the next case.

Segmentation QC is one decision per case, not per individual label, scan, or overlay.

### 7.2 Required desktop layout

At `1440x1000`, the Main Review Screen uses a two-zone layout inspired by 3D Slicer spatial proportions:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Top header (compact, ≤44px): dataset | case_id | patient_id | source | QC   │
│                               warnings | [queued] | [loading] | Help        │
├───────────────────────────────────────┬──────────────────────────────────────┤
│ Left Module Panel (380–440px)         │ Viewer Workspace (fills remainder)   │
│                                       │                                      │
│ [Module: Review ▼]                    │ ┌──────────────┬──────────────┐      │
│                                       │ │ AXI          │ COR          │      │
│ ── module content (scrollable) ──     │ ├──────────────┼──────────────┤      │
│                                       │ │ SAG          │ 3D slot      │      │
│ Review:  case list, source summary    │ └──────────────┴──────────────┘      │
│ Sources: inventory cards, controls    │                                      │
│ Overlay: viewer popover, HUD          │ (2×2 uses all remaining height)      │
│ QC:      status, comment, Save & Next │                                      │
│ Case Data: modal button               │                                      │
│ Warnings: warning detail              │                                      │
│ History: decision log                 │                                      │
│                                       │                                      │
│ ── sticky footer ──                   │                                      │
│ [Case selector] [Previous] [Next]     │                                      │
└───────────────────────────────────────┴──────────────────────────────────────┘
```

Rules:

* the left module panel is persistent and never collapsed in v1;
* target width at `1440px`: 380–440px; minimum: 340px; maximum: 480px;
* no fixed right QC panel — QC is the QC module in the left panel;
* no bottom drawer visible by default — Inventory / Warnings / History are left panel modules;
* the 2×2 viewer uses all remaining viewport space after the top header and left panel;
* the 2×2 grid is rectangular (not forced to 1:1 square) to fill available space;
* pane containers are separated by 1 px near-invisible dividers; there are no card borders, drop shadows, or rounded corners on panes — the viewer looks like one integrated dark workspace;
* complete CT images preserve physical aspect ratio inside each pane using contain-fit behavior;
* VOI images use viewer-effective isotropic spacing by default;
* viewer, case identity, module selector, and case navigation are never hidden;
* active warnings appear as count badges in the top header and the Review module;
* no page-level scroll during routine review at `1440x1000` or `1280x720`;
* no vertical tabs;
* no PACS complexity;
* layout inspiration: 3D Slicer spatial proportion model (left module panel + large unified image workspace); no 3D Slicer assets, branding, or visual implementation are copied.

---

## 8. Left Module Panel

### 8.1 Role

The left module panel is the primary non-image control area. It replaces the previous three-zone layout (case rail + left panel + right QC panel + bottom drawer) with one persistent, wider, internally scrollable panel containing all non-image functionality organized by module.

Target width at `1440px`: `380–440px` (implemented as `clamp(340px, 27vw, 480px)`).
Minimum width: `340px`. Maximum width: `480px`.

The left module panel is never collapsed in v1.

### 8.2 Module selector

At the top of the scrollable content area, a dropdown control selects the active module:

| Module | Purpose |
| --- | --- |
| Review | Routine case review: active source summary, warning count, quick QC access |
| Sources | Direct source selection: phase filters plus scan-grouped CT / VOI L / VOI R cards |
| QC | Case-level QC decision: status buttons, comment, Save & Next, Save only |
| Case Data | Open Case Data modal, case/patient summary chips, phase correction action |
| Warnings | Warning detail for all sources in current case |
| History | Prior curation decisions, reviewer, timestamp, status |

The most common flow is: select case in **Review** → review source in **Sources** → adjust overlays from the viewer popover when needed → record decision in **QC**.

### 8.3 QC module placement

QC is now a left panel module, not a fixed right panel. The **QC module** must be easily reachable from the module selector and must not require scrolling through other modules.

**Save & Next** is the primary action. It is accessible from the QC module and from the Review module (when a QC status is already selected).

**Missing SEG** blocks QC save and shows a blocking alert inside the QC module.

### 8.4 Navigation hierarchy

The source identity model is:

```text
Case -> Phase -> Scan -> Scope -> Side
```

The doctor selects a complete available source directly. A selectable source card represents the full combination `phase + scan + scope + side`, for example `NP · scan 1 · Complete CT`, `NP · scan 1 · VOI L`, or `NP · scan 1 · VOI R`.

Rules:

* primary source selection uses phase filter chips (`NP`, `CMP`, `NC`, `EXC`) and scan-grouped cards;
* each scan group exposes source chips such as `CT`, `VOI L`, and `VOI R`;
* clicking a source chip immediately loads that exact source in the viewer;
* source chips show selected, available, missing, warning, and disabled states;
* the displayed source uses clinical copy, not API-like strings;
* detailed inventory is secondary and collapsible below the source cards;
* the left panel must avoid horizontal scrolling during routine source selection;
* warning badges appear next to affected cases or sources;
* the panel footer always shows the case selector plus Previous/Next navigation;
* warning count badge is always visible in the top header regardless of active module.

---

## 9. Viewer Grid

### 9.1 Default layout

The default layout is a fixed 2×2 grid:

* AXI in the top-left pane;
* COR in the top-right pane;
* SAG in the bottom-left pane;
* 3D slot in the bottom-right pane.

The viewer workspace is designed as a **single unified image workspace** subdivided into four panes by thin, near-invisible 1 px separators — not as four isolated cards. This is inspired by the spatial model of 3D Slicer: one large dark canvas, minimal chrome per pane, maximum image area.

Each pane has:
* a compact header strip (≈32-36 px) showing the axis label badge and a discoverable expand control — no verbose captions or padding;
* a black image area filling the remaining pane height;
* a reserved slice-slider strip below the image.

The panels do not disappear. The doctor may activate or deactivate AXI, COR, and SAG individually, but the grid remains stable. Pane positions and pane geometry must not change when switching case, scan, phase, scope, side, or VOI source.

The 3D slot is available on demand and is not dominant by default.

### 9.2 Layout controls

The viewer should include:

* per-pane expand toggle (double-click header or icon) that expands to fill the full viewer workspace;
* Reset Layout button appears only when a pane is expanded — not cluttering the default 2×2 view;
* no separate focus buttons, because the doctor interacts directly with each panel.

### 9.3 Image rules

Viewer image rules:

* always preserve complete CT physical aspect ratio when spacing is available;
* never stretch CT or VOI slices to fill the pane;
* default fit mode is fit entire slice inside panel using contain-fit behavior;
* MPR image content uses physical voxel spacing when available: axial uses X/Y spacing, coronal uses X/Z spacing, and sagittal uses Y/Z spacing;
* VOI sources use viewer-effective isotropic spacing `[1, 1, 1]` by default so cropped anatomy remains inspectable in 2D and 3D;
* complete CT and VOI sources fit independently by default so VOIs remain large enough for inspection;
* CT and VOI images must not be stretched to fill the pane; unused area remains black or neutral viewer background;
* viewer pane containers are **rectangular and fill the available 2×2 workspace** — pane containers may be wider than tall or taller than wide depending on screen geometry; do not force 1:1 square panes as that wastes space;
* the physical image content rectangle uses contain-fit inside each pane — the image itself stays proportional to voxel spacing regardless of pane shape;
* sliders have reserved fixed space at the pane bottom;
* auto-center image when changing case, scan, phase, or scope;
* zoom and pan are independent per panel;
* black (`#000`) pane background absorbs unused space when image aspect ratio leaves empty bands.
* all fitting, scaling, interpolation, zoom, and pan are viewer-only and non-persistent;
* visualization changes must not modify CT, VOI, SEG, mask files, `manifest.csv`, or `database.csv`.

### 9.4 CT and VOI comparison

In v1, comparison means CT <-> VOI comparison inside the 2×2 layout.

Future v2 comparison concepts:

* phase comparison such as NP vs CMP;
* L vs R comparison;
* synchronized crosshair between compared panels;
* dedicated compare-phases layout.

---

## 10. Overlays and Legend

### 10.1 Available overlays

Available overlays:

* kidney;
* tumor;
* cyst.

Overlay settings stay inside the viewer as a popover/dropdown anchored to an **Overlay** control. They are not moved into the left module panel.

### 10.2 Overlay controls

Each overlay supports:

* show/hide;
* opacity slider;
* filled mode;
* contour-only mode.

Default overlay mode: filled.

The viewer also shows a compact overlay status HUD near the viewer toolbar/chrome. The HUD is read-only, uses subtle dark styling, and summarizes the current overlay mode and label state without behaving like a modal.

Viewer-level controls such as Overlay, Fit, Expand, and Reset Layout must use medically usable click targets of at least 32 px, visible hover/focus states, and tooltips where the action is not self-evident. Pane expand controls must be discoverable in the pane header without covering image content.

### 10.3 Overlay colors

Use consistent color semantics:

| Overlay | Color |
| --- | --- |
| kidney | light blue |
| tumor | orange/red |
| cyst | green |

The viewer must include a compact overlay HUD in the viewer chrome area, not only tooltips.

---

## 11. QC Module (Left Panel)

### 11.1 Role

QC is a module in the left panel module selector, not a fixed right panel.

The QC decision is one decision per case, not per individual scan or label.

The QC module must be easily reachable at one click from the module selector.

### 11.2 Actions

Required QC actions:

* Accept;
* Needs correction;
* Reject;
* Cannot assess.

Primary button:

* Save & Next.

Rules:

* Needs correction automatically adds the case to the correction queue;
* no confirmation modal for normal QC save;
* comment is optional in all states;
* comment is recommended but not blocking for Needs correction;
* Missing SEG blocks QC save and shows a blocking alert inside the QC module;
* no comment templates in v1.

### 11.3 Safety-sensitive actions

The highest scientific risks are:

* wrong phase correction;
* exclusion of a valid scan or VOI.

Phase correction requires a simple one-click confirmation, for example:

```text
Change phase from NP to CMP?
```

Scan or VOI exclusion must be explicit, visible in the current case/source context, and auditable.

---

## 12. Warnings

### 12.1 Warning types

Critical warnings:

* Missing SEG;
* Missing VOI;
* Wrong phase suspected;
* Wrong side suspected;
* Duplicate scan;
* Ambiguous phase.

### 12.2 Warning display

Warnings appear as visible badges in the left navigator.

Rules:

* do not use blocking banners for routine warnings;
* Missing SEG blocks QC;
* all other warnings are informational;
* the doctor cannot mark warnings as resolved in v1;
* warning resolution remains technical-team responsibility.

---

## 13. Case Data Modal

### 13.1 Role

Case Data replaces any separate full-page metadata view.

Case Data is an overlay modal activated by an icon in the left panel. It is not a separate full page in v1.

### 13.2 Format

Case Data uses a clinical categorized report style.

It must not look or behave like a spreadsheet.

Required sections:

* Case Summary;
* Imaging Availability;
* Segmentation & VOI;
* QC History.

### 13.3 Required behavior

Case Data supports:

* metadata search;
* categorized sections;
* hidden raw fields by default;
* hidden technical paths by default;
* no export in v1.

Always visible fields:

* `case_id`;
* available phases;
* QC status;
* active warnings.

Secondary tabs or drawers may include:

* Inventory;
* Warnings;
* History.

---

## 14. Bottom Drawer

### 14.1 Role (v2.0 default)

The bottom drawer is **not visible by default** in v2.0.

Inventory, Warnings, and History have been migrated into the left module panel as dedicated modules (Sources, Warnings, History). This gives the 2×2 viewer workspace the maximum available screen height.

The bottom drawer component is preserved in the codebase as an optional hidden/advanced feature. If a future version requires it, it can be re-enabled without architectural changes. In v2.0, it must not reduce viewer height in the default review layout.

### 14.2 Content migration

| Previous bottom drawer tab | New location |
| --- | --- |
| Inventory | Sources module (left panel) |
| Warnings | Warnings module (left panel) |
| History | History module (left panel) |
| Metadata | Case Data modal (unchanged) |

The viewer, QC decision, active case identity, and loaded source must never be hidden behind tabs.

---

## 15. Interaction Model

### 15.1 Mouse interactions

Required viewer interactions:

| Interaction | Behavior |
| --- | --- |
| Mouse wheel | slice |
| Ctrl + wheel | zoom |
| Shift + drag | pan |
| Right drag | window/level |

### 15.2 Keyboard shortcuts

Required shortcuts:

| Key | Behavior |
| --- | --- |
| `N` | Next case |
| `A` | Accept |
| `C` | Needs correction |
| `R` | Reject |
| `Space` | Next slice |

Add:

* help overlay;
* visible shortcut tooltip for users without extensive training.

No review locked mode in v1.

---

## 16. Responsive Behavior

### 16.1 Target desktop, `1440x1000`

Use the full two-zone layout:

```text
Left module panel | Fixed 2×2 viewer workspace
```

Rules:

* left module panel width: `clamp(340px, 27vw, 480px)` (approximately 380–440px at 1440px);
* no right QC panel — QC is the QC module in the left panel;
* no bottom drawer visible by default — secondary content is in left panel modules;
* 2×2 viewer uses all remaining width and height without page-level scrolling.

### 16.2 Large desktop, up to `2560x1440`

Use the same two-zone layout with more viewer breathing room.

Rules:

* do not let metadata dominate the increased space;
* preserve CT/VOI physical aspect ratio in each panel;
* keep 3D available but secondary by default.

### 16.3 Minimum supported resolution, `1280x720`

Use compact spacing while preserving the two-screen model.

Rules:

* left module panel and viewer remain reachable;
* routine actions should still be possible without unnecessary navigation;
* compact labels and module switching are preferred over hiding primary review controls.

---

## 17. Status and Color Semantics

### 17.1 QC statuses

Use consistent badge semantics across the case navigator, source navigator, viewer status, QC panel, bottom drawer, and Case Data modal.

| Status | Meaning |
| --- | --- |
| Not reviewed | no saved curation decision |
| Accepted | reviewed and accepted |
| Needs correction | requires external correction |
| Rejected | not acceptable |
| Cannot assess | reviewer cannot make determination |
| Missing | required data unavailable |
| Warning | mapping or file issue requires attention |
| Queued | case is in correction queue |

### 17.2 Visual priority

Suggested visual priority:

1. Missing, rejected, or blocking issue.
2. Needs correction or warning.
3. Queued.
4. Not reviewed.
5. Accepted.

Color should support meaning but must not be the only indicator.

---

## 18. Navigation Model

### 18.1 Primary navigation

Primary navigation is:

```text
Dataset Load Screen -> Main Review Screen
```

The Main Review Screen contains:

* persistent full case navigator;
* source navigator;
* prominent Next Case button;
* Save & Next primary QC action;
* Case Data modal entry.

### 18.2 Not primary in v1

The following are not primary user-facing screens in v1:

* `/cases` as a primary case selection route;
* a full-page Case Data route;
* a separate full-page case metadata route;
* a separate comparison page.

---

## 19. UX Acceptance Criteria

The UX/UI architecture is acceptable when:

1. The application presents only two primary screens: Dataset Load Screen and Main Review Screen.
2. Routine review happens in the Main Review Screen.
3. The `/cases` page is not treated as a primary user-facing surface.
4. The doctor can identify the active case at all times.
5. The doctor can identify the active scan, phase, scope, side, and loaded source at all times.
6. The fixed 2×2 viewer is visible without page-level scrolling at `1440x1000`.
7. Viewer panels stay fixed while MPR images preserve physical aspect ratio and never stretch CT/VOI slices to fill the pane.
8. The left module panel is always visible. Module selector is reachable at all times.
9. QC is accessible via the QC module in the left panel at one click.
10. The viewer, active case identity, module selector, and case navigation are never hidden behind tabs.
11. The doctor can perform phase correction, scan/VOI exclusion, and QC decision without page-level scrolling.
12. Scan `0` complete CT loads by default when opening a case.
13. Segmentation QC is one decision per case.
14. Save & Next is the primary QC action.
15. Needs correction automatically adds the case to the correction queue.
16. Phase correction requires one-click confirmation.
17. Missing SEG blocks QC.
18. All non-Missing-SEG warnings are informational in v1.
19. Warning badges are visible in the left navigator.
20. Overlay controls remain in a viewer popover and support show/hide, opacity, filled mode, and contour-only mode.
21. Overlay colors are light blue for kidney, orange/red for tumor, and green for cyst.
22. A compact overlay HUD is visible in the viewer.
23. Case Data is available as an overlay modal, not a full page.
24. Case Data is categorized, searchable, and not spreadsheet-like.
25. Raw fields and technical paths are hidden by default.
26. No raw file-path interaction is needed during routine review.
27. No application code changes are required by this documentation update.

---

## 20. Implementation Guidance

### 20.1 Refactor target

Future frontend refactors should align implementation around the two-screen product model.

Recommended component decomposition:

```text
DatasetLoadScreen
├── DatasetReadinessCard
├── DatasetValidationSummary
├── StartReviewAction
└── ResumeReviewAction

MainReviewScreen
├── TopReviewBar (compact header)
├── LeftModulePanel
│   ├── ModuleSelector (dropdown: Review / Sources / QC / Case Data / Warnings / History)
│   ├── ReviewModule
│   │   ├── CaseNavigator
│   │   └── ActiveSourceSummary
│   ├── SourcesModule
│   │   ├── SourceNavigator (phase filters + scan-grouped source cards)
│   │   └── InventoryTab (collapsible detail)
│   ├── QcModule
│   │   ├── QcStatusActions
│   │   ├── CommentField
│   │   ├── CorrectionQueueState
│   │   └── SaveAndNextAction
│   ├── CaseDataModule (chips + Open Case Data modal button)
│   ├── WarningsModule
│   │   └── WarningsTab
│   └── HistoryModule
│       └── HistoryTab
├── ViewerWorkspace (fills all remaining width and height)
│   └── ViewerGrid2x2 (rectangular, no forced 1:1 aspect ratio)
│       ├── AxialPanel
│       ├── CoronalPanel
│       ├── SagittalPanel
│       ├── Surface3DSlot
│       ├── OverlayHud
│       └── OverlayPopover
├── CaseDataModal
└── HelpOverlay
```

### 20.2 What to avoid

Do not:

* modify application code as part of this documentation update;
* make `/cases` the main review surface;
* add a full-page case metadata route for v1;
* hide the viewer or QC panel behind tabs;
* rewrite the MPR rendering engine unnecessarily;
* introduce a PACS-like layout system;
* introduce segmentation editing;
* make metadata the center of the page;
* turn Case Data into a spreadsheet clone;
* use raw file paths as navigation controls;
* add too many layout modes.

### 20.3 Development sequence for future implementation

1. Align route-level UX copy and navigation with the two-screen model.
2. Refactor the main review experience into a two-zone layout (left module panel + viewer workspace).
3. Move case selection into the persistent left panel footer.
4. Move source selection into the Sources module as direct source cards for phase + scan + scope + side.
5. Replace any full-page metadata behavior with the Case Data modal.
6. Move Inventory, Warnings, and History into left panel modules. Remove bottom drawer from default render.
7. Add help overlay, shortcut tooltip, Reset Layout, and compact overlay HUD.
8. Verify screenshots at `1280x720`, `1440x1000`, and `2560x1440`.

---

## 21. Visual Regression Targets

Maintain screenshots for:

1. Dataset Load Screen at target desktop size.
2. Main Review Screen at `1440x1000`.
3. Main Review Screen at `1280x720`.
4. Main Review Screen at `2560x1440`.
5. Default scan `0` complete CT load state.
6. CT <-> VOI comparison inside the 2×2 viewer.
7. Overlay filled mode.
8. Overlay contour-only mode.
9. QC accepted state.
10. Needs correction queued state.
11. Missing SEG blocking QC state.
12. Warning badges in the left navigator.
13. Case Data modal with raw fields collapsed.
14. Help overlay and shortcut tooltip.

A build should not be considered UX-ready if the `1440x1000` Main Review Screen screenshot does not show the left module panel and fixed 2×2 viewer workspace without page-level scrolling.

---

## 22. Final UX Statement

The ccRCC CT Dataset Curation WebUI should behave as a focused two-screen medical curation product:

* dataset readiness comes first;
* routine review happens in one Main Review Screen;
* case navigation, source selection, image review, warnings, and QC are visible together;
* CT and VOI comparison stays inside the 2×2 viewer;
* Case Data is available as a modal when needed;
* curation decisions are fast, explicit, and auditable;
* the interface remains lightweight, medically legible, and purpose-built.

The goal is not to imitate large clinical or research platforms, but to preserve their useful review logic in a smaller, safer, and more focused tool.
