from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image

from app.services.slice_renderer import (
    DEFAULT_LAYER_CONFIG,
    _display_size_for_slice,
    _extract_slice,
    default_layer_config,
    render_mask_overlay_slice,
    render_slice,
)


def _encoded_volume(shape: tuple[int, int, int]) -> np.ndarray:
    x, y, z = np.indices(shape)
    return (100 * x + 10 * y + z).astype(np.float32)


def _rendered_size(axis: str, spacing: tuple[float, float, float]) -> tuple[int, int]:
    volume = np.arange(4 * 4 * 2, dtype=np.float32).reshape((4, 4, 2))
    png_bytes = render_slice(
        volume=volume,
        mask=None,
        axis=axis,
        index=1,
        ww=400,
        wl=10,
        layers=[],
        spacing=spacing,
    )
    with Image.open(BytesIO(png_bytes)) as image:
        return image.size


def test_slice_renderer_uses_spacing_for_display_only_interpolation():
    assert _rendered_size("axial", (1.0, 1.0, 4.0)) == (512, 512)
    assert _rendered_size("coronal", (1.0, 1.0, 4.0)) == (256, 512)
    assert _rendered_size("sagittal", (1.0, 1.0, 4.0)) == (256, 512)
    assert _display_size_for_slice((4, 4), "axial", (2.0, 1.0, 4.0)) == (512, 256)


def test_reformatted_views_keep_a_readable_minimum_visual_height():
    assert _display_size_for_slice((45, 512), "coronal", (1.0, 1.0, 1.5)) == (512, 256)
    assert _display_size_for_slice((45, 512), "sagittal", (1.0, 1.0, 1.5)) == (512, 256)


def test_slice_renderer_preserves_axis_orientation_contract():
    volume = _encoded_volume((2, 3, 4))

    np.testing.assert_array_equal(
        _extract_slice(volume, "axial", 2),
        np.asarray(
            [
                [22, 122],
                [12, 112],
                [2, 102],
            ],
            dtype=np.float32,
        ),
    )
    np.testing.assert_array_equal(
        _extract_slice(volume, "coronal", 1),
        np.asarray(
            [
                [13, 113],
                [12, 112],
                [11, 111],
                [10, 110],
            ],
            dtype=np.float32,
        ),
    )
    np.testing.assert_array_equal(
        _extract_slice(volume, "sagittal", 1),
        np.asarray(
            [
                [103, 113, 123],
                [102, 112, 122],
                [101, 111, 121],
                [100, 110, 120],
            ],
            dtype=np.float32,
        ),
    )


def test_slice_renderer_keeps_mask_overlay_in_ras_slice_space():
    mask = np.zeros((2, 3, 4), dtype=np.uint8)
    mask[1, 2, 3] = 2

    axial = _extract_slice(mask, "axial", 3)
    coronal = _extract_slice(mask, "coronal", 2)
    sagittal = _extract_slice(mask, "sagittal", 1)

    assert axial.shape == (3, 2)
    assert coronal.shape == (4, 2)
    assert sagittal.shape == (4, 3)
    assert axial[0, 1] == 2
    assert coronal[0, 1] == 2
    assert sagittal[0, 2] == 2


def test_slice_renderer_applies_ct_window_level_to_png_pixels():
    volume = np.full((512, 512, 1), 50, dtype=np.float32)
    volume[0, 511, 0] = -100
    volume[511, 511, 0] = 200

    png_bytes = render_slice(
        volume=volume,
        mask=None,
        axis="axial",
        index=0,
        ww=300,
        wl=50,
        layers=[],
        spacing=(1.0, 1.0, 1.0),
    )

    with Image.open(BytesIO(png_bytes)) as image:
        assert image.getpixel((0, 0)) == (0, 0, 0)
        assert image.getpixel((511, 0)) == (255, 255, 255)
        assert image.getpixel((256, 256)) == (128, 128, 128)


def test_slice_renderer_applies_layer_visibility_color_opacity_and_contours():
    volume = np.zeros((512, 512, 1), dtype=np.float32)
    mask = np.zeros((512, 512, 1), dtype=np.uint8)
    mask[140:260, 140:260, 0] = 1
    mask[300:420, 300:420, 0] = 2

    hidden_png = render_slice(
        volume=volume,
        mask=mask,
        axis="axial",
        index=0,
        ww=2,
        wl=1,
        layers=[2],
        spacing=(1.0, 1.0, 1.0),
    )
    visible_png = render_slice(
        volume=volume,
        mask=mask,
        axis="axial",
        index=0,
        ww=2,
        wl=1,
        layers=[1, 2],
        spacing=(1.0, 1.0, 1.0),
    )

    assert DEFAULT_LAYER_CONFIG[1]["color"] == "#22d3ee"
    assert DEFAULT_LAYER_CONFIG[2]["color"] == "#facc15"

    with Image.open(BytesIO(hidden_png)) as hidden:
        # Label 1 is present in the mask but not in the visible layer list.
        assert hidden.getpixel((200, 512 - 1 - 200)) == (0, 0, 0)
        assert hidden.getpixel((360, 512 - 1 - 360)) == (25, 20, 2)

    with Image.open(BytesIO(visible_png)) as visible:
        assert visible.getpixel((200, 512 - 1 - 200)) == (3, 21, 23)
        assert visible.getpixel((360, 512 - 1 - 360)) == (25, 20, 2)
        pixels = np.asarray(visible)
        assert np.count_nonzero(np.all(pixels == np.asarray([34, 211, 238]), axis=2)) > 0
        assert np.count_nonzero(np.all(pixels == np.asarray([250, 204, 21]), axis=2)) > 0


def test_slice_renderer_renders_unknown_labels_with_generic_palette():
    volume = np.zeros((512, 512, 1), dtype=np.float32)
    mask = np.zeros((512, 512, 1), dtype=np.uint8)
    mask[100:160, 100:160, 0] = 4

    assert default_layer_config(4)["color"] == "#60a5fa"

    png_bytes = render_slice(
        volume=volume,
        mask=mask,
        axis="axial",
        index=0,
        ww=2,
        wl=1,
        layers=[4],
        spacing=(1.0, 1.0, 1.0),
    )

    with Image.open(BytesIO(png_bytes)) as image:
        assert image.getpixel((120, 512 - 1 - 120)) == (9, 16, 25)
        pixels = np.asarray(image)
        assert np.count_nonzero(np.all(pixels == np.asarray([96, 165, 250]), axis=2)) > 0


def test_mask_overlay_renderer_returns_transparent_rgba_slice_with_visible_contours():
    mask = np.zeros((512, 512, 1), dtype=np.uint8)
    mask[140:260, 140:260, 0] = 1
    config = {
        1: {"name": "Kidney", "color": "cyan", "alpha": 0.0, "linewidth": 1},
    }

    png_bytes = render_mask_overlay_slice(
        mask=mask,
        axis="axial",
        index=0,
        layers=[1],
        layer_config=config,
        spacing=(1.0, 1.0, 1.0),
    )

    with Image.open(BytesIO(png_bytes)) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((200, 512 - 1 - 200)) == (0, 0, 0, 0)
        pixels = np.asarray(image)
        assert np.count_nonzero(np.all(pixels == np.asarray([0, 255, 255, 255]), axis=2)) > 0


def test_slice_renderer_does_not_mutate_source_volume_or_mask():
    volume = np.arange(4 * 4 * 2, dtype=np.float32).reshape((4, 4, 2))
    mask = np.zeros((4, 4, 2), dtype=np.uint8)
    mask[1:3, 1:3, 1] = 2
    original_volume = volume.copy()
    original_mask = mask.copy()

    render_slice(
        volume=volume,
        mask=mask,
        axis="coronal",
        index=2,
        ww=400,
        wl=10,
        layers=[2],
        spacing=(1.0, 1.0, 4.0),
    )

    np.testing.assert_array_equal(volume, original_volume)
    np.testing.assert_array_equal(mask, original_mask)
