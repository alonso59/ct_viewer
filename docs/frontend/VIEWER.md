# Viewer (3D Slicer-style, NiiVue)

Scope: case editor viewports, layouts, MPR interaction, overlays, 3D, memory.
Read when: working on `features/viewer`.
Depends: ADR-0003, ADR-0015, ADR-0023, frontend/ARCHITECTURE.md, API-23/24/25, SOURCES.md (Open mode).

## Model

- One **case editor tab** has one active item: image + zero or more segmentation sets (ADR-0015), each loaded once from API-23/24 (`?seg=`).
- Open mode (SRC-09) uses the same viewer over API-07/08, with curation and tasks hidden.
- NiiVue renders every viewport on the GPU. Slice scrolling, W/L and overlays never call the server.
- Orientation comes from the NIfTI affine and is displayed in RAS world space; nothing is resampled or rewritten.

## Layouts

| ID | Layout | Viewports |
|---|---|---|
| `four-up` (default) | 2×2 | Axial · Sagittal / Coronal · 3D |
| `conventional` | 1 large + 3 small | Axial large; Sagittal, Coronal, 3D stacked |
| `one-up-{axial\|sagittal\|coronal\|3d}` | 1 | Single viewport |
| `three-mpr` | 1×3 | Axial · Sagittal · Coronal |

## Requirements

| ID | Requirement | Pri |
|---|---|---|
| VW-01 | Layouts as listed; switch via toolbar, `L` key, or command; the layout is kept in the URL (FE-04). | M |
| VW-02 | Maximize a viewport by double-clicking its header or pressing the maximize button; `Esc` restores the layout. | M |
| VW-03 | Scroll = slice step; `Shift`+scroll = 10 slices; a slider per viewport shows the index and total as "`{{index}} · {{total}}`" in the UI font, not `ui-monospace` (ADR-0023 — avoids reading as an editor's line/column indicator). The slider track is a 2 px neutral line (`--plane-track`); the plane colour is only on its thumb (AUD-A3-22). | M |
| VW-04 | Linked crosshair across the 2D views; click or drag sets the position. Accent colors follow 3D Slicer: axial **red** `#CF6679`, sagittal **yellow** `#C9A23C`, coronal **green** `#4F9D7C`, 3D `#7D8590` — desaturated off the literal `--error`/`--warn`/`--ok` GitHub Dark tokens so a plane accent doesn't read as a diff/lint status color (ADR-0023). The panel border stays a neutral `--border-muted`; the plane color lives in an 8×8 px chip in the header (`.vp-chip`), not the border. Crosshair lines (full opacity, with a 1 px `--viewport-halo` so they stay legible over any overlay) and the slice slider's thumb use the same desaturated values; the orientation letters sit 8 px off the centre lines (AUD-A3-22). | M |
| VW-05 | Window/level: right-drag (horizontal = width, vertical = level), numeric inputs, and presets (Soft tissue 400/50, Bone 1800/400, Lung 1500/−600, Brain 80/40, Kidney 500/100). Modality rule (projects and Open mode alike): a **known** modality (DICOM header, input metadata, the import's `modality` option) is used as is and shows no selector; an **unknown** one (`null`: NIfTI or NumPy without metadata) is **assumed CT**, and a "CT (assumed) ▾" selector (CT · MR · Other) appears next to W/L so the user can change it. The choice is display-only (per item, in memory; the index is not changed) and is carried as the `modality` option into Add to project… / Create project from this (SRC-14/15). HU presets and the soft-tissue default apply to CT; any other modality opens on the 1st–99th percentile window. | M |
| VW-06 | Pan (middle-drag or `Space`+drag) and zoom (`Ctrl/Cmd`+scroll, or pinch) act **only on the view under the pointer** (3D Slicer behaviour): each 2D view keeps its own field of view, and only the crosshair / slice position is shared (VW-04). A "Link zoom across views" toggle stays in the tool bar as an opt-in, **off by default**, not persisted; turning it on copies the last-used view's field of view to the others. `R` is the global reset (VW-10); per-view fit is VW-26. | M |
| VW-07 | Multi-label overlay using the project label map colors (PRJ-07): per-label visibility and opacity, outline-only toggle, global overlay opacity. | M |
| VW-08 | Cursor readout, one format for the status bar (UI-07) and the in-view probe (VW-22): value with its unit (`HU` for CT, `value` for any other modality, VW-05) · label name (value) · ijk · RAS mm, e.g. "35 HU · kidney (1) · ijk 29, 31, 24 · RAS 31.2, 29.2, 36 mm" (`features/viewer/readout.ts`, AUD-A2-11, AUD-A3-05). | M |
| VW-09 | 3D viewport: volume render of the image and/or label render; optional surface meshes (API-25) in label colors; orbit, pan, zoom; blend slider. | S |
| VW-10 | Toolbar: layout, W/L presets, overlay toggle, outline, crosshair toggle, reset, screenshot (PNG to download). Reset (`R`, tool bar) is global and keeps its meaning: fit every view (VW-26 on all tiles, 3D camera included), crosshair to the volume centre, the default W/L (VW-25), restore a maximized view. | S |
| VW-11 | Item switcher in the tab header: **Scan** chips (one per phase present), then scan_idx (only if >1), then scope (Full / VOI), then side (only if VOI). The scan's assigned phase (PHS-01) follows as a separate **Phase** segmented control with the effective value pressed; the header wraps on a narrow editor instead of hiding the review status (AUD-A1-12). | M |
| VW-12 | Adaptive states: no mask → overlay controls hidden and the 3D panel shows "No segmentation"; missing file → error card with the warning code (IMP-08). | M |
| VW-13 | Loading UI: progress bar from download bytes; first slice rendered as soon as the volume is decoded. | M |
| VW-14 | Memory budget: at most `VIEWER_MAX_LOADED` (default 3) tabs keep GPU/CPU volumes; hidden tabs beyond that are unloaded and reload on focus. | M |
| VW-15 | Crosshair position and W/L are preserved when switching items within a case where the geometry matches. | S |
| VW-16 | Curation context (axis, slice, W/L) is attached to each event (CUR event `context.viewer`). | S |
| VW-17 | Measurements (distance, angle, ROI mean/SD in HU) are read-only helpers; not persisted without a project (ADR-0021). | S |
| VW-18 | Compare two items side by side with linked crosshair, e.g. NC vs NP. | C |
| VW-19 | Segmentation set selector in the Layers section: one overlay per visible set, each with the label map through its `label_mapping`; the active set is the curation target (`seg_id`). Default `default_seg`. Implemented (P7b Wave 4) with one visible set at a time: the selector switches the overlay, meshes (`?seg=`) and label colours (set values → project labels); two sets at once is VW-20. The choice is kept per project; an item without a mask in the chosen set shows the `default_seg` mask with the notice "Not in set X", and mask decisions name the set whose mask is on screen (AUD-A5-05). | M |
| VW-20 | Two sets shown together: second set as outline-only in a contrasting style (e.g. ground truth vs nnU-Net). | C |
| VW-21 | Open mode: a label map opened alone renders with auto `label_{value}` colours; a 1-slice volume shows 2D tiles only; attaching a segmentation checks geometry first (SRC-10). The Open toolbar holds the three actions of UI-17 (Save as NIfTI…, Add to project…, Create project from this) and nothing that edits files. Implemented by the viewer's `StandaloneViewer` (same surface as a case tab, no curation or tasks); Open records keep the DICOM modality or `null` (assumed CT, VW-05); the action row layout is UI-17, Close is UI-24. | M |
| VW-22 | CT tool set, identical in the case tab and Open mode (file or folder), ADR-0021 **Must**: W/L presets + numeric W/L + DICOM header window (`WindowCenter/Width`, when `display.use_dicom_window`), layout, zoom/pan, crosshair, slice slider, reset, screenshot, HU probe, header info (NIfTI header / DICOM tags), modality selector when assumed (VW-05); viewer shortcuts work in both. | M |
| VW-23 | ADR-0021 **Should**: slab MIP / MinIP / average with a thickness in mm (2D tiles), invert. | S |
| VW-24 | ADR-0021 **Could**: cine loop, histogram, MR colour maps. | C |
| VW-25 | Display settings (PRJ-18) set the initial layout, W/L per modality, interpolation (linear / nearest) and the radiological (patient right on screen left, default) or neurological convention. | M |
| VW-26 | **Fit to window per view** (3D Slicer's "Fit to window"): a fit button in each viewport header, left of maximize (tooltip "Fit to window", `F` on the view under the pointer, else on the maximized view). On a 2D view it restores zoom 100 % and zero pan so the whole slice fits the tile; slice index, crosshair, W/L, overlays and the other views do not change. On the 3D view it restores the camera (zoom, azimuth/elevation). When zoom is linked (VW-06) fit applies to all 2D views. A new item opens fitted (as today). | M |

## Implementation (P7c Wave 4)

- One tool set (VW-22/23): the basic tool bar items (tools, layout, overlay, W/L presets, reset, screenshot) plus the lazy `CtTools.tsx` chunk (measurements, numeric W/L + the DICOM header window, slab MIP/MinIP/average with thickness, invert, header info). The case tab shows them in the shell tool bar; Open mode renders the same components as `CtToolbar`. Tools and viewer commands are enabled whenever a viewer is visible (`useViewerLocal.active`), so the shortcuts work in Open mode too; on any other editor the tool bar shows none of them (UI-06, AUD-A3-20).
- Engine: `setDisplay({invert, slab, interpolation, convention})` (slice-shader uniforms `rwInvert`, `rwSlabMode`, `rwSlabHalf`: up to 64 samples each side along the plane normal, labels from the centre slice; interpolation switches the image texture filter; convention sets NiiVue's radiological flag and flips horizontal pan), `worldAt`, `canvasAt`, `roiStats` (voxels of the full-resolution image within the radius on the tile's slice).
- HU probe: the VW-08 readout inside the hovered 2D view, at its bottom-left above the slice slider (never over another tile). Loads are ordered (`engine/loadGate.ts`): after every await a load or mesh update stops unless it is still the newest and not aborted, so a slower older load never replaces the newer image and meshes are never added twice (VW-14/15, AUD-A5-13). Measurements: distance (2 clicks), angle (3, at the middle point), circular ROI (centre + edge: mean, SD, n, area); drawn in canvas space, shown on the slice they were made on, kept in memory for the visible item, cleared on a new item or with "Clear measurements" (VW-17).
- DICOM window: converter rows carry `window_center` / `window_width` (first values); Open-mode DICOM items carry `window` `[width, center]`; with `display.use_dicom_window` a new item opens on it, and a "DICOM" button re-applies it. Header info: geometry of the item and, on demand, the DICOM tags (API-22, or `GET /open/{sid}/items/{n}/dicom-tags`).
- VW-25: `applyProjectDisplay` puts the project's CT window (also the `R` reset target), presets (they replace the built-in list), DICOM-window flag, interpolation, convention and `default_modality` (assumed modality for items without one; `mixed` assumes CT) into the viewer store; the layout only on the first open when the URL has none. Open mode resets to the defaults.

## Wrapper contract (`features/viewer`)

Source of truth: `frontend/src/features/viewer/model/types.ts` (`ViewerHandle`). Summary:
`load(item, {imageUrl, maskUrl?, onProgress, onImage, signal})`, `maskError`, `setTiles`, `setWindow`, `defaultWindow`,
`setLabels`, `setOverlay`, `setLinkedZoom`, `setRender`, `setMeshes`, `setCrosshair`, `step/goto/pick/hover/pan/zoom/orbit`,
`resetView`, `fitView(tile)` (VW-26), `onView`, `onCursor`, `screenshot`, `setDisplay`, `worldAt`, `canvasAt`, `roiStats`, `stats`, `dispose`. `getViewerContext()` gives CUR `context.viewer`; its `slice` is the 1-based index shown in the viewport header.

NiiVue is only imported inside `features/viewer/engine/`, and **lazily** (`createViewer` is async), so it stays out of the initial bundle (FE-05). Everything else uses `ViewerHandle`, which keeps the engine swappable.

## Decisions

- Independent field of view per view (owner, 2026-09-25, amends VW-06/10, adds VW-26): like 3D Slicer, zoom/pan never propagate between views unless the user links them; the existing global Reset keeps its semantics so the `R` habit does not change. No ADR: ADR-0003 is unaffected.

- Mesh format (API-25, P1 spike): **gzip MZ3**, cached as `cache/meshes/{mask_fp}_{label}_{smooth}.mz3`, vertices in world mm via the NIfTI affine, served as `application/octet-stream`. A 302k-triangle mesh is 2.0 MB and parses in 16 ms in NiiVue 0.69 (GIfTI 2.6 MB, STL 14.8 MB, OBJ 10.4 MB).

- One NiiVue instance per case tab (P3 spike): all tiles on one canvas via `setCustomLayout`; frames, headers, sliders and crosshair lines are DOM over the canvas. Four instances would hold four GPU copies of the volume.
- Label rendering (P3 spike): custom LUT in our 2D slice shader (row 0 = colour + per-label opacity, 0 = hidden; row 1 = outline flag; outline = in-plane 4-neighbour boundary, Slicer style). NiiVue's label colormap is used only in the 3D tile (it forces alpha 1 per label and draws 3D outlines).
- 2D performance (TST-09): NiiVue re-composites the whole volume on each W/L or overlay change (≈ 0.6 s on 512×512×600). 2D tiles therefore use NiiVue's `setCustomSliceShader` hook over full-resolution textures uploaded once (R16_SNORM via EXT_texture_norm16, R32F fallback; labels R8UI/R16UI); W/L and labels are uniforms. The 3D tile renders a ≤ 24 M-voxel proxy. Still within ADR-0003.
- **NiiVue is pinned to an exact version (0.69.0)** because the slice-shader hook is not a stable public API; re-run TST-09 before any upgrade.
- TST-09 on the synthetic reference (Apple M4, Chrome): first slice 1.9 s (mask 3.1 s), scroll and W/L 60 fps, one tab 0.58 GB JS heap. Dataset820 re-run in P7.

## Known gaps (from P3)

- 3D pan not available (NiiVue has no 3D pan); orbit and zoom work.
- NFR-09 with 3 loaded tabs not measured; Safari/Firefox untested (R32F fallback doubles GPU memory for int16).
