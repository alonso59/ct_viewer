"""VOI candidates from a segmentation mask: components, sides, crop box, axial preview.

Everything works on the canonical RAS grid (`as_closest_canonical`): array axes are
x = patient right, y = anterior, z = superior, whatever the acquisition or patient position
(prone, supine, feet first), because sides come from the affine, never from voxel order.
Imports no `app` code; callers pass paths and plain values.
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import nibabel as nib
import numpy as np
from numpy.typing import NDArray
from scipy import ndimage  # type: ignore[import-untyped]


def _region(
    lateral: bool,
    min_ml: float,
    organ: list[str],
    extra: list[str],
    protect: list[str],
    min_size: list[float],
) -> dict[str, Any]:
    return {
        "lateral": lateral,
        "max_components": 2 if lateral else 1,
        "min_volume_ml": min_ml,
        "organ": organ,
        "labels": organ + extra,
        "protect": protect,
        "margin_mm": 5.0,
        "min_size_mm": min_size,
    }


# Label names are matched case-insensitively against the project label map. The region's own
# labels need one `organ` label in the project, so a "tumor" label of another organ never
# builds a liver VOI; `protect` labels are never dropped as small islands (a tumour fragment
# joins the nearest organ box).
REGIONS: dict[str, dict[str, Any]] = {
    "kidney": _region(
        True, 1.0, ["kidney", "kidney_left", "kidney_right"], ["tumor", "cyst"], ["tumor"], [96.0, 96.0, 120.0]
    ),
    "lung": _region(True, 20.0, ["lung", "lung_left", "lung_right"], ["nodule"], ["nodule"], [0.0, 0.0, 0.0]),
    "liver": _region(False, 50.0, ["liver"], ["tumor"], ["tumor"], [0.0, 0.0, 0.0]),
    "pancreas": _region(
        False,
        2.0,
        ["pancreas", "pancreas_head", "pancreas_body", "pancreas_tail"],
        ["pancreatic_duct", "pancreatic_lesion", "tumor"],
        ["pancreatic_lesion", "tumor"],
        [64.0, 64.0, 64.0],
    ),
    "stomach": _region(False, 10.0, ["stomach"], [], [], [0.0, 0.0, 0.0]),
    "heart": _region(False, 50.0, ["heart"], [], [], [0.0, 0.0, 0.0]),
    "custom": _region(False, 0.5, [], [], [], [0.0, 0.0, 0.0]),
}


def side_hints(names: Sequence[str], values_of: Any) -> dict[int, str]:
    """File values of labels whose name says a side (`kidney_left`, `right_lung`) → `L` / `R`."""
    out: dict[int, str] = {}
    for name in names:
        words = name.lower().replace("-", "_").split("_")
        side = "L" if "left" in words else "R" if "right" in words else None
        if side:
            for v in values_of([name]):
                out[int(v)] = side
    return out


def file_values(
    names: Sequence[str],
    project_labels: dict[str, int],
    mapping: dict[str, int] | None,
    organ: Sequence[str] = (),
) -> tuple[list[int], list[str]]:
    """Label names → values as stored in the mask file, plus the names the project lacks.

    `mapping` is the set's file value → project value (identity when empty). With `organ`,
    no values unless one of those names is in the project.
    """
    by_name = {k.lower(): v for k, v in project_labels.items()}
    if organ and not any(o.lower() in by_name for o in organ):
        return [], [n for n in names if n.lower() not in by_name]
    values: list[int] = []
    missing: list[str] = []
    for name in names:
        pv = by_name.get(name.lower())
        if pv is None:
            missing.append(name)
            continue
        if mapping:
            values += [int(k) for k, v in mapping.items() if int(v) == pv]
        else:
            values.append(pv)
    if organ:  # other spellings of a present organ are not missing
        missing = [n for n in missing if n.lower() not in {o.lower() for o in organ}]
    return sorted(set(values)), missing


MIN_FRACTION_OF_LARGEST = 0.01
SPLIT_MIN_FRACTION = 0.2  # a fused lateral blob is cut at the midline when both halves hold this share
AMBIGUOUS_MM = 15.0  # a lone component this close to the midline has an uncertain side
OBLIQUE_TOLERANCE = 0.3  # off-axis share of an affine column above which the grid is oblique

Box = tuple[tuple[int, int, int], tuple[int, int, int]]  # start (inclusive), stop (exclusive)


@dataclass
class Grid:
    data: NDArray[Any]
    affine: NDArray[np.float64]
    zooms: tuple[float, float, float]
    warnings: list[str] = field(default_factory=list)


def _canonical(img: Any) -> tuple[Any, list[str]]:
    affine = np.asarray(img.affine, dtype=float)
    cols = affine[:3, :3] / np.maximum(np.linalg.norm(affine[:3, :3], axis=0), 1e-9)
    off_axis = 1.0 - np.abs(cols).max(axis=0)
    warnings = ["oblique_grid"] if float(off_axis.max()) > OBLIQUE_TOLERANCE else []
    return nib.as_closest_canonical(img), warnings


def _same_geometry(a: NDArray[Any], b: NDArray[Any]) -> bool:
    return bool(np.allclose(a[:3, :3], b[:3, :3], atol=1e-3) and np.allclose(a[:3, 3], b[:3, 3], atol=1.0))


def _on_image_grid(mask: Any, image: Any) -> tuple[Any, list[str]]:
    """The mask's voxels on the image's geometry.

    A mask is written voxel for voxel over its image; its own header is sometimes wrong (an LPS
    header over an RAS image mirrors it in x and y), so the image's affine decides where the
    voxels are. Different shapes cannot be aligned this way and are refused.
    """
    if mask.shape[:3] != image.shape[:3]:
        raise ValueError("image and mask do not share a grid")
    if _same_geometry(np.asarray(mask.affine), np.asarray(image.affine)):
        return mask, []
    data = np.asanyarray(mask.dataobj)
    return nib.Nifti1Image(data, np.asarray(image.affine, dtype=float)), ["mask_header_differs"]


def read_grid(path: str, *, as_labels: bool, ref: str | None = None) -> Grid:
    """A volume on the canonical RAS grid; with `ref` (its image), on that image's geometry."""
    raw: Any = nib.load(path)
    aligned: list[str] = []
    if ref is not None:
        raw, aligned = _on_image_grid(raw, nib.load(ref))
    img, warnings = _canonical(raw)
    warnings = [*warnings, *aligned]
    arr = np.asanyarray(img.dataobj)
    if arr.ndim > 3:
        arr = arr[..., 0]
    if as_labels:
        arr = np.rint(arr).astype(np.int32)
    zooms = tuple(float(z) for z in img.header.get_zooms()[:3])
    return Grid(arr, np.asarray(img.affine, dtype=float), zooms, warnings)  # type: ignore[arg-type]


def _world(affine: NDArray[np.float64], ijk: Iterable[float]) -> list[float]:
    return [float(v) for v in (affine @ np.append(np.asarray(list(ijk), dtype=float), 1.0))[:3]]


def body_midline_x(image_path: str) -> float | None:
    """World x (RAS) of the body's left-right centre, from a coarse read.

    An opening cuts the thin links (blankets, straps) that join the table to the body; the
    centre is the median of the body's soft tissue, so arms, the table and a field of view that
    cuts one flank shift it little.
    """
    img, _ = _canonical(nib.load(image_path))
    step = (4, 4, 2)
    small = np.asarray(img.dataobj[:: step[0], :: step[1], :: step[2]], dtype=np.float32)
    if small.ndim > 3:
        small = small[..., 0]
    labels, n = ndimage.label(ndimage.binary_opening(small > -300, iterations=2))
    if n == 0:
        return None
    body = labels == (int(np.argmax(np.bincount(labels.ravel())[1:])) + 1)
    soft = body & (small > -150) & (small < 150)
    xs = np.nonzero(soft if soft.any() else body)[0]
    return _world(np.asarray(img.affine, dtype=float), (float(np.median(xs)) * step[0], 0, 0))[0]


@dataclass
class Candidate:
    cid: str
    side: str  # L | R | "" (no laterality)
    voxels: int
    volume_ml: float
    centroid_mm: list[float]
    tight: Box
    crop: Box
    tight_size_mm: list[float]
    crop_size_mm: list[float]
    z_mid: int
    warnings: list[str]
    label_ml: dict[str, float] = field(default_factory=dict)  # file value → mL inside the label box
    confidence: str = ""  # sides: verified | probable | uncertain; "" without laterality

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.cid,
            "side": self.side,
            "voxels": self.voxels,
            "volume_ml": round(self.volume_ml, 2),
            "centroid_mm": [round(v, 1) for v in self.centroid_mm],
            "tight": [list(self.tight[0]), list(self.tight[1])],
            "crop": [list(self.crop[0]), list(self.crop[1])],
            "tight_size_mm": [round(v, 1) for v in self.tight_size_mm],
            "crop_size_mm": [round(v, 1) for v in self.crop_size_mm],
            "z_mid": self.z_mid,
            "warnings": self.warnings,
            "label_ml": {k: round(v, 2) for k, v in self.label_ml.items()},
            "confidence": self.confidence,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Candidate:
        def box(b: Any) -> Box:
            return tuple(int(v) for v in b[0]), tuple(int(v) for v in b[1])  # type: ignore[return-value]

        return cls(
            cid=str(d["id"]),
            side=str(d["side"]),
            voxels=int(d["voxels"]),
            volume_ml=float(d["volume_ml"]),
            centroid_mm=[float(v) for v in d["centroid_mm"]],
            tight=box(d["tight"]),
            crop=box(d["crop"]),
            tight_size_mm=[float(v) for v in d["tight_size_mm"]],
            crop_size_mm=[float(v) for v in d["crop_size_mm"]],
            z_mid=int(d["z_mid"]),
            warnings=list(d["warnings"]),
            label_ml={str(k): float(v) for k, v in (d.get("label_ml") or {}).items()},
            confidence=str(d.get("confidence") or ""),
        )


# Organs whose side never changes (situs solitus): where they lie checks the header's left/right.
ANATOMY = {"liver": "R", "spleen": "L"}
ANATOMY_MARGIN_MM = 30.0
# A side with one of these is uncertain whatever else agrees; the soft ones only without evidence.
HARD_DOUBT = {"side_ambiguous", "both_on_one_side_of_midline", "label_side_mismatch", "split_at_midline"}
SOFT_DOUBT = {"midline_from_grid", "oblique_grid", "mask_header_differs"}
SWAP = {"L": "R", "R": "L"}


def _mirrored_by_anatomy(grid: Grid, anatomy: dict[int, str], midline: Any) -> bool | None:
    """True when the liver lies on the patient's left of the spleen (or of the midline):
    the header's left/right is mirrored (a wrong header, or a prone patient stored as supine)."""
    x_of: dict[str, float] = {}
    for side in ("R", "L"):
        vals = [v for v, s in anatomy.items() if s == side]
        sel = np.isin(grid.data, vals) if vals else None
        if sel is not None and sel.any():
            x_of[side] = _world(grid.affine, (float(np.nonzero(sel)[0].mean()), 0, 0))[0]
    if "R" in x_of and "L" in x_of:
        gap = x_of["R"] - x_of["L"]
    elif x_of:
        mid = midline()
        if mid is None:
            return None
        side, x = next(iter(x_of.items()))
        gap = (x - mid) if side == "R" else (mid - x)
    else:
        return None
    if abs(gap) < ANATOMY_MARGIN_MM:
        return None
    return gap < 0


def analyze(
    image_path: str | None,
    mask_path: str,
    values: Sequence[int],
    protect: Sequence[int],
    region: str,
    hints: dict[int, str] | None = None,
    anatomy: dict[int, str] | None = None,
) -> dict[str, Any]:
    """The slow part (reads the volumes), independent of margin and minimum size, so it caches.

    Sides come from the image's coordinates, then are checked: `anatomy` (file value → the side
    of an organ that never moves, liver R, spleen L) corrects a mirrored header, and `hints`
    (file value → the side its label name states) cross-check each VOI. Each lateral VOI gets a
    confidence: verified (independent evidence agrees), probable (coordinates only) or uncertain.
    """
    preset = REGIONS[region]
    grid = read_grid(mask_path, as_labels=True, ref=image_path)
    cache: dict[str, float | None] = {}

    def midline() -> float | None:
        if "m" not in cache:
            cache["m"] = body_midline_x(image_path) if image_path else None
        return cache["m"]

    cands = candidates(
        grid,
        values,
        lateral=bool(preset["lateral"]),
        max_components=int(preset["max_components"]),
        min_volume_ml=float(preset["min_volume_ml"]),
        margin_mm=0.0,
        min_size_mm=(0.0, 0.0, 0.0),
        protect=protect,
        midline=midline,
    )
    if preset["lateral"] and cands:
        mirrored = _mirrored_by_anatomy(grid, anatomy, midline) if anatomy else None
        for c in cands:
            if mirrored and c.side:
                c.side = SWAP[c.side]
                c.cid = c.side
                c.warnings = sorted({*c.warnings, "sides_from_anatomy"})
            named = {"L": 0.0, "R": 0.0}
            for v, ml in c.label_ml.items():
                if hints and int(v) in hints:
                    named[hints[int(v)]] += ml
            said = max(named, key=lambda k: named[k]) if any(named.values()) else None
            if c.side and said and said != c.side:
                c.warnings = sorted({*c.warnings, "label_side_mismatch"})
            doubts = set(c.warnings) & (HARD_DOUBT | SOFT_DOUBT)
            mid = midline()
            # anatomy checks the header, not which part got which side: that needs the part to
            # lie clearly on its own side of the midline too
            clear = (
                mid is not None
                and c.side in SWAP
                and ((c.centroid_mm[0] - mid) * (1 if c.side == "R" else -1)) * (-1 if mirrored else 1) >= AMBIGUOUS_MM
            )
            if not c.side or doubts & HARD_DOUBT:
                c.confidence = "uncertain"
            elif (said is not None and said == c.side) or (mirrored is not None and clear and not doubts):
                c.confidence = "verified"
            else:
                c.confidence = "uncertain" if doubts else "probable"
    return {
        "shape": [int(v) for v in grid.data.shape],
        "zooms": list(grid.zooms),
        "candidates": [c.to_json() for c in cands],
    }


def reframe(analysis: dict[str, Any], margin_mm: float, min_size_mm: Sequence[float]) -> list[Candidate]:
    """Crop boxes for a margin and minimum size over a cached `analyze` result (no file reads)."""
    zooms = analysis["zooms"]
    out = []
    for d in analysis["candidates"]:
        c = Candidate.from_json(d)
        c.crop = crop_box(c.tight, analysis["shape"], zooms, margin_mm, min_size_mm)
        c.crop_size_mm = [(c.crop[1][a] - c.crop[0][a]) * zooms[a] for a in range(3)]
        c.z_mid = (c.crop[0][2] + c.crop[1][2] - 1) // 2
        out.append(c)
    return out


def crop_box(
    tight: Box,
    shape: Sequence[int],
    zooms: Sequence[float],
    margin_mm: float,
    min_size_mm: Sequence[float],
) -> Box:
    """Margin, then grow each axis to the minimum size; a blocked side gives its share to the other."""
    start: list[int] = []
    stop: list[int] = []
    for ax in range(3):
        lo, hi = tight[0][ax], tight[1][ax]
        lo -= int(np.ceil(margin_mm / zooms[ax]))
        hi += int(np.ceil(margin_mm / zooms[ax]))
        need = int(np.ceil(min_size_mm[ax] / zooms[ax])) - (hi - lo)
        if need > 0:
            lo -= need // 2
            hi += need - need // 2
        n = int(shape[ax])
        if lo < 0:
            hi = min(n, hi - lo)
            lo = 0
        if hi > n:
            lo = max(0, lo - (hi - n))
            hi = n
        start.append(lo)
        stop.append(hi)
    return (start[0], start[1], start[2]), (stop[0], stop[1], stop[2])


def _box_of(slices: tuple[slice, ...]) -> Box:
    return (
        (slices[0].start, slices[1].start, slices[2].start),
        (slices[0].stop, slices[1].stop, slices[2].stop),
    )


def _union(a: Box, b: Box) -> Box:
    lo = tuple(min(x, y) for x, y in zip(a[0], b[0], strict=True))
    hi = tuple(max(x, y) for x, y in zip(a[1], b[1], strict=True))
    return lo, hi  # type: ignore[return-value]


def candidates(
    mask: Grid,
    values: Sequence[int],
    *,
    lateral: bool,
    max_components: int,
    min_volume_ml: float,
    margin_mm: float,
    min_size_mm: Sequence[float],
    protect: Sequence[int] = (),
    midline: Any = None,
) -> list[Candidate]:
    """Bounding-box candidates; `midline` is a world x or a callable returning one (read lazily)."""
    binary = np.isin(mask.data, list(values))
    if not binary.any():
        return []
    zooms = mask.zooms
    voxel_ml = float(np.prod(zooms)) / 1000.0
    nz = [np.nonzero(binary.any(axis=tuple(a for a in range(3) if a != ax)))[0] for ax in range(3)]
    lo = [int(n.min()) for n in nz]
    region = binary[tuple(slice(lo[ax], int(nz[ax].max()) + 1) for ax in range(3))]
    labels, n = ndimage.label(region, structure=np.ones((3, 3, 3), dtype=bool))
    sizes = np.bincount(labels.ravel())[1:]
    objs = ndimage.find_objects(labels)
    comps: list[dict[str, Any]] = []
    for k in range(n):
        sl = objs[k]
        assert sl is not None
        comp_mask = labels[sl] == k + 1
        grid_sl = tuple(slice(sl[a].start + lo[a], sl[a].stop + lo[a]) for a in range(3))
        com = ndimage.center_of_mass(comp_mask)
        comps.append(
            {
                "voxels": int(sizes[k]),
                "box": _box_of(grid_sl),
                "centroid": [com[a] + sl[a].start + lo[a] for a in range(3)],
                "protected": bool(protect and np.isin(mask.data[grid_sl][comp_mask], list(protect)).any()),
            }
        )
    comps.sort(key=lambda c: c["voxels"], reverse=True)
    largest = comps[0]["voxels"]
    kept = [
        c for c in comps if c["voxels"] * voxel_ml >= min_volume_ml and c["voxels"] >= MIN_FRACTION_OF_LARGEST * largest
    ]
    if not kept:
        kept = comps[:1]
    kept = kept[: max(1, max_components)] if lateral else kept
    for c in comps:  # tiny islands that hold a protected label join the nearest kept component
        if c in kept or not c["protected"]:
            continue
        near = min(kept, key=lambda k: float(np.linalg.norm(np.subtract(k["centroid"], c["centroid"]))))
        near["box"] = _union(near["box"], c["box"])
        near["voxels"] += c["voxels"]
        near.setdefault("notes", []).append("protected_component_merged")
    for c in kept:
        c["world"] = _world(mask.affine, c["centroid"])

    sides: list[str]
    notes: list[list[str]] = [list(c.get("notes", [])) for c in kept]
    if not lateral:
        merged = kept[0]
        for c in kept[1:]:
            merged["box"] = _union(merged["box"], c["box"])
            merged["voxels"] += c["voxels"]
            merged["centroid"] = [
                (a * merged["voxels"] + b * c["voxels"]) / (merged["voxels"] + c["voxels"])
                for a, b in zip(merged["centroid"], c["centroid"], strict=True)
            ]
        merged["world"] = _world(mask.affine, merged["centroid"])
        kept, sides, notes = [merged], [""], [notes[0] if notes else []]
    else:
        mid = midline() if callable(midline) else midline
        if mid is None:
            ext = mask.data.shape[0] - 1
            mid = _world(mask.affine, (ext / 2.0, 0, 0))[0]
            mid_note = ["midline_from_grid"]
        else:
            mid_note = []
        if len(kept) == 1:
            c = kept[0]
            split = _split_at_midline(mask, binary, c, float(mid))
            if split:
                kept, notes = split, [["split_at_midline"], ["split_at_midline"]]
        if len(kept) >= 2:
            ordered = sorted(range(len(kept)), key=lambda i: kept[i]["world"][0], reverse=True)
            sides = [""] * len(kept)
            for rank, i in enumerate(ordered):
                sides[i] = "R" if rank == 0 else ("L" if rank == 1 else "")
            if len(kept) == 2 and (kept[ordered[0]]["world"][0] < mid or kept[ordered[1]]["world"][0] > mid):
                for nt in notes:
                    nt.append("both_on_one_side_of_midline")
            kept, sides, notes = (
                [kept[i] for i in ordered[:2]],
                [sides[i] for i in ordered[:2]],
                [notes[i] for i in ordered[:2]],
            )
        else:
            c = kept[0]
            dx = c["world"][0] - float(mid)
            sides = ["R" if dx > 0 else "L"]
            if abs(dx) < AMBIGUOUS_MM:
                notes[0].append("side_ambiguous")
        for nt in notes:
            nt.extend(mid_note)

    out: list[Candidate] = []
    for idx, (c, side, nt) in enumerate(zip(kept, sides, notes, strict=True)):
        tight: Box = c["box"]
        crop = crop_box(tight, mask.data.shape, zooms, margin_mm, min_size_mm)
        (bx0, by0, bz0), (bx1, by1, bz1) = tight
        if any(tight[0][a] == 0 or tight[1][a] >= mask.data.shape[a] for a in range(3)):
            nt = [*nt, "at_image_edge"]  # the labels reach the edge: the organ may be cut off
        found, counts = np.unique(mask.data[bx0:bx1, by0:by1, bz0:bz1], return_counts=True)
        label_ml = {str(int(v)): float(n) * voxel_ml for v, n in zip(found, counts, strict=True) if int(v) in values}
        size = [(tight[1][a] - tight[0][a]) * zooms[a] for a in range(3)]
        csize = [(crop[1][a] - crop[0][a]) * zooms[a] for a in range(3)]
        out.append(
            Candidate(
                cid=side or f"V{idx + 1}",
                side=side,
                voxels=int(c["voxels"]),
                volume_ml=c["voxels"] * voxel_ml,
                centroid_mm=c["world"],
                tight=tight,
                crop=crop,
                tight_size_mm=size,
                crop_size_mm=csize,
                z_mid=(crop[0][2] + crop[1][2] - 1) // 2,
                warnings=sorted({*nt, *mask.warnings}),
                label_ml=label_ml,
            )
        )
    return out


def _split_at_midline(
    mask: Grid, binary: NDArray[np.bool_], comp: dict[str, Any], mid: float
) -> list[dict[str, Any]] | None:
    """Cut a fused blob (horseshoe kidney, connected lungs) at the midline when both halves are real."""
    (x0, y0, z0), (x1, y1, z1) = comp["box"]
    xs = np.arange(x0, x1)
    right = mask.affine[0, 0] * xs + mask.affine[0, 3] > mid  # canonical grid: x follows axis 0
    sub = binary[x0:x1, y0:y1, z0:z1]
    per_x = sub.sum(axis=(1, 2))
    total = int(per_x.sum())
    nr, nl = int(per_x[right].sum()), int(per_x[~right].sum())
    if total == 0 or min(nr, nl) < SPLIT_MIN_FRACTION * total:
        return None
    halves: list[dict[str, Any]] = []
    for sel, count in ((right, nr), (~right, nl)):
        part = np.zeros_like(sub)
        part[sel] = sub[sel]
        nz = [np.nonzero(part.any(axis=tuple(a for a in range(3) if a != ax)))[0] for ax in range(3)]
        lo = (x0 + int(nz[0].min()), y0 + int(nz[1].min()), z0 + int(nz[2].min()))
        hi = (x0 + int(nz[0].max()) + 1, y0 + int(nz[1].max()) + 1, z0 + int(nz[2].max()) + 1)
        com = ndimage.center_of_mass(part)
        centroid = [com[0] + x0, com[1] + y0, com[2] + z0]
        halves.append({"voxels": count, "box": (lo, hi), "centroid": centroid, "world": _world(mask.affine, centroid)})
    if any(abs(h["world"][0] - mid) < AMBIGUOUS_MM for h in halves):
        return None  # a small structure on the midline, not two organs
    return halves


# ---------------------------------------------------------------- preview


def _ras_slab(path: str, z_index: int) -> tuple[NDArray[Any], tuple[float, float]]:
    """Axial slice at canonical-grid `z_index` as `[x, y]`, reading one slab of the file."""
    img: Any = nib.load(path)
    affine = np.asarray(img.affine, dtype=float)
    ornt = nib.orientations.io_orientation(affine)
    axes = [int(a) for a in ornt[:, 0]]
    flips = [ornt[i, 1] < 0 for i in range(3)]
    zooms = np.sqrt((affine[:3, :3] ** 2).sum(axis=0))
    z_in = axes.index(2)
    n = int(img.shape[z_in])
    idx = n - 1 - z_index if flips[z_in] else z_index
    slicer: list[Any] = [slice(None)] * 3
    slicer[z_in] = int(np.clip(idx, 0, n - 1))
    slicer += [0] * (len(img.shape) - 3)
    sl = np.asarray(img.dataobj[tuple(slicer)])
    a, b = (i for i in range(3) if i != z_in)
    if flips[a]:
        sl = sl[::-1, :]
    if flips[b]:
        sl = sl[:, ::-1]
    if axes[a] == 1:
        sl = sl.T
        a, b = b, a
    return sl, (float(zooms[a]), float(zooms[b]))


def _boxes_webp(
    sl: NDArray[Any],
    spacing: tuple[float, float],
    boxes: Sequence[tuple[tuple[int, int, int, int], tuple[int, int, int]]],
    size_px: int,
    window: tuple[float, float] = (400.0, 40.0),
) -> bytes:
    """An axial `[x, y]` slice as WebP with boxes `(x0, y0, x1, y1)` drawn in their colours.

    Fixed display (anterior up, patient right on the image left, R/L marked), so a prone scan
    reads like a supine one.
    """
    from PIL import Image, ImageDraw, ImageFont

    ww, wl = window
    gray = np.clip((np.nan_to_num(sl.astype(np.float32)) - (wl - ww / 2)) / ww, 0, 1)
    g = np.ascontiguousarray(np.asarray(gray * 255 + 0.5, dtype=np.uint8).T[::-1, ::-1])
    h, w = g.shape
    sx, sy = spacing
    scale = size_px / max(w * sx, h * sy)
    tw, th = max(1, round(w * sx * scale)), max(1, round(h * sy * scale))
    img = Image.fromarray(g).resize((tw, th), Image.Resampling.BILINEAR).convert("RGB")
    draw = ImageDraw.Draw(img)
    for (bx0, by0, bx1, by1), color in boxes:
        # columns run right to left (x reversed), rows anterior to posterior (y reversed)
        left, right = (w - bx1) / w * tw, (w - bx0) / w * tw
        top, bottom = (h - by1) / h * th, (h - by0) / h * th
        draw.rectangle([left, top, right - 1, bottom - 1], outline=color, width=2)
    font = ImageFont.load_default(size=max(14, size_px // 16))
    for text, x in (("R", 4), ("L", tw - 4)):
        anchor = "lm" if text == "R" else "rm"
        bb = draw.textbbox((x, th // 2), text, font=font, anchor=anchor)
        draw.rectangle([bb[0] - 3, bb[1] - 2, bb[2] + 3, bb[3] + 2], fill=(0, 0, 0))
        draw.text((x, th // 2), text, fill=(255, 255, 255), font=font, anchor=anchor)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", lossless=True)
    return buf.getvalue()


LABEL_BOX = (255, 220, 60)  # yellow: the labels' bounding box
CROP_BOX = (40, 150, 255)  # blue: the VOI crop


def render_preview(image_path: str, cand: Candidate, *, size_px: int = 320) -> bytes:
    """WebP of the candidate's middle axial slice with its label box and crop box."""
    z = cand.z_mid
    sl, spacing = _ras_slab(image_path, z)
    (cx0, cy0, _), (cx1, cy1, _) = cand.crop
    padx = max(8, int(0.35 * (cx1 - cx0)))
    pady = max(8, int(0.35 * (cy1 - cy0)))
    x0, x1 = max(0, cx0 - padx), min(sl.shape[0], cx1 + padx)
    y0, y1 = max(0, cy0 - pady), min(sl.shape[1], cy1 + pady)

    def local(box: Box) -> tuple[int, int, int, int]:
        (bx0, by0, _), (bx1, by1, _) = box
        return bx0 - x0, by0 - y0, bx1 - x0, by1 - y0

    return _boxes_webp(
        sl[x0:x1, y0:y1], spacing, [(local(cand.crop), CROP_BOX), (local(cand.tight), LABEL_BOX)], size_px
    )


# ---------------------------------------------------------------- extraction


def extract(
    image_path: str,
    mask_path: str,
    cand: Candidate,
    values: Sequence[int],
    out_image: str,
    out_mask: str,
    *,
    resample_mm: float | None,
    keep_labels: bool = True,
) -> dict[str, Any]:
    """Write the crop (image + mask) as NIfTI in RAS; optionally resample to isotropic voxels."""
    raw_img: Any = nib.load(image_path)
    raw_msk, _ = _on_image_grid(nib.load(mask_path), raw_img)
    img, _ = _canonical(raw_img)
    msk, _ = _canonical(raw_msk)
    (x0, y0, z0), (x1, y1, z1) = cand.crop
    sub_i = img.slicer[x0:x1, y0:y1, z0:z1]
    sub_m = msk.slicer[x0:x1, y0:y1, z0:z1]
    data_m = np.rint(np.asanyarray(sub_m.dataobj)).astype(np.uint8)
    if not keep_labels:
        data_m = np.isin(data_m, list(values)).astype(np.uint8)
    out_i = nib.Nifti1Image(np.asanyarray(sub_i.dataobj).astype(np.float32), sub_i.affine)
    out_m = nib.Nifti1Image(data_m, sub_m.affine)
    if resample_mm:
        from nibabel.processing import resample_to_output

        vox = [float(resample_mm)] * 3
        out_i = resample_to_output(out_i, vox, order=3, cval=-1000.0)
        out_m = resample_to_output(out_m, vox, order=0)
        out_m = nib.Nifti1Image(np.asarray(out_m.dataobj).astype(np.uint8), out_m.affine)
    nib.save(out_i, out_image)
    nib.save(out_m, out_mask)
    return {
        "shape": [int(v) for v in out_i.shape],
        "spacing": [round(float(v), 3) for v in out_i.header.get_zooms()[:3]],
    }


def render_result(image_path: str, mask_path: str, values: Sequence[int], *, size_px: int = 320) -> bytes:
    """WebP of a written VOI: the middle axial slice of its label box, with that box drawn.

    The whole image is the crop; the yellow box is where the VOI labels lie inside it.
    """
    img, _ = _canonical(nib.load(image_path))
    msk, _ = _canonical(nib.load(mask_path))
    labels = np.rint(np.asarray(msk.dataobj)).astype(np.int32)
    lab = np.isin(labels, list(values)) if values else labels > 0  # older catalogs: every label
    shape = labels.shape
    if lab.any():
        nz = [np.nonzero(lab.any(axis=tuple(a for a in range(3) if a != ax)))[0] for ax in range(3)]
        lo = [int(n.min()) for n in nz]
        hi = [int(n.max()) + 1 for n in nz]
    else:
        lo, hi = [0, 0, 0], list(shape)
    z = (lo[2] + hi[2] - 1) // 2
    sl = np.asarray(img.dataobj[:, :, z], dtype=np.float32)
    zooms = img.header.get_zooms()
    boxes = [((0, 0, shape[0], shape[1]), CROP_BOX)]
    if lab.any():
        boxes.append(((lo[0], lo[1], hi[0], hi[1]), LABEL_BOX))
    return _boxes_webp(sl, (float(zooms[0]), float(zooms[1])), boxes, size_px)
