"""VOI plugin routes (candidates, previews, regions) and the `voi.extract` builtin task."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient

from tests.test_contract import assert_problem
from tests.test_tasks import API, ITEMS, finish, with_derived
from tests.test_tasks import env as env
from tests.test_tasks import plugins_root as plugins_root
from tests.test_tasks import proj as proj

VOI = f"{API}/plugins/voi"


def test_regions_list_presets(env: TestClient) -> None:
    rows = {r["id"]: r for r in env.get(f"{VOI}/regions").json()}
    assert rows["kidney"]["lateral"] and rows["lung"]["lateral"]
    assert not rows["liver"]["lateral"]
    assert rows["kidney"]["labels"] == ["kidney", "kidney_left", "kidney_right", "tumor", "cyst"]


def test_candidates_preview_and_cache(env: TestClient, proj: str) -> None:
    url = f"{VOI}/projects/{proj}/items/{ITEMS[0]}/candidates"
    r = env.post(url, json={"region": "kidney", "min_size_mm": [40, 40, 40]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lateral"] and body["seg_id"] == "imported" and body["missing_labels"] == []
    assert len(body["candidates"]) == 1
    cand = body["candidates"][0]
    assert cand["side"] in ("L", "R") and cand["volume_ml"] > 0
    axes = zip(cand["crop_size_mm"], body["shape"], body["spacing_mm"], strict=True)
    assert all(size >= 40 or size >= n * sp for size, n, sp in axes)  # or the whole image

    p = env.get(f"{VOI}/projects/{proj}/previews/{cand['preview']}")
    assert p.status_code == 200 and p.headers["content-type"] == "image/webp"
    assert p.content[8:12] == b"WEBP"

    # margin changes only the crop: same tight box, cached analysis
    tight_only = {"region": "kidney", "margin_mm": 0, "min_size_mm": [0, 0, 0]}
    again = env.post(url, json=tight_only).json()
    c2 = again["candidates"][0]
    assert c2["tight"] == cand["tight"] and c2["crop"] == c2["tight"]


def test_candidates_report_missing_labels(env: TestClient, proj: str) -> None:
    url = f"{VOI}/projects/{proj}/items/{ITEMS[0]}/candidates"
    body = env.post(url, json={"region": "lung"}).json()
    assert body["candidates"] == [] and "lung" in body["missing_labels"]
    assert_problem(env.post(url, json={"region": "custom"}), "validation")
    assert_problem(env.get(f"{VOI}/projects/{proj}/previews/nope"), "not-found")


def test_extract_task_writes_vois_and_catalog(env: TestClient, proj: str, tmp_path: Path) -> None:
    with_derived(env, proj, tmp_path)
    r = env.post(
        f"{API}/projects/{proj}/task-runs",
        json={
            "task_id": "voi.extract",
            "settings": {
                "region": "kidney",
                "resample_mm": 0,
                "min_size_mm": [30, 30, 30],
                "overrides": [{"item_id": ITEMS[1], "exclude": ["L", "R"]}],
            },
            "selection": {"item_ids": ITEMS[:2], "seg_id": "imported"},
        },
        headers={"X-Reviewer": "T"},
    )
    assert r.status_code == 202, r.text
    run = finish(env, proj, r.json())
    assert run["status"] == "completed", run
    assert run["counts"]["ok"] == 1 and run["counts"]["skipped"] == 1
    out = Path(run["output_dir"])
    rows = [json.loads(line) for line in (out / "voi_catalog.jsonl").read_text().splitlines()]
    assert [row["item_id"] for row in rows] == [ITEMS[0]]
    assert rows[0]["orientation"] == "RAS" and (out / rows[0]["image"]).is_file()
    assert (out / rows[0]["mask"]).is_file()
    outputs = env.get(f"{API}/projects/{proj}/task-runs/{run['run_id']}/outputs").json()
    kinds = sorted(o["kind"] for o in outputs)
    assert kinds.count("image") == 1 and kinds.count("sidecar") == 2  # the mask, the histogram


def test_extract_measures_the_lesions_of_each_crop(
    env: TestClient, proj: str, tmp_path: Path
) -> None:
    with_derived(env, proj, tmp_path)
    labels = {e["name"]: e["value"] for e in env.get(f"{API}/projects/{proj}").json()["label_map"]}

    def extract(**settings: object) -> tuple[Path, list[dict[str, Any]]]:
        r = env.post(
            f"{API}/projects/{proj}/task-runs",
            json={
                "task_id": "voi.extract",
                "settings": {"region": "kidney", "resample_mm": 1.0, **settings},
                "selection": {"item_ids": ITEMS[:1], "seg_id": "imported"},
            },
            headers={"X-Reviewer": "T"},
        )
        assert r.status_code == 202, r.text
        run = finish(env, proj, r.json())
        assert run["status"] == "completed", run
        runs.append(run)
        out = Path(run["output_dir"])
        return out, [json.loads(x) for x in (out / "voi_catalog.jsonl").read_text().splitlines()]

    runs: list[dict[str, Any]] = []
    out, rows = extract()
    [row] = [r for r in rows if r["lesions"]]  # the fixture's tumor is in one kidney
    assert row["lesion_labels"] == ["tumor"] and row["spacing"] == [1.0, 1.0, 1.0]
    [lesion] = row["lesions"]
    assert lesion["lesion"] == 1 and lesion["label"] == labels["tumor"]
    mask = np.asarray(nib.load(out / row["mask"]).dataobj)
    assert lesion["volume_vox"] == int((mask == lesion["label_value"]).sum())
    lo, hi = lesion["bbox_min_vox"], lesion["bbox_max_vox"]
    assert (mask[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]] == lesion["label_value"]).sum() == (
        lesion["volume_vox"]
    )
    assert lesion["organ_contact_ratio"] > 0.5 and set(lesion["hu"]) == {
        "mean",
        "std",
        "p5",
        "p50",
        "p95",
    }
    hist = json.loads((out / row["hu_histogram"]).read_text())
    assert hist["n"] == int(
        np.isin(mask, [labels["kidney"], labels["tumor"], labels["cyst"]]).sum()
    )
    # The same input gives the same measures and histogram bytes; measuring can be turned off.
    again, rows2 = extract()
    assert [r["lesions"] for r in rows2] == [r["lesions"] for r in rows]
    assert (again / row["hu_histogram"]).read_bytes() == (out / row["hu_histogram"]).read_bytes()
    _, off = extract(measure_lesions=False)
    assert all(r["lesions"] == [] and r["lesion_labels"] == [] for r in off)
    _, small = extract(min_lesion_voxels=10**5)
    assert [r["lesions_below_min"] for r in small if r["side"] == row["side"]] == [1]


def test_extract_writes_the_training_files_and_the_lesions_table(
    env: TestClient, proj: str, tmp_path: Path
) -> None:
    with_derived(env, proj, tmp_path)
    r = env.post(
        f"{API}/projects/{proj}/task-runs",
        json={
            "task_id": "voi.extract",
            "settings": {"region": "kidney", "resample_mm": 1.0, "bin_percentiles": [50]},
            "selection": {"item_ids": ITEMS, "seg_id": "imported"},
        },
        headers={"X-Reviewer": "T"},
    )
    assert r.status_code == 202, r.text
    run = finish(env, proj, r.json())
    assert run["status"] == "completed", run
    out = Path(run["output_dir"])
    catalog = [json.loads(x) for x in (out / "lesion_catalog.jsonl").read_text().splitlines()]
    assert len(catalog) == len(ITEMS)  # one tumor per fixture scan
    assert all((out / c["mask_path"]).is_file() and c["size_bin"] in ("b0", "b1") for c in catalog)
    prof = json.loads((out / "sampling_profile.json").read_text())
    assert prof["num_lesions"] == len(ITEMS) and prof["target_spacing"] == [1.0, 1.0, 1.0]
    assert prof["settings"]["bin_percentiles"] == [50] and len(prof["size_bins"]) == 2
    fp = json.loads((out / "dataset_fingerprint.json").read_text())
    assert fp["num_lesions"] == len(ITEMS) and fp["foreground_intensity"]["channel_0"]["mean"]
    tid = f"{run['run_id']}-lesions"
    assert {"kind": "table", "detail": tid} in [
        {"kind": o["kind"], "detail": o["detail"]} for o in run["outputs"]
    ]
    [table] = [t for t in env.get(f"{API}/projects/{proj}/tables").json() if t["table_id"] == tid]
    assert table["kind"] == "voi_lesions" and table["roles"] == {"volume": "volume_ml"}
    views = f"{API}/projects/{proj}/tables/{tid}/views"
    dist = env.post(f"{views}/feature-distribution", json={"feature": "volume_ml"})
    assert dist.status_code == 200, dist.text
    vol = {c["volume_mm3"] / 1000 for c in catalog}
    points = {round(p["value"], 6) for p in dist.json()["points"]}
    assert points == {round(v, 6) for v in vol}


def test_profiles_are_recomputed_saved_and_exported(
    env: TestClient, proj: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_derived(env, proj, tmp_path)
    r = env.post(
        f"{API}/projects/{proj}/task-runs",
        json={
            "task_id": "voi.extract",
            "settings": {"region": "kidney", "resample_mm": 1.0},
            "selection": {"item_ids": ITEMS, "seg_id": "imported"},
        },
        headers={"X-Reviewer": "T"},
    )
    run = finish(env, proj, r.json())
    base = f"{VOI}/projects/{proj}/runs/{run['run_id']}"
    results = env.get(f"{base}/results").json()
    assert (
        results["summary"]["n_lesions"] == len(ITEMS) == results["summary"]["n_vois_with_lesions"]
    )
    vois = [v for scan in results["scans"] for v in scan["vois"] if v["n_lesions"]]
    assert len(vois) == len(ITEMS) and all(v["largest_lesion_ml"] > 0 for v in vois)

    def no_volume(*_: object, **__: object) -> None:
        raise AssertionError("a profile must not read volumes")

    with monkeypatch.context() as m:
        m.setattr(nib, "load", no_volume)
        p = env.post(f"{base}/profile", json={"bin_percentiles": [50], "balancing_alpha": 1})
    assert p.status_code == 200, p.text
    prof = p.json()["profile"]
    assert len(prof["size_bins"]) == 2 and prof["settings"]["hu_window"] == [-100.0, 300.0]
    assert sum(prof["target_size_bin_probabilities"].values()) == pytest.approx(1.0)
    assert len(p.json()["lesion_volumes_mm3"]) == len(ITEMS)
    assert_problem(env.post(f"{base}/profile", json={"hu_window": [10, -10]}), "validation")
    assert_problem(env.post(f"{base}/profile", json={"nope": 1}), "validation")

    saved = env.put(
        f"{base}/profiles/balanced", json={"balancing_alpha": 1}, headers={"X-Reviewer": "Dr. P"}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["name"] == "balanced" and saved.json()["saved_by"] == "Dr. P"
    [row] = env.get(f"{base}/profiles").json()
    assert row["name"] == "balanced" and row["num_lesions"] == len(ITEMS)
    assert env.get(f"{base}/profiles/balanced/export").json() == saved.json()["profile"]
    own = env.get(f"{base}/profiles/run/export").json()
    assert own == json.loads((Path(run["output_dir"]) / "sampling_profile.json").read_text())
    assert own["balancing_alpha"] == 0.5 and saved.json()["profile"]["balancing_alpha"] == 1.0
    assert_problem(env.put(f"{base}/profiles/run", json={}), "validation")
    assert_problem(env.put(f"{base}/profiles/Bad%20Name", json={}), "validation")
    assert_problem(env.get(f"{base}/profiles/other/export"), "not-found")


def test_an_invalid_profile_fails_before_any_crop(
    env: TestClient, proj: str, tmp_path: Path
) -> None:
    with_derived(env, proj, tmp_path)
    r = env.post(
        f"{API}/projects/{proj}/task-runs",
        json={
            "task_id": "voi.extract",
            "settings": {"region": "kidney", "hu_window": [300, -100]},
            "selection": {"item_ids": ITEMS[:1], "seg_id": "imported"},
        },
        headers={"X-Reviewer": "T"},
    )
    assert r.status_code == 202, r.text
    run = finish(env, proj, r.json())
    assert run["status"] == "failed" and "low < high" in (run["error"] or ""), run


def test_region_needs_its_organ_label(env: TestClient, proj: str) -> None:
    """A kidney project has `tumor` but no `liver`: the liver preset must not box the tumor."""
    url = f"{VOI}/projects/{proj}/items/{ITEMS[0]}/candidates"
    body = env.post(url, json={"region": "liver"}).json()
    assert body["candidates"] == [] and body["missing_labels"] == ["liver"]
    chosen = env.post(url, json={"region": "liver", "labels": ["tumor"]}).json()
    assert len(chosen["candidates"]) == 1  # explicit labels are the user's choice


def test_run_results_list_the_written_vois(env: TestClient, proj: str, tmp_path: Path) -> None:
    with_derived(env, proj, tmp_path)
    r = env.post(
        f"{API}/projects/{proj}/task-runs",
        json={
            "task_id": "voi.extract",
            "settings": {"region": "kidney", "resample_mm": 0, "min_size_mm": [20, 20, 20]},
            "selection": {"item_ids": ITEMS[:1], "seg_id": "imported"},
        },
        headers={"X-Reviewer": "T"},
    )
    run = finish(env, proj, r.json())
    body = env.get(f"{VOI}/projects/{proj}/runs/{run['run_id']}/results").json()
    assert body["status"] == "completed" and body["reviewer"] == "T"
    assert body["output_dir"] == run["output_dir"] and body["view"] == "scans"
    assert body["summary"]["n_scans"] == 1 and body["summary"]["n_vois"] == 1
    assert body["total"] == 1 and [s["item_id"] for s in body["scans"]] == [ITEMS[0]]
    res = body["scans"][0]["vois"][0]
    assert res["item_id"] == ITEMS[0] and res["side"] in ("L", "R") and res["volume_ml"] > 0
    cases = env.get(f"{VOI}/projects/{proj}/runs/{run['run_id']}/results?view=cases").json()
    assert cases["scans"] == [] and [c["n_vois"] for c in cases["cases"]] == [1]
    nothing = env.get(f"{VOI}/projects/{proj}/runs/{run['run_id']}/results?q=zzz").json()
    assert (
        nothing["total"] == 0 and nothing["summary"]["n_vois"] == 1
    )  # the summary ignores filters
    assert (
        env.get(f"{VOI}/projects/{proj}/runs/{run['run_id']}/results?limit=51").status_code == 422
    )
    p = env.get(f"{VOI}/projects/{proj}/runs/{run['run_id']}/results/0/preview")
    assert p.status_code == 200 and p.content[8:12] == b"WEBP"
    assert_problem(
        env.get(f"{VOI}/projects/{proj}/runs/{run['run_id']}/results/5/preview"), "not-found"
    )


def test_preflight_skips_vois_and_scans_that_already_have_them(env: TestClient, proj: str) -> None:
    url = f"{API}/projects/{proj}/tasks/voi.extract/preflight"
    pre = env.post(url, json={"selection": {"seg_id": "imported"}, "settings": {}}).json()
    assert pre["missing"]["voi item, needs complete"] == 10  # a VOI crop is not cropped again
    assert pre["missing"]["already has VOIs"] == 6  # nor is a scan whose VOIs exist
    ready = set(pre["ready_item_ids"])
    assert ready and all(i.endswith(".complete.-") for i in ready)
    again = env.post(
        url, json={"selection": {"seg_id": "imported"}, "settings": {"skip_existing": False}}
    ).json()
    assert "already has VOIs" not in again["missing"]  # extracting them again is allowed
    assert again["n_ready"] == pre["n_ready"] + 6
    assert again["missing"]["voi item, needs complete"] == 10  # crops are never cropped
