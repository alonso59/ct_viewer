"""VOI plugin routes (candidates, previews, regions) and the `voi.extract` builtin task."""

from __future__ import annotations

import json
from pathlib import Path

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
    assert kinds.count("image") == 1 and kinds.count("sidecar") == 1


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
