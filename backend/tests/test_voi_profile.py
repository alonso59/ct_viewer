"""ADR-0061: the training contract of a `voi.extract` run (`plugins/voi/profile.py`)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import pytest
from plugins.voi import lesions, profile
from plugins.voi import task as voi_task


def lesion(
    volume_mm3: float, box_mm: tuple[float, float, float] = (10, 10, 10), n: int = 1
) -> dict[str, Any]:
    return {
        "lesion": n,
        "label": 2,
        "label_value": 2,
        "volume_vox": int(volume_mm3),
        "volume_mm3": volume_mm3,
        "max_extent_mm": max(box_mm),
        "bbox_size_mm": list(box_mm),
        "bbox_size_vox": [int(v) for v in box_mm],
        "centroid_vox": [5.0, 5.0, 5.0],
        "organ_contact_ratio": 0.5,
        "hu": {"mean": 30.0, "std": 5.0, "p5": 20.0, "p50": 30.0, "p95": 40.0},
    }


VOLUMES = [float(v) for v in range(100, 10_100, 100)]  # 100 lesions, 0.1 mL to 10 mL


def test_bins_budgets_and_priors_grow_with_lesion_size() -> None:
    prof, names = profile.build_profile([lesion(v) for v in VOLUMES], {}, [1.0, 1.0, 1.0])
    assert [b["name"] for b in prof["size_bins"]] == ["b0", "b1", "b2", "b3", "b4"]
    assert prof["size_bin_thresholds"] == {
        f"p{p}_0": pytest.approx(np.percentile(VOLUMES, p)) for p in (20, 50, 80, 95)
    }
    assert (
        prof["size_bins"][0]["label"] == "≤ 2.08 mL"
        and prof["size_bins"][-1]["label"] == "> 9.51 mL"
    )
    assert names[0] == "b0" and names[-1] == "b4" and len(names) == 100
    # The research defaults for five bins (tiny … huge), now keyed by the bins produced.
    assert list(prof["suggested_patch_budget_by_size_bin"].values()) == [2, 2, 3, 4, 5]
    priors = prof["suggested_patch_role_priors_by_size_bin"]
    assert priors["b0"] == {"center": 0.85, "border": 0.1, "context": 0.05}
    assert priors["b4"] == {"center": 0.3, "border": 0.4, "context": 0.3}
    assert all(sum(p.values()) == pytest.approx(1.0) for p in priors.values())
    assert prof["size_bin_counts"] == {"b0": 20, "b1": 30, "b2": 30, "b3": 15, "b4": 5}
    rec = prof["heuristic_patch_recommendations"]["b0"]
    assert rec["recommended_min_patch_extent"] == [34.0, 34.0, 34.0]
    assert rec["recommended_min_patch_vox"] == [34, 34, 34]
    assert prof["version"] == 2 and prof["settings_hash"].startswith("sha256:")


def test_other_bin_counts_scale_the_defaults() -> None:
    prof, _ = profile.build_profile([lesion(v) for v in VOLUMES], {"bin_percentiles": [50]}, None)
    assert list(prof["suggested_patch_budget_by_size_bin"].values()) == [2, 5]
    three, _ = profile.build_profile(
        [lesion(v) for v in VOLUMES], {"bin_percentiles": [33, 66]}, None
    )
    assert three["suggested_patch_role_priors_by_size_bin"]["b1"] == {
        "center": 0.5,
        "border": 0.3,
        "context": 0.2,
    }
    assert "recommended_min_patch_vox" not in three["heuristic_patch_recommendations"]["b0"]


def test_balancing_moves_bins_towards_uniform() -> None:
    found = [lesion(v) for v in VOLUMES]
    for alpha in (0.0, 0.5, 1.0):
        prof, _ = profile.build_profile(found, {"balancing_alpha": alpha}, None)
        emp, target = (
            prof["empirical_size_bin_probabilities"],
            prof["target_size_bin_probabilities"],
        )
        assert sum(target.values()) == pytest.approx(1.0)
        for k in emp:
            assert target[k] == pytest.approx((1 - alpha) * emp[k] + alpha / 5)


def test_given_budgets_and_priors_and_mismatches() -> None:
    found = [lesion(v) for v in VOLUMES]
    given = {
        "bin_percentiles": [50],
        "budget_by_bin": [1, 7],
        "role_priors_by_bin": [{"center": 2, "border": 1, "context": 1}, {"center": 1}],
    }
    prof, _ = profile.build_profile(found, given, None)
    assert prof["suggested_patch_budget_by_size_bin"] == {"b0": 1, "b1": 7}
    assert prof["suggested_patch_role_priors_by_size_bin"]["b0"] == {
        "center": 0.5,
        "border": 0.25,
        "context": 0.25,
    }
    assert prof["warnings"] == []
    # Repeated cuts merge bins: a list for the asked number of bins no longer fits.
    same = [lesion(1000.0) for _ in range(10)] + [lesion(5000.0)]
    merged, _ = profile.build_profile(
        same, {"bin_percentiles": [20, 50], "budget_by_bin": [1, 2, 3]}, None
    )
    assert len(merged["size_bins"]) == 2
    assert merged["suggested_patch_budget_by_size_bin"] == {"b0": 2, "b1": 5}
    assert merged["warnings"] == [
        "budget_by_bin has 3 values for 2 size bins; the defaults were used"
    ]


def test_profile_is_deterministic_and_validated() -> None:
    found = [lesion(v, (v / 100, 10, 5)) for v in VOLUMES]
    assert profile.build_profile(found, {}, None) == profile.build_profile(found, {}, None)
    assert profile.build_profile([], {}, None)[0]["num_lesions"] == 0
    with pytest.raises(ValueError, match="low < high"):
        profile.profile_settings({"hu_window": [300, -100]})
    with pytest.raises(ValueError, match="between 0 and 100"):
        profile.profile_settings({"bin_percentiles": [0, 50]})


def test_fingerprint_statistics_equal_numpy_on_whole_hu_values() -> None:
    rng = np.random.default_rng(1)
    vois = [np.rint(rng.normal(40, 60, (12, 12, 8))), np.rint(rng.normal(180, 90, (10, 10, 6)))]
    hists = [lesions.hu_histogram(v, np.ones(v.shape, bool)) for v in vois]
    rows = [{"shape": list(v.shape), "lesions": [], "lesion_labels": ["tumor"]} for v in vois]
    fp = profile.build_fingerprint(rows, hists, {"hu_window": [-100, 300]}, [1.0, 1.0, 1.0])
    pooled = np.concatenate([v.ravel() for v in vois])
    for key, values in (
        ("foreground_intensity", pooled),
        ("windowed_intensity", np.clip(pooled, -100, 300)),
    ):
        got = fp[key]["channel_0"]
        assert got["mean"] == pytest.approx(values.mean()) and got["std"] == pytest.approx(
            values.std()
        )
        assert (got["min"], got["max"]) == (values.min(), values.max())
        for k, q in (
            ("p0_5", 0.5),
            ("p5", 5),
            ("p25", 25),
            ("median", 50),
            ("p95", 95),
            ("p99_5", 99.5),
        ):
            assert got[k] == pytest.approx(np.percentile(values, q)), k
    assert fp["normalization"] == {
        "method": "window_rescale",
        "window_min": -100.0,
        "window_max": 300.0,
        "output_min": -1.0,
        "output_max": 1.0,
    }
    assert fp["voxel_info"]["total_bbox_voxels"] == pooled.size and fp["num_vois"] == 2
    assert fp["voi_shape_statistics"]["max"] == [12, 12, 8] and fp["target_spacing"] == [
        1.0,
        1.0,
        1.0,
    ]


def catalog_row(item: str, side: str, found: list[dict[str, Any]], hist: str) -> dict[str, Any]:
    return {
        "item_id": item,
        "case_id": item.split(".")[0],
        "scan_idx": "01",
        "phase": "NP",
        "side": side,
        "candidate": side,
        "image": f"c/{item}_{side}_image.nii.gz",
        "mask": f"c/{item}_{side}_mask.nii.gz",
        "shape": [64, 64, 48],
        "spacing": [1.0, 1.0, 1.0],
        "hu_histogram": hist,
        "lesion_labels": ["tumor"],
        "lesions": found,
    }


def finish(tmp_path: Path, lines: list[dict[str, Any]]) -> tuple[Path, Any]:
    out, job_dir = tmp_path / "out", tmp_path / "job"
    out.mkdir(parents=True, exist_ok=True)
    job_dir.mkdir(exist_ok=True)
    (out / "h.json").write_text(
        json.dumps(lesions.hu_histogram(np.arange(-50.0, 150.0), np.ones(200, bool)))
    )
    (out / voi_task.CATALOG).write_text("".join(json.dumps(r) + "\n" for r in lines))
    tables: list[tuple[str, Path, dict[str, Any]]] = []
    job = SimpleNamespace(
        output_dir=out, dir=job_dir, settings={}, table=lambda *a: tables.append(a)
    )
    voi_task.training_files(job)  # type: ignore[arg-type]
    return out, tables


def test_training_files_come_from_the_whole_catalog(tmp_path: Path) -> None:
    rows = [
        catalog_row("a.01.complete.-", "L", [lesion(2000.0)], "h.json"),
        catalog_row("a.01.complete.-", "R", [lesion(9000.0), lesion(300.0, n=2)], "h.json"),
        catalog_row("b.01.complete.-", "L", [], "h.json"),
    ]
    one_pass, tables = finish(tmp_path / "one", rows)
    # A resumed run: an earlier attempt's rows, then the same item extracted again.
    stale = catalog_row("a.01.complete.-", "R", [lesion(1.0)], "h.json")
    resumed, _ = finish(tmp_path / "two", [rows[0], stale, rows[2], rows[1]])
    for f in ("lesion_catalog.jsonl", "sampling_profile.json", "dataset_fingerprint.json"):
        assert (one_pass / f).read_text() == (resumed / f).read_text(), f
    cat = [json.loads(x) for x in (one_pass / "lesion_catalog.jsonl").read_text().splitlines()]
    assert len(cat) == 3 and all(
        {"mask_path", "centroid_vox", "bbox_size_vox", "size_bin"} <= set(c) for c in cat
    )
    assert {c["mask_path"] for c in cat} == {r["mask"] for r in rows[:2]}
    fp = json.loads((one_pass / "dataset_fingerprint.json").read_text())
    assert fp["num_vois"] == 3 and fp["num_vois_with_tumor"] == 2 and fp["num_lesions"] == 3
    assert fp["voxel_info"]["total_bbox_voxels"] == 600
    [(name, path, spec)] = tables
    assert (
        name == "lesions"
        and spec["roles"] == {"volume": "volume_ml"}
        and spec["grain"] == "instance"
    )
    t = pq.read_table(path).to_pylist()
    vol = {(r["side"], r["instance"]): r["value"] for r in t if r["name"] == "volume_ml"}
    # One numbering per scan over both sides, largest first.
    assert vol == {("R", "1"): 9.0, ("L", "2"): 2.0, ("R", "3"): 0.3}
    assert {r["name"] for r in t} >= {"hu_mean", "organ_contact_ratio", "lesions_in_voi"}


def test_no_lesions_writes_the_files_but_no_table(tmp_path: Path) -> None:
    out, tables = finish(tmp_path, [catalog_row("b.01.complete.-", "L", [], "h.json")])
    assert json.loads((out / "sampling_profile.json").read_text())["num_lesions"] == 0
    assert (out / "lesion_catalog.jsonl").read_text() == "" and tables == []
