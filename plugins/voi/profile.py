"""Training contract of a `voi.extract` run: lesion catalog, sampling profile, dataset fingerprint.

Pure functions of the catalog rows (their measured lesions) and the foreground histograms; no
volume is read, so a profile can be recomputed with other settings at once. Keys follow the
research pipeline's sampling profile (schema 1, extended here as schema 2) and dataset fingerprint
(schema 3), which its lesion-centric patch sampler and loaders read.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np

from plugins.voi.lesions import HU_BINS, HU_LO

DEFAULTS: dict[str, Any] = {
    "bin_percentiles": [20.0, 50.0, 80.0, 95.0],
    "balancing_alpha": 0.5,
    "budget_by_bin": None,  # one per bin, smallest first; None scales with the bin's rank
    "role_priors_by_bin": None,  # [{center, border, context}] per bin; None scales with rank
    "hu_window": [-100.0, 300.0],
    "patch_size_candidates": None,  # [[x, y, z]] in voxels
}
ROLES = ("center", "border", "context")
# Research defaults for five bins, smallest first; other bin counts interpolate them by rank.
_BUDGET = [2.0, 2.0, 3.0, 4.0, 5.0]
_PRIORS = [(0.85, 0.10, 0.05), (0.65, 0.25, 0.10), (0.50, 0.30, 0.20), (0.40, 0.35, 0.25), (0.30, 0.40, 0.30)]
PATCH_MARGIN_MM = 12.0  # added on each side of a lesion box in the patch recommendations
NOTES = [
    "Lesions are connected components of the lesion labels in each written VOI crop.",
    "Voxel coordinates and boxes refer to the crop files (mask_path, image_path) as written.",
    "Sample by lesion and role (center, border, context), not by a subject's tumor burden.",
]


def profile_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    """The profile settings of a run or request, defaults filled in; ValueError when invalid."""
    s = {k: (settings[k] if settings.get(k) is not None else v) for k, v in DEFAULTS.items()}
    lo, hi = s["hu_window"]
    if not lo < hi:
        raise ValueError(f"hu_window needs low < high, got {lo}, {hi}")
    if not s["bin_percentiles"] or not all(0 < p < 100 for p in s["bin_percentiles"]):
        raise ValueError("bin_percentiles need values between 0 and 100")
    return s


def settings_hash(settings: Mapping[str, Any]) -> str:
    raw = json.dumps(profile_settings(settings), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _pkey(p: float) -> str:
    return f"p{str(p).replace('.', '_')}"  # the research key: 5 → p5, 20.0 → p20_0


def _percentiles(values: Sequence[float], ps: Sequence[float]) -> dict[str, float]:
    return {_pkey(p): float(np.percentile(values, p)) for p in ps} if len(values) else {}


def latest_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One catalog row per VOI: a VOI extracted again (a resumed item) keeps its last row."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        out[(str(row["item_id"]), str(row.get("candidate")))] = row
    return list(out.values())


def lesion_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The lesion catalog without size bins: one row per lesion, VOI fields first."""
    out: list[dict[str, Any]] = []
    for row in rows:
        found = row.get("lesions") or []
        for les in found:
            out.append(
                {
                    "case_id": row.get("case_id"),
                    "item_id": row["item_id"],
                    "voi_id": str(row["mask"]).removesuffix("_mask.nii.gz"),
                    "laterality": row.get("side") or "unknown",
                    "phase": row.get("phase"),
                    "mask_path": row["mask"],
                    "image_path": row["image"],
                    "lesion_id": int(les["lesion"]) - 1,
                    "num_lesions_in_voi": len(found),
                    "voi_shape": row.get("shape"),
                    "spacing": row.get("spacing"),
                    "coordinates_reference": "voi_local",
                    **les,
                }
            )
    return out


def _ml(mm3: float) -> str:
    return f"{mm3 / 1000:.3g}"


def size_bins(volumes: Sequence[float], percentiles: Sequence[float]) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Percentile cuts of the lesion volumes (mm³) and the bins they make, smallest first."""
    ps = sorted(float(p) for p in percentiles)
    cuts = [float(np.percentile(volumes, p)) for p in ps]
    unique: list[float] = []
    for c in cuts:
        if not unique or c > unique[-1]:
            unique.append(c)  # small datasets can repeat a cut; repeated cuts would make empty bins
    bins: list[dict[str, Any]] = []
    lower: float | None = None
    for i in range(len(unique) + 1):
        upper = unique[i] if i < len(unique) else None
        if lower is None:
            label = f"≤ {_ml(upper or 0)} mL"
        elif upper is None:
            label = f"> {_ml(lower)} mL"
        else:
            label = f"{_ml(lower)}–{_ml(upper)} mL"
        bins.append(
            {"name": f"b{i}", "label": label, "metric": "volume_mm3", "min_inclusive": lower, "max_inclusive": upper}
        )
        lower = upper
    return {_pkey(p): c for p, c in zip(ps, cuts, strict=True)}, bins


def bin_of(volume: float, bins: Sequence[dict[str, Any]]) -> str:
    for b in bins:
        if b["max_inclusive"] is not None and volume <= b["max_inclusive"]:
            return str(b["name"])
    return str(bins[-1]["name"])


def _by_rank(i: int, n: int) -> tuple[int, dict[str, float]]:
    pos = 4.0 * i / (n - 1) if n > 1 else 2.0
    budget = round(float(np.interp(pos, range(5), _BUDGET)))
    raw = [float(np.interp(pos, range(5), [p[r] for p in _PRIORS])) for r in range(3)]
    return budget, {role: round(v / sum(raw), 4) for role, v in zip(ROLES, raw, strict=True)}


def _budgets_and_priors(
    bins: Sequence[dict[str, Any]], s: Mapping[str, Any]
) -> tuple[dict[str, int], dict[str, dict[str, float]], list[str]]:
    """Per bin, the given budget and role priors, or ones scaled by rank; a given list whose
    length is not the number of bins (repeated cuts merge bins) is not used, with a warning."""
    n = len(bins)
    warnings: list[str] = []
    given: dict[str, Any] = {}
    for what in ("budget_by_bin", "role_priors_by_bin"):
        v = s[what]
        if v is not None and len(v) != n:
            warnings.append(f"{what} has {len(v)} values for {n} size bins; the defaults were used")
            v = None
        given[what] = v
    budgets: dict[str, int] = {}
    priors: dict[str, dict[str, float]] = {}
    for i, b in enumerate(bins):
        budget, prior = _by_rank(i, n)
        if given["budget_by_bin"] is not None:
            budget = int(given["budget_by_bin"][i])
        if given["role_priors_by_bin"] is not None:
            w = [max(float(given["role_priors_by_bin"][i].get(r, 0.0)), 0.0) for r in ROLES]
            if sum(w) > 0:
                prior = {r: round(x / sum(w), 4) for r, x in zip(ROLES, w, strict=True)}
            else:
                warnings.append(f"role priors of {b['name']} are all zero; the defaults were used")
        budgets[b["name"]] = budget
        priors[b["name"]] = prior
    return budgets, priors, warnings


def _patch_recommendations(
    lesions: Sequence[dict[str, Any]],
    names: Sequence[str],
    bins: Sequence[dict[str, Any]],
    spacing: Sequence[float] | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for b in bins:
        boxes = [les["bbox_size_mm"] for les, name in zip(lesions, names, strict=True) if name == b["name"]]
        if not boxes:
            continue
        p75, p90 = (np.percentile(np.asarray(boxes, dtype=np.float64), q, axis=0) for q in (75, 90))
        rec: dict[str, Any] = {
            "units": "mm",
            "bbox_extent_p75": p75.tolist(),
            "bbox_extent_p90": p90.tolist(),
            "recommended_min_patch_extent": (p75 + 2 * PATCH_MARGIN_MM).tolist(),
            "recommended_context_patch_extent": (p90 + 2 * PATCH_MARGIN_MM).tolist(),
        }
        if spacing is not None:
            sp = np.asarray(spacing, dtype=np.float64)
            rec["recommended_min_patch_vox"] = [int(v) for v in np.ceil((p75 + 2 * PATCH_MARGIN_MM) / sp)]
            rec["recommended_context_patch_vox"] = [int(v) for v in np.ceil((p90 + 2 * PATCH_MARGIN_MM) / sp)]
        out[str(b["name"])] = rec
    return out


def build_profile(
    lesions: Sequence[dict[str, Any]], settings: Mapping[str, Any], spacing: Sequence[float] | None
) -> tuple[dict[str, Any], list[str]]:
    """The sampling profile (schema 2: schema 1's keys plus bin labels, settings and their hash)
    and each lesion's size bin. `spacing` is the voxel size shared by every crop, if any."""
    s = profile_settings(settings)
    head = {"version": 2, "num_lesions": len(lesions), "settings": s, "settings_hash": settings_hash(s)}
    if not lesions:
        return {**head, "size_bin_thresholds": {}, "size_bins": [], "target_spacing": spacing, "notes": NOTES}, []
    volumes = [float(les["volume_mm3"]) for les in lesions]
    thresholds, bins = size_bins(volumes, s["bin_percentiles"])
    names = [bin_of(v, bins) for v in volumes]
    counts = {b["name"]: names.count(b["name"]) for b in bins if b["name"] in names}
    empirical = {k: v / len(names) for k, v in counts.items()}
    alpha = float(np.clip(s["balancing_alpha"], 0.0, 1.0))
    target = {k: (1 - alpha) * p + alpha / len(counts) for k, p in empirical.items()}
    budgets, priors, warnings = _budgets_and_priors(bins, s)
    boxes = np.asarray([les["bbox_size_mm"] for les in lesions], dtype=np.float64)
    candidates = s["patch_size_candidates"] or []
    vox = np.asarray([les["bbox_size_vox"] for les in lesions], dtype=np.float64)
    profile = {
        **head,
        "volume_metric": "volume_mm3",
        "extent_metric": "max_extent_mm",
        "bbox_metric": "bbox_size_mm",
        "target_spacing": list(spacing) if spacing is not None else None,
        "size_bin_thresholds": thresholds,
        "size_bins": bins,
        "lesion_volume_percentiles": _percentiles(volumes, [5, 10, 25, 50, 75, 90, 95]),
        "lesion_max_extent_percentiles": _percentiles(
            [float(les["max_extent_mm"]) for les in lesions], [5, 10, 25, 50, 75, 90, 95]
        ),
        "lesion_bbox_extent_percentiles": {
            **{f"p{q}": np.percentile(boxes, q, axis=0).tolist() for q in (25, 50, 75, 90)},
            "units": "mm",
        },
        "size_bin_counts": counts,
        "empirical_size_bin_probabilities": empirical,
        "target_size_bin_probabilities": target,
        "balancing_alpha": alpha,
        "suggested_patch_budget_by_size_bin": budgets,
        "suggested_patch_role_priors_by_size_bin": priors,
        "heuristic_patch_recommendations": _patch_recommendations(lesions, names, bins, spacing),
        "patch_size_candidates": [list(c) for c in candidates] or None,
        "patch_size_candidate_evaluation": {
            str(tuple(int(v) for v in c)): {
                "bbox_full_coverage_rate": float(np.mean(np.all(vox <= np.asarray(c, dtype=np.float64), axis=1))),
                "num_lesions": len(lesions),
            }
            for c in candidates
        },
        "warnings": warnings,
        "notes": NOTES,
    }
    return profile, names


def pool_histograms(hists: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Foreground histograms of several VOIs as one: full 1 HU counts and exact moments."""
    counts = np.zeros(HU_BINS, dtype=np.int64)
    n, total, sq, lo, hi = 0, 0.0, 0.0, np.inf, -np.inf
    for h in hists:
        start = int(h["lo"]) - HU_LO
        counts[start : start + len(h["counts"])] += np.asarray(h["counts"], dtype=np.int64)
        n += int(h["n"])
        total += float(h["sum"])
        sq += float(h["sumsq"])
        if h["n"]:
            lo, hi = min(lo, float(h["min"])), max(hi, float(h["max"]))
    return {"counts": counts, "n": n, "sum": total, "sumsq": sq, "min": lo, "max": hi}


def _value_at(cum: np.ndarray, rank: int) -> float:
    return float(HU_LO + int(np.searchsorted(cum, rank, side="right")))


def _hist_percentile(counts: np.ndarray, q: float) -> float:
    """numpy's default (linear) percentile over the values the 1 HU counts stand for."""
    cum = np.cumsum(counts)
    h = (int(cum[-1]) - 1) * q / 100.0
    lo, frac = int(np.floor(h)), h - np.floor(h)
    a = _value_at(cum, lo)
    return a + frac * (_value_at(cum, lo + 1) - a) if frac else a


def _stats(counts: np.ndarray, n: int, mean: float, var: float, vmin: float, vmax: float) -> dict[str, Any]:
    if n == 0:
        return {}
    p = {
        k: _hist_percentile(counts, q)
        for k, q in (("p0_5", 0.5), ("p5", 5), ("p25", 25), ("median", 50), ("p75", 75), ("p95", 95), ("p99_5", 99.5))
    }
    return {
        "mean": mean,
        "std": float(np.sqrt(max(var, 0.0))),
        "min": vmin,
        "max": vmax,
        "median": p["median"],
        "p0_5": p["p0_5"],
        "p5": p["p5"],
        "p25": p["p25"],
        "p75": p["p75"],
        "p95": p["p95"],
        "p99_5": p["p99_5"],
        "iqr": p["p75"] - p["p25"],
    }


def build_fingerprint(
    rows: Sequence[dict[str, Any]],
    hists: Iterable[Mapping[str, Any]],
    settings: Mapping[str, Any],
    spacing: Sequence[float] | None,
) -> dict[str, Any]:
    """The dataset fingerprint (research schema 3). Raw statistics are exact in mean, std, min
    and max and to 1 HU in percentiles; windowed ones (values clipped to `hu_window`) are to 1 HU."""
    s = profile_settings(settings)
    w_lo, w_hi = (float(v) for v in s["hu_window"])
    pool = pool_histograms(hists)
    n = int(pool["n"])
    raw_mean = pool["sum"] / n if n else 0.0
    raw = _stats(pool["counts"], n, raw_mean, pool["sumsq"] / n - raw_mean**2 if n else 0.0, pool["min"], pool["max"])
    values = np.arange(HU_BINS, dtype=np.float64) + HU_LO
    clipped = np.clip(values, w_lo, w_hi)
    wc = np.zeros(HU_BINS, dtype=np.int64)
    np.add.at(wc, (np.rint(clipped) - HU_LO).astype(np.intp), pool["counts"])
    w_mean = float((clipped * pool["counts"]).sum() / n) if n else 0.0
    w_var = float((clipped**2 * pool["counts"]).sum() / n - w_mean**2) if n else 0.0
    windowed = _stats(wc, n, w_mean, w_var, max(pool["min"], w_lo), min(pool["max"], w_hi))
    shapes = np.asarray([r["shape"] for r in rows], dtype=np.int64)
    lesion_labels = sorted({name for r in rows for name in r.get("lesion_labels") or []})
    return {
        "version": 3,
        "foreground_intensity": {"channel_0": raw},
        "windowed_intensity": {"channel_0": windowed},
        "normalization": {
            "method": "window_rescale",
            "window_min": w_lo,
            "window_max": w_hi,
            "output_min": -1.0,
            "output_max": 1.0,
        },
        "voi_shape_statistics": {
            "min": shapes.min(axis=0).tolist(),
            "max": shapes.max(axis=0).tolist(),
            "mean": shapes.mean(axis=0).tolist(),
            "median": np.median(shapes, axis=0).tolist(),
        }
        if len(rows)
        else {},
        "voxel_info": {"hu_range": [w_lo, w_hi], "total_bbox_voxels": n, "filtered_bbox_voxels": n},
        "num_vois": len(rows),
        "num_vois_with_tumor": sum(1 for r in rows if r.get("lesions")),
        "num_lesions": sum(len(r.get("lesions") or []) for r in rows),
        "lesion_labels": lesion_labels,
        "target_spacing": list(spacing) if spacing is not None else None,
        "assumptions": {
            "voi_files_are_side_specific": True,
            "coordinates_reference": "voi_local",
            "foreground": "the VOI's labels in each crop",
        },
        "notes": [
            "foreground_intensity: statistics over the full voxel range (informational).",
            "windowed_intensity: after clipping to the HU window (the loader's normalization).",
        ],
    }


def shared_spacing(rows: Sequence[dict[str, Any]]) -> list[float] | None:
    """The voxel size every crop has, if they all have the same one."""
    sizes = {tuple(r["spacing"]) for r in rows if r.get("spacing")}
    return [float(v) for v in next(iter(sizes))] if len(sizes) == 1 else None
