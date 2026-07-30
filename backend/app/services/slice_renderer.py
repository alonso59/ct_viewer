from __future__ import annotations

from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image, ImageColor


DEFAULT_LAYER_CONFIG: dict[int, dict[str, Any]] = {
    1: {"name": "Kidney", "color": "#22d3ee", "alpha": 0.10, "linewidth": 1},
    2: {"name": "Tumor", "color": "#facc15", "alpha": 0.10, "linewidth": 1},
    3: {"name": "Cyst", "color": "#e879f9", "alpha": 0.05, "linewidth": 1},
}
EXTRA_LAYER_COLORS = (
    "#60a5fa",
    "#fb7185",
    "#34d399",
    "#f97316",
    "#a78bfa",
    "#2dd4bf",
    "#f472b6",
    "#84cc16",
    "#f59e0b",
    "#c084fc",
    "#f43f5e",
    "#38bdf8",
)

# Rendered slices are resampled for display so their pixel aspect follows the
# physical voxel spacing. The source volume and mask arrays are never modified.
_MIN_DISPLAY_PX = 512
_MIN_REFORMATTED_ASPECT = 0.50


def default_layer_config(label: int) -> dict[str, Any]:
    if label in DEFAULT_LAYER_CONFIG:
        return dict(DEFAULT_LAYER_CONFIG[label])

    color = EXTRA_LAYER_COLORS[abs(label - 4) % len(EXTRA_LAYER_COLORS)]
    return {"name": f"Label {label}", "color": color, "alpha": 0.10, "linewidth": 1}


def render_slice(
    volume: np.ndarray,
    mask: np.ndarray | None,
    axis: str,
    index: int,
    ww: float,
    wl: float,
    layers: list[int],
    layer_config: dict[int, dict[str, Any]] | None = None,
    spacing: tuple[float, float, float] | None = None,
) -> bytes:
    config = layer_config or DEFAULT_LAYER_CONFIG
    image_slice = _extract_slice(volume, axis, index)
    windowed = _window_to_uint8(image_slice, ww, wl)
    image = Image.fromarray(np.repeat(windowed[..., None], 3, axis=2).astype(np.uint8), mode="RGB")

    mask_slice = _extract_slice(mask, axis, index) if mask is not None else None

    target_size = _display_size_for_slice(image_slice.shape, axis, spacing)
    if image.size != target_size:
        image = image.resize(target_size, Image.BILINEAR)
        if mask_slice is not None:
            mask_image = Image.fromarray(mask_slice.astype(np.uint8), mode="L")
            mask_slice = np.asarray(mask_image.resize(target_size, Image.NEAREST))

    if mask_slice is not None:
        rgb = np.asarray(image).astype(np.float32)
        for label in layers:
            layer_style = config.get(label) or default_layer_config(label)
            label_mask = mask_slice == label
            if not label_mask.any():
                continue

            color = np.asarray(ImageColor.getrgb(layer_style["color"]), dtype=np.float32)
            alpha = float(layer_style["alpha"])
            rgb[label_mask] = rgb[label_mask] * (1.0 - alpha) + color * alpha

        image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB")

    if mask_slice is not None:
        image = _draw_contours(image, mask_slice, layers, config)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def render_mask_overlay_slice(
    mask: np.ndarray | None,
    axis: str,
    index: int,
    layers: list[int],
    layer_config: dict[int, dict[str, Any]] | None = None,
    spacing: tuple[float, float, float] | None = None,
) -> bytes:
    if mask is None:
        raise RuntimeError("No mask is currently loaded")

    config = layer_config or DEFAULT_LAYER_CONFIG
    mask_slice = _extract_slice(mask, axis, index)

    target_size = _display_size_for_slice(mask_slice.shape, axis, spacing)
    if (int(mask_slice.shape[1]), int(mask_slice.shape[0])) != target_size:
        mask_image = Image.fromarray(mask_slice.astype(np.uint8), mode="L")
        mask_slice = np.asarray(mask_image.resize(target_size, Image.NEAREST))

    rgba = np.zeros((mask_slice.shape[0], mask_slice.shape[1], 4), dtype=np.uint8)
    for label in layers:
        layer_style = config.get(label) or default_layer_config(label)
        label_mask = mask_slice == label
        if not label_mask.any():
            continue

        color = ImageColor.getrgb(layer_style["color"])
        alpha = int(round(float(layer_style["alpha"]) * 255.0))
        if alpha > 0:
            rgba[label_mask] = (*color, max(0, min(255, alpha)))

    image = Image.fromarray(rgba, mode="RGBA")
    image = _draw_contours_rgba(image, mask_slice, layers, config)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _display_size_for_slice(
    slice_shape: tuple[int, ...],
    axis: str,
    spacing: tuple[float, float, float] | None,
) -> tuple[int, int]:
    rows = int(slice_shape[0])
    cols = int(slice_shape[1])
    row_spacing, col_spacing = _slice_pixel_spacing(axis, spacing)
    base_spacing = min(row_spacing, col_spacing)

    target_w = max(1, round(cols * (col_spacing / base_spacing)))
    target_h = max(1, round(rows * (row_spacing / base_spacing)))

    longest = max(target_w, target_h)
    if longest < _MIN_DISPLAY_PX:
        scale = _MIN_DISPLAY_PX / longest
        target_w = max(1, round(target_w * scale))
        target_h = max(1, round(target_h * scale))

    if axis.strip().lower() in {"coronal", "sagittal"}:
        target_h = max(target_h, round(target_w * _MIN_REFORMATTED_ASPECT))

    return target_w, target_h


def _slice_pixel_spacing(
    axis: str,
    spacing: tuple[float, float, float] | None,
) -> tuple[float, float]:
    sx, sy, sz = _normalize_spacing(spacing)
    normalized_axis = axis.strip().lower()
    if normalized_axis == "axial":
        return sy, sx
    if normalized_axis == "coronal":
        return sz, sx
    if normalized_axis == "sagittal":
        return sz, sy
    raise ValueError(f"Unsupported axis '{axis}'")


def _normalize_spacing(spacing: tuple[float, float, float] | None) -> tuple[float, float, float]:
    if spacing is None or len(spacing) < 3:
        return (1.0, 1.0, 1.0)

    try:
        values = tuple(float(value) for value in spacing[:3])
    except (TypeError, ValueError):
        return (1.0, 1.0, 1.0)

    if any(not np.isfinite(value) or value <= 0 for value in values):
        return (1.0, 1.0, 1.0)

    return values


def _draw_contours(
    image: Image.Image,
    mask_slice: np.ndarray,
    layers: list[int],
    layer_config: dict[int, dict[str, Any]],
) -> Image.Image:
    return _draw_contours_rgba(image.convert("RGBA"), mask_slice, layers, layer_config).convert("RGB")


def _draw_contours_rgba(
    image: Image.Image,
    mask_slice: np.ndarray,
    layers: list[int],
    layer_config: dict[int, dict[str, Any]],
) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()

    for label in layers:
        layer_style = layer_config.get(label) or default_layer_config(label)
        label_mask = mask_slice == label
        if not label_mask.any():
            continue

        boundary = _binary_boundary(label_mask)
        width = max(1, int(round(float(layer_style.get("linewidth", 1)))))
        if width > 1:
            boundary = _dilate_binary(boundary, width - 1)
        color = ImageColor.getrgb(layer_style["color"])
        rgba[boundary, 0] = color[0]
        rgba[boundary, 1] = color[1]
        rgba[boundary, 2] = color[2]
        rgba[boundary, 3] = 255

    return Image.fromarray(rgba, mode="RGBA")


def _binary_boundary(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask.astype(bool, copy=False), 1, mode="constant", constant_values=False)
    center = padded[1:-1, 1:-1]
    interior = (
        center
        & padded[:-2, 1:-1]
        & padded[2:, 1:-1]
        & padded[1:-1, :-2]
        & padded[1:-1, 2:]
    )
    return center & ~interior


def _dilate_binary(mask: np.ndarray, iterations: int) -> np.ndarray:
    dilated = mask.astype(bool, copy=False)
    for _ in range(max(0, iterations)):
        padded = np.pad(dilated, 1, mode="constant", constant_values=False)
        dilated = (
            padded[1:-1, 1:-1]
            | padded[:-2, 1:-1]
            | padded[2:, 1:-1]
            | padded[1:-1, :-2]
            | padded[1:-1, 2:]
            | padded[:-2, :-2]
            | padded[:-2, 2:]
            | padded[2:, :-2]
            | padded[2:, 2:]
        )
    return dilated


def _extract_slice(volume: np.ndarray | None, axis: str, index: int) -> np.ndarray:
    if volume is None:
        raise RuntimeError("No volume is currently loaded")

    # Loaded NIfTI arrays are canonical RAS (X=right, Y=anterior, Z=superior).
    # The returned PNG plane maps screen right/up to RAS-positive in-plane axes.
    normalized_axis = axis.strip().lower()
    if normalized_axis == "axial":
        if not 0 <= index < volume.shape[2]:
            raise IndexError(f"Axial index {index} out of bounds for depth {volume.shape[2]}")
        slice_2d = volume[:, :, index].T
    elif normalized_axis == "coronal":
        if not 0 <= index < volume.shape[1]:
            raise IndexError(f"Coronal index {index} out of bounds for height {volume.shape[1]}")
        slice_2d = volume[:, index, :].T
    elif normalized_axis == "sagittal":
        if not 0 <= index < volume.shape[0]:
            raise IndexError(f"Sagittal index {index} out of bounds for width {volume.shape[0]}")
        slice_2d = volume[index, :, :].T
    else:
        raise ValueError(f"Unsupported axis '{axis}'")

    return np.flipud(slice_2d)


def _window_to_uint8(slice_2d: np.ndarray, ww: float, wl: float) -> np.ndarray:
    if ww <= 0:
        raise ValueError("Window width must be greater than zero")

    hu_min = wl - (ww / 2.0)
    hu_max = wl + (ww / 2.0)
    clipped = np.clip(slice_2d.astype(np.float32), hu_min, hu_max)
    normalized = (clipped - hu_min) / (hu_max - hu_min)
    return np.round(normalized * 255.0).astype(np.uint8)
