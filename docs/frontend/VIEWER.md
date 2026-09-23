# Viewer (3D Slicer-style, NiiVue)

Scope: case editor viewports, layouts, MPR interaction, overlays, 3D, memory.
Read when: working on `features/viewer`.
Depends: ADR-0003, frontend/ARCHITECTURE.md, API-23/24/25.

## Model

- One **case editor tab** has one active item: image + optional mask loaded once from API-23/24.
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
| VW-05 | Window/level: right-drag (horizontal = width, vertical = level), numeric inputs, and presets (Soft tissue 400/50, Bone 1800/400, Lung 1500/−600, Brain 80/40, Kidney 500/100). | M |
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

## Wrapper contract (`features/viewer`)

```ts
interface ViewerHandle {
  load(item: ItemRecord, opts: { imageUrl: string; maskUrl?: string }): Promise<void>;
  setLayout(id: LayoutId): void;
  setWindow(ww: number, wl: number): void;
  setLabel(value: number, p: { visible?: boolean; opacity?: number; outline?: boolean }): void;
  setCrosshair(ras: [number, number, number]): void;
  onCursor(cb: (r: CursorReadout) => void): Unsubscribe;
  snapshot(): ViewerContext;            // for CUR context
  dispose(): void;
}
```

NiiVue is only imported inside `features/viewer/engine/`. Everything else uses `ViewerHandle`, which keeps the engine swappable.

## Technical spikes (P3, no user decision needed)

- Can NiiVue render the 2×2 layout from one instance (multiplanar + render tiles), or does it need four instances sharing one volume? Pick the one with lower memory.
- Label rendering: NiiVue label colormap vs a custom LUT with outline support.

## Decisions

- Mesh format (API-25, P1 spike): **gzip MZ3**, cached as `cache/meshes/{mask_fp}_{label}_{smooth}.mz3`, vertices in world mm via the NIfTI affine, served as `application/octet-stream`. A 302k-triangle mesh is 2.0 MB and parses in 16 ms in NiiVue 0.69 (GIfTI 2.6 MB, STL 14.8 MB, OBJ 10.4 MB).
