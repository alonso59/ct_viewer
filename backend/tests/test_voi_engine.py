"""VOI engine: sides from the affine (supine, prone, feet first), crop, split, preview, extract."""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from plugins.voi import engine

SHAPE = (64, 64, 40)
KIDNEY, TUMOR = 1, 2


def _ellipsoid(center: tuple[int, int, int], radii: tuple[int, int, int]) -> np.ndarray:
    i, j, k = np.indices(SHAPE)
    return (
        ((i - center[0]) / radii[0]) ** 2
        + ((j - center[1]) / radii[1]) ** 2
        + ((k - center[2]) / radii[2]) ** 2
    ) <= 1.0


def _affine(position: str) -> np.ndarray:
    """Voxel → RAS world for a patient lying supine (axis 0 → right) or prone (axis 0 → left)."""
    a = np.eye(4)
    if position == "prone":  # array axis 0 runs towards the patient's left, axis 1 posterior
        a[0, 0], a[1, 1], a[0, 3], a[1, 3] = -1.0, -1.0, 63.0, 63.0
    if position == "feet_first":
        a[2, 2], a[2, 3] = -1.0, 39.0
    return a


def _mask(path: Path, data: np.ndarray, position: str = "supine") -> str:
    nib.save(nib.Nifti1Image(data.astype(np.uint8), _affine(position)), path)
    return str(path)


def _image(path: Path, position: str = "supine", center_x: int = 32) -> str:
    body = _ellipsoid((center_x, 32, 20), (28, 22, 40))
    data = np.where(body, 40.0, -1000.0).astype(np.float32)
    nib.save(nib.Nifti1Image(data, _affine(position)), path)
    return str(path)


def _two_kidneys() -> np.ndarray:
    m = np.zeros(SHAPE, np.uint8)
    m[_ellipsoid((16, 32, 20), (6, 8, 10))] = KIDNEY
    m[_ellipsoid((48, 32, 20), (6, 8, 10))] = KIDNEY
    m[_ellipsoid((48, 32, 24), (3, 3, 3))] = TUMOR
    return m


def _run(mask_path: str, image_path: str | None = None, **kw: object) -> list[engine.Candidate]:
    grid = engine.read_grid(mask_path, as_labels=True)
    opts: dict[str, object] = {
        "lateral": True,
        "max_components": 2,
        "min_volume_ml": 0.05,
        "margin_mm": 2.0,
        "min_size_mm": (0.0, 0.0, 0.0),
        "midline": (lambda: engine.body_midline_x(image_path)) if image_path else None,
    }
    opts.update(kw)
    return engine.candidates(grid, [KIDNEY, TUMOR], **opts)  # type: ignore[arg-type]


@pytest.mark.parametrize("position", ["supine", "prone", "feet_first"])
def test_sides_follow_patient_coordinates(tmp_path: Path, position: str) -> None:
    mask = _mask(tmp_path / "m.nii.gz", _two_kidneys(), position)
    cands = _run(mask, _image(tmp_path / "i.nii.gz", position))
    by_side = {c.side: c for c in cands}
    assert set(by_side) == {"L", "R"}
    # the tumor sits in the kidney stored at array x=48; its patient side depends on the affine
    tumor_side = "L" if position == "prone" else "R"
    assert by_side[tumor_side].centroid_mm[0] == pytest.approx(
        engine._world(_affine(position), (48, 32, 20))[0], abs=1.0
    )
    assert all(not c.warnings for c in cands)


def test_single_kidney_side_from_body_midline(tmp_path: Path) -> None:
    m = np.zeros(SHAPE, np.uint8)
    m[_ellipsoid((30, 32, 20), (5, 6, 8))] = KIDNEY
    # body off the centre of the field of view: the grid centre would say "left", the body "right"
    cands = _run(_mask(tmp_path / "m.nii.gz", m), _image(tmp_path / "i.nii.gz", center_x=4))
    assert [c.side for c in cands] == ["R"]
    assert "midline_from_grid" not in cands[0].warnings


def test_lone_component_near_midline_is_ambiguous(tmp_path: Path) -> None:
    m = np.zeros(SHAPE, np.uint8)
    m[_ellipsoid((34, 32, 20), (4, 4, 4))] = KIDNEY
    cands = _run(_mask(tmp_path / "m.nii.gz", m), _image(tmp_path / "i.nii.gz"))
    assert "side_ambiguous" in cands[0].warnings


def test_fused_blob_split_at_midline(tmp_path: Path) -> None:
    m = np.zeros(SHAPE, np.uint8)
    m[8:56, 26:38, 14:26] = KIDNEY  # one connected bar across the midline (horseshoe, joined lungs)
    big = np.diag([3.0, 3.0, 3.0, 1.0])  # 3 mm voxels: halves sit well away from the midline
    body = np.where(_ellipsoid((32, 32, 20), (28, 22, 40)), 40.0, -1000.0).astype(np.float32)
    nib.save(nib.Nifti1Image(m, big), tmp_path / "m.nii.gz")
    nib.save(nib.Nifti1Image(body, big), tmp_path / "i.nii.gz")
    cands = _run(str(tmp_path / "m.nii.gz"), str(tmp_path / "i.nii.gz"))
    assert sorted(c.side for c in cands) == ["L", "R"]
    assert all("split_at_midline" in c.warnings for c in cands)


def test_non_lateral_region_is_one_box_over_all_parts(tmp_path: Path) -> None:
    cands = _run(_mask(tmp_path / "m.nii.gz", _two_kidneys()), lateral=False, max_components=1)
    assert len(cands) == 1 and cands[0].side == ""
    (x0, _, _), (x1, _, _) = cands[0].tight
    assert x0 <= 10 and x1 >= 54


def test_tiny_islands_dropped_unless_protected(tmp_path: Path) -> None:
    m = _two_kidneys()
    m[2:4, 2:4, 2:4] = KIDNEY  # noise
    m[60:62, 60:62, 36:38] = TUMOR  # tiny tumor fragment: merged, never lost
    grid = engine.read_grid(_mask(tmp_path / "m.nii.gz", m), as_labels=True)
    cands = engine.candidates(
        grid,
        [KIDNEY, TUMOR],
        lateral=True,
        max_components=2,
        min_volume_ml=0.1,
        margin_mm=0,
        min_size_mm=(0, 0, 0),
        protect=[TUMOR],
        midline=32.0,
    )
    assert len(cands) == 2
    right = next(c for c in cands if c.side == "R")
    assert right.tight[1][0] == 62 and "protected_component_merged" in right.warnings
    assert all(c.tight[0][0] > 4 for c in cands)


def test_crop_box_min_size_shifts_away_from_border() -> None:
    tight = ((0, 10, 10), (10, 20, 20))
    crop = engine.crop_box(
        tight, (64, 64, 40), (1.0, 1.0, 2.0), margin_mm=0, min_size_mm=(30, 0, 100)
    )
    assert crop[0][0] == 0 and crop[1][0] == 30  # blocked at 0: grows the other way
    assert crop[0][2] == 0 and crop[1][2] == 40  # larger than the image: clamped


def test_preview_and_extract(tmp_path: Path) -> None:
    mask = _mask(tmp_path / "m.nii.gz", _two_kidneys(), "prone")
    image = _image(tmp_path / "i.nii.gz", "prone")
    cand = _run(mask, image, min_size_mm=(20.0, 20.0, 20.0))[0]
    webp = engine.render_preview(image, cand)
    assert webp[:4] == b"RIFF" and webp[8:12] == b"WEBP"
    meta = engine.extract(
        image,
        mask,
        cand,
        [KIDNEY, TUMOR],
        str(tmp_path / "vi.nii.gz"),
        str(tmp_path / "vm.nii.gz"),
        resample_mm=None,
    )
    assert meta["shape"] == [cand.crop[1][a] - cand.crop[0][a] for a in range(3)]
    out = nib.load(tmp_path / "vm.nii.gz")
    assert nib.aff2axcodes(out.affine) == ("R", "A", "S")
    assert (
        int(np.asarray(out.dataobj).max()) == KIDNEY or int(np.asarray(out.dataobj).max()) == TUMOR
    )
    meta = engine.extract(
        image,
        mask,
        cand,
        [KIDNEY, TUMOR],
        str(tmp_path / "ri.nii.gz"),
        str(tmp_path / "rm.nii.gz"),
        resample_mm=2.0,
    )
    assert meta["spacing"] == [2.0, 2.0, 2.0]


def test_mask_with_a_mirrored_header_follows_the_image(tmp_path: Path) -> None:
    """A mask written voxel for voxel over an RAS image but stored with an LPS header (PanTS)."""
    image = _image(tmp_path / "i.nii.gz")
    lps = np.diag([-1.0, -1.0, 1.0, 1.0])
    nib.save(nib.Nifti1Image(_two_kidneys(), lps), tmp_path / "m.nii.gz")
    out = engine.analyze(image, str(tmp_path / "m.nii.gz"), [KIDNEY, TUMOR], [TUMOR], "kidney")
    tumor_side = next(c for c in out["candidates"] if c["label_ml"].get(str(TUMOR)))
    assert tumor_side["side"] == "R"  # voxel x=48 is patient right in the image's geometry
    assert all("mask_header_differs" in c["warnings"] for c in out["candidates"])
    assert all(c["confidence"] == "uncertain" for c in out["candidates"])  # nothing else checks it


@pytest.mark.parametrize("liver_at", [10, 54])
def test_liver_and_spleen_correct_a_mirrored_header(tmp_path: Path, liver_at: int) -> None:
    """Liver (14) on the patient's left of the spleen (24): the header mirrors left and right."""
    m = _two_kidneys()
    m[_ellipsoid((liver_at, 20, 30), (8, 8, 6))] = 14
    m[_ellipsoid((64 - liver_at, 20, 30), (5, 5, 5))] = 24
    image, mask = _image(tmp_path / "i.nii.gz"), _mask(tmp_path / "m.nii.gz", m)
    anatomy = {14: "R", 24: "L"}  # liver, spleen
    out = engine.analyze(image, mask, [KIDNEY, TUMOR], [TUMOR], "kidney", anatomy=anatomy)
    tumor = next(c for c in out["candidates"] if c["label_ml"].get(str(TUMOR)))
    mirrored = liver_at < 32  # liver at low x = world left in RAS
    assert tumor["side"] == ("L" if mirrored else "R")
    assert all(("sides_from_anatomy" in c["warnings"]) is mirrored for c in out["candidates"])
    assert all(c["confidence"] == "verified" for c in out["candidates"])


def test_confidence_probable_from_coordinates_only(tmp_path: Path) -> None:
    out = engine.analyze(
        _image(tmp_path / "i.nii.gz"),
        _mask(tmp_path / "m.nii.gz", _two_kidneys()),
        [KIDNEY, TUMOR],
        [TUMOR],
        "kidney",
    )
    assert [c["confidence"] for c in out["candidates"]] == ["probable", "probable"]


@pytest.mark.parametrize(("left_at", "mismatch"), [(16, False), (48, True)])
def test_side_named_labels_cross_check_the_coordinates(
    tmp_path: Path, left_at: int, mismatch: bool
) -> None:
    """`kidney_left` (12) / `kidney_right` (13): a label naming the other side is flagged."""
    m = np.zeros(SHAPE, np.uint8)
    m[_ellipsoid((left_at, 32, 20), (6, 8, 10))] = 12
    m[_ellipsoid((64 - left_at, 32, 20), (6, 8, 10))] = 13
    out = engine.analyze(
        _image(tmp_path / "i.nii.gz"), _mask(tmp_path / "m.nii.gz", m), [12, 13], [], "kidney",
        {12: "L", 13: "R"},
    )  # fmt: skip
    assert all(("label_side_mismatch" in c["warnings"]) is mismatch for c in out["candidates"])
    assert all(
        c["confidence"] == ("uncertain" if mismatch else "verified") for c in out["candidates"]
    )


def test_side_hints_from_label_names() -> None:
    labels = {"kidney_left": 12, "kidney_right": 13, "right-lung": 16, "liver": 14}
    hints = engine.side_hints(list(labels), lambda n: [labels[x] for x in n])
    assert hints == {12: "L", 13: "R", 16: "R"}


def test_labels_reaching_the_scan_edge_are_flagged(tmp_path: Path) -> None:
    m = np.zeros(SHAPE, np.uint8)
    m[10:20, 20:30, 0:4] = KIDNEY  # cut by the first slice
    cands = _run(_mask(tmp_path / "m.nii.gz", m), _image(tmp_path / "i.nii.gz"))
    assert "at_image_edge" in cands[0].warnings
