# Viewer (3D Slicer-style, NiiVue)

Scope: case editor viewports, layouts, MPR interaction, overlays, 3D, memory.
Read when: working on `features/viewer`.
Depends: ADR-0003, ADR-0015, frontend/ARCHITECTURE.md, API-23/24/25, SOURCES.md (Open mode).

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
| VW-03 | Scroll = slice step; `Shift`+scroll = 10 slices; a slider per viewport shows index / total. | M |
| VW-04 | Linked crosshair across the 2D views; click or drag sets the position. Accent colors follow 3D Slicer: axial **red** `#F85149`, sagittal **yellow** `#D29922`, coronal **green** `#3FB950`, 3D `#7D8590` (GitHub Dark tones). | M |
| VW-05 | Window/level: right-drag (horizontal = width, vertical = level), numeric inputs, and presets (Soft tissue 400/50, Bone 1800/400, Lung 1500/−600, Brain 80/40, Kidney 500/100). HU presets only when `item.modality = CT` (missing = CT in projects; missing = percentiles in Open mode); otherwise the default window is the 1st–99th percentile. | M |
| VW-06 | Pan (middle-drag or `Space`+drag) and zoom (`Ctrl/Cmd`+scroll, or pinch); `R` resets; zoom can be linked across views (toggle). | M |
| VW-07 | Multi-label overlay using the project label map colors (PRJ-07): per-label visibility and opacity, outline-only toggle, global overlay opacity. | M |
| VW-08 | Cursor readout: ijk, RAS mm, image value (HU), label value under the cursor → status bar (UI-07). | M |
| VW-09 | 3D viewport: volume render of the image and/or label render; optional surface meshes (API-25) in label colors; orbit, pan, zoom; blend slider. | S |
| VW-10 | Toolbar: layout, W/L presets, overlay toggle, outline, crosshair toggle, reset, screenshot (PNG to download). | S |
| VW-11 | Item switcher in the tab header: phase chips, then scan_idx (only if >1), then scope (Full / VOI), then side (only if VOI). | M |
| VW-12 | Adaptive states: no mask → overlay controls hidden and the 3D panel shows "No segmentation"; missing file → error card with the warning code (IMP-08). | M |
| VW-13 | Loading UI: progress bar from download bytes; first slice rendered as soon as the volume is decoded. | M |
| VW-14 | Memory budget: at most `VIEWER_MAX_LOADED` (default 3) tabs keep GPU/CPU volumes; hidden tabs beyond that are unloaded and reload on focus. | M |
| VW-15 | Crosshair position and W/L are preserved when switching items within a case where the geometry matches. | S |
| VW-16 | Curation context (axis, slice, W/L) is attached to each event (CUR event `context.viewer`). | S |
| VW-17 | Measurements (distance, ROI stats) are read-only helpers and are not persisted. | C (v3.1) |
| VW-18 | Compare two items side by side with linked crosshair, e.g. NC vs NP. | C (v3.1) |
| VW-19 | Segmentation set selector in the Layers section: one overlay per visible set, each with the label map through its `label_mapping`; the active set is the curation target (`seg_id`). Default `default_seg`. | M |
| VW-20 | Two sets shown together: second set as outline-only in a contrasting style (e.g. ground truth vs nnU-Net). | C |
| VW-21 | Open mode: a label map opened alone renders with auto `label_{value}` colours; a 1-slice volume shows 2D tiles only; attaching a segmentation checks geometry first (SRC-10). | M |

## Wrapper contract (`features/viewer`)

Source of truth: `frontend/src/features/viewer/model/types.ts` (`ViewerHandle`). Summary:
`load(item, {imageUrl, maskUrl?, onProgress, onImage, signal})`, `maskError`, `setTiles`, `setWindow`, `defaultWindow`,
`setLabels`, `setOverlay`, `setLinkedZoom`, `setRender`, `setMeshes`, `setCrosshair`, `step/goto/pick/hover/pan/zoom/orbit`,
`resetView`, `onView`, `onCursor`, `screenshot`, `stats`, `dispose`. `getViewerContext()` gives CUR `context.viewer`; its `slice` is the 1-based index shown in the viewport header.

NiiVue is only imported inside `features/viewer/engine/`, and **lazily** (`createViewer` is async), so it stays out of the initial bundle (FE-05). Everything else uses `ViewerHandle`, which keeps the engine swappable.

## Decisions

- Mesh format (API-25, P1 spike): **gzip MZ3**, cached as `cache/meshes/{mask_fp}_{label}_{smooth}.mz3`, vertices in world mm via the NIfTI affine, served as `application/octet-stream`. A 302k-triangle mesh is 2.0 MB and parses in 16 ms in NiiVue 0.69 (GIfTI 2.6 MB, STL 14.8 MB, OBJ 10.4 MB).

- One NiiVue instance per case tab (P3 spike): all tiles on one canvas via `setCustomLayout`; frames, headers, sliders and crosshair lines are DOM over the canvas. Four instances would hold four GPU copies of the volume.
- Label rendering (P3 spike): custom LUT in our 2D slice shader (row 0 = colour + per-label opacity, 0 = hidden; row 1 = outline flag; outline = in-plane 4-neighbour boundary, Slicer style). NiiVue's label colormap is used only in the 3D tile (it forces alpha 1 per label and draws 3D outlines).
- 2D performance (TST-09): NiiVue re-composites the whole volume on each W/L or overlay change (≈ 0.6 s on 512×512×600). 2D tiles therefore use NiiVue's `setCustomSliceShader` hook over full-resolution textures uploaded once (R16_SNORM via EXT_texture_norm16, R32F fallback; labels R8UI/R16UI); W/L and labels are uniforms. The 3D tile renders a ≤ 24 M-voxel proxy. Still within ADR-0003.
- **NiiVue is pinned to an exact version (0.69.0)** because the slice-shader hook is not a stable public API; re-run TST-09 before any upgrade.
- TST-09 on the synthetic reference (Apple M4, Chrome): first slice 1.9 s (mask 3.1 s), scroll and W/L 60 fps, one tab 0.58 GB JS heap. Dataset820 re-run in P7.

## Known gaps (from P3)

- 3D pan not available (NiiVue has no 3D pan); orbit and zoom work.
- NFR-09 with 3 loaded tabs not measured; Safari/Firefox untested (R32F fallback doubles GPU memory for int16).
