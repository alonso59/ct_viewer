"""Task framework (TSK-01..12, API-42..47): manifests, schema validation, preflight, builtin
runtime on the fake `segment.threshold` plugin, mask registration as a segmentation set,
run record, cancel/resume, derived ledger. Inline jobs (threads)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.tasks.models import TaskManifest
from app.tasks.registry import manifest_hash, parse_manifest
from app.tasks.schema import normalize
from tests.test_api_ingest import ctx_of, do_import, wait
from tests.test_contract import assert_problem
from tests.test_format_v2 import derived_settings
from tests.test_projects_api import patch_project
from tools.make_fixtures import DATASET

API = "/api/v1"
REPO = Path(__file__).resolve().parents[2]
THRESHOLD = REPO / "plugins" / "threshold" / "task.json"
ITEMS = [f"case_{n:05d}.01.complete.-" for n in (1, 2, 3)]


def builtin_threshold() -> TaskManifest:
    """The CI plugin's manifest with the builtin runtime (TST-14 runs it under both)."""
    m, _ = parse_manifest(THRESHOLD)
    return m.model_copy(
        update={
            "runtime": m.runtime.model_copy(
                update={"type": "builtin", "entry": "plugins.threshold.run:run", "command": None}
            )
        }
    )


@pytest.fixture
def plugins_root(tmp_path: Path) -> Path:
    root = tmp_path / "plugins_root"
    (root / "bad").mkdir(parents=True)
    (root / "bad" / "task.json").write_text("{not json")
    (root / "builtin").mkdir()
    (root / "builtin" / "task.json").write_text(
        json.dumps({**json.loads(THRESHOLD.read_text()), "id": "x.builtin",
                    "runtime": {"type": "builtin", "entry": "a:b"}})
    )  # fmt: skip
    (root / "threshold").symlink_to(THRESHOLD.parent)
    return root


@pytest.fixture
def env(tmp_path: Path, fixtures_copy: Path, plugins_root: Path) -> Iterator[TestClient]:
    derived = tmp_path / "derived"
    derived.mkdir()
    s = derived_settings(tmp_path, fixtures_copy / DATASET, derived)
    s.plugins_root = plugins_root
    with TestClient(create_app(s, inline_jobs=True)) as c:
        reg = ctx_of(c).registry
        reg.tasks.pop("segment.threshold")
        m = builtin_threshold()
        reg.add(m, manifest_hash(m.model_dump_json().encode()), "builtin")
        yield c


@pytest.fixture
def proj(env: TestClient, data_root: Path, tmp_path: Path) -> str:
    pid = str(
        env.post(f"{API}/projects", json={"name": "t", "packs": ["ccrcc"]}).json()["project_id"]
    )
    do_import(env, pid, data_root)
    return pid


def with_derived(c: TestClient, pid: str, tmp_path: Path) -> Path:
    d = tmp_path / "derived"
    r = c.put(f"{API}/projects/{pid}/roots/DERIVED", json={"path": str(d), "role": "derived"})
    assert r.status_code == 200, r.text
    return d


def run_body(**settings: Any) -> dict[str, Any]:
    return {
        "task_id": "segment.threshold",
        "settings": {"threshold": 100, **settings},
        "selection": {"item_ids": ITEMS},
    }


def finish(c: TestClient, pid: str, started: dict[str, Any]) -> dict[str, Any]:
    wait(c, started["job_id"])
    return dict(c.get(f"{API}/projects/{pid}/task-runs/{started['run_id']}").json())


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# -- manifests (TSK-01/02, API-42/43) -----------------------------------------------------


def test_list_tasks_with_invalid_manifests(env: TestClient) -> None:
    body = env.get(f"{API}/tasks").json()
    ids = {t["manifest"]["id"]: t for t in body["tasks"]}
    assert "radiomics.pyradiomics" in ids and "segment.threshold" in ids
    rad = ids["radiomics.pyradiomics"]
    assert rad["source"] == "builtin" and rad["settings_schema_url"] == "/api/v1/radiomics/schema"
    errors = {Path(i["path"]).parent.name: i["error"] for i in body["invalid"]}
    assert "not JSON" in errors["bad"]
    assert "external runtime" in errors["builtin"]
    assert body["runners"] == []
    assert_problem(env.get(f"{API}/tasks/nope.task"), "not-found")


def test_external_manifest_from_plugins_root(tmp_path: Path, plugins_root: Path) -> None:
    s = derived_settings(tmp_path, tmp_path, None)
    s.plugins_root = plugins_root
    with TestClient(create_app(s, inline_jobs=True)) as c:
        t = c.get(f"{API}/tasks/segment.threshold").json()
        assert t["source"] == "plugins_root" and t["manifest"]["runtime"]["type"] == "external"
        assert t["runner_online"] is False and t["manifest"]["test_only"] is True


def test_manifest_rejects_unknown_keys_and_bad_schema(tmp_path: Path) -> None:
    raw = json.loads(THRESHOLD.read_text())
    p = tmp_path / "task.json"
    p.write_text(json.dumps({**raw, "typo": 1}))
    with pytest.raises(ValueError, match="typo"):
        parse_manifest(p)
    p.write_text(json.dumps({**raw, "settings_schema": {"type": "tuple"}}))
    with pytest.raises(ValueError, match="type must be"):
        parse_manifest(p)


def test_settings_schema_subset() -> None:
    schema = json.loads(THRESHOLD.read_text())["settings_schema"]
    norm, issues = normalize(schema, {}, {})
    assert norm == {"threshold": 0, "label": 1, "delay_s": 0} and issues == []
    _, issues = normalize(schema, {}, {"label": 0, "threshold": "x", "nope": 1, "seg_id": "A!"})
    rules = {(tuple(i.loc), i.rule) for i in issues}
    assert rules == {
        (("label",), "range"), (("threshold",), "type"), (("nope",), "unknown"),
        (("seg_id",), "pattern"),
    }  # fmt: skip
    norm, issues = normalize(
        {"type": "object", "properties": {"n": {"type": "integer"}}}, {}, {"n": 2.0}
    )
    assert norm == {"n": 2} and issues == []


def test_validate_endpoint(env: TestClient) -> None:
    ok = env.post(f"{API}/tasks/segment.threshold/validate", json={"settings": {}}).json()
    assert ok["ok"] and ok["settings"]["label"] == 1 and ok["settings_hash"].startswith("sha256:")
    bad = env.post(
        f"{API}/tasks/segment.threshold/validate", json={"settings": {"label": 999}}
    ).json()
    assert not bad["ok"] and bad["settings_hash"] is None and bad["issues"][0]["loc"] == ["label"]


# -- preflight + estimate (TSK-04/05, API-44) -----------------------------------------------


def test_preflight_and_suggestions(env: TestClient, proj: str) -> None:
    reg = ctx_of(env).registry
    reads = TaskManifest.model_validate(
        {
            "id": "test.reads-tumor", "version": "1", "title": "t", "kind": "features",
            "input": "items", "outputs": ["features"], "requires": {"seg": {"labels": ["tumor"]}},
            "runtime": {"type": "builtin", "entry": "plugins.threshold.run:run"},
        }
    )  # fmt: skip
    seg = reads.model_copy(update={"id": "test.segmenter", "outputs": ["masks"], "requires": {}})
    reg.add(reads, "sha256:x", "builtin")
    reg.add(seg, "sha256:y", "builtin")
    r = env.post(f"{API}/projects/{proj}/tasks/test.reads-tumor/preflight", json={})
    assert r.status_code == 200, r.text
    pre = r.json()
    assert pre["n_selected"] > pre["n_ready"] > 0
    assert set(pre["missing"]) <= {"no image", "no mask in imported", "no tumor label in imported"}
    assert "no mask in imported" in pre["missing"]
    assert {s["task_id"] for s in pre["suggestions"]} == {"test.segmenter"}  # test_only hidden
    thr = env.post(
        f"{API}/projects/{proj}/tasks/segment.threshold/preflight",
        json={"selection": {"item_ids": ITEMS}},
    ).json()
    assert thr["n_ready"] == 3 and thr["derived_root_required"] is True
    assert_problem(
        env.post(
            f"{API}/projects/{proj}/tasks/test.reads-tumor/preflight",
            json={"selection": {"seg_id": "nope"}},
        ),
        "validation",
    )


def test_estimate_builtin_sample(env: TestClient, proj: str) -> None:
    body = {"selection": {"item_ids": ITEMS}, "settings": {"threshold": 100}}
    est = env.post(f"{API}/projects/{proj}/tasks/segment.threshold/estimate", json=body).json()
    assert est["basis"] == "sample" and est["n_units"] == 3
    assert est["seconds_per_item"] is not None and est["sample_errors"] == []
    assert est["output_bytes"] and est["output_bytes"] > 0
    scratch = ctx_of(env).settings.workspace_root / ".scratch" / "estimates"
    assert not any(scratch.iterdir())  # sample outputs are disposable


# -- builtin runs (TSK-06..10, TST-14 builtin half) -----------------------------------------


def test_run_requires_derived_root(env: TestClient, proj: str) -> None:
    r = env.post(f"{API}/projects/{proj}/task-runs", json=run_body())
    assert_problem(r, "derived-root-required")
    assert r.json()["actions"] == ["choose_derived_root"]


def test_builtin_run_registers_segmentation_set(
    env: TestClient, proj: str, tmp_path: Path, data_root: Path
) -> None:
    derived = with_derived(env, proj, tmp_path)
    before = tree_hashes(data_root)
    r = env.post(f"{API}/projects/{proj}/task-runs", json=run_body(), headers={"X-Reviewer": "T"})
    assert r.status_code == 202, r.text
    run = finish(env, proj, r.json())
    assert run["status"] == "completed", run
    assert run["counts"] == {"items": 3, "ok": 3, "failed": 0, "skipped": 0}
    rid = run["run_id"]
    seg_id = f"threshold-{rid[:8].lower()}"
    # TSK-10 run record
    assert run["task"]["id"] == "segment.threshold" and run["task"]["version"] == "0.1.0"
    assert run["settings"]["threshold"] == 100 and run["settings_hash"].startswith("sha256:")
    assert run["reviewer"] == "T" and run["runtime"] == "builtin" and run["attempts"] == 1
    assert [i["item_id"] for i in run["inputs"]] == ITEMS and run["inputs"][0]["image_fp"]
    assert run["versions"]["segment.threshold"] == "0.1.0" and "numpy" in run["versions"]
    out_dir = Path(run["output_dir"])
    assert out_dir == derived.resolve() / proj / "segment.threshold" / "runs" / rid
    # outputs only inside the run's output_dir (ADR-0014); sources untouched (R1)
    assert sorted(p.name for p in derived.rglob("*") if p.is_file()) == sorted(
        f"{i}.nii.gz" for i in ITEMS
    )
    assert all(out_dir in p.parents for p in derived.rglob("*.nii.gz"))
    assert tree_hashes(data_root) == before
    # segmentation set (ADR-0015) + label mapping by name (unmatched → label_{value})
    sets = {s["seg_id"]: s for s in env.get(f"{API}/projects/{proj}/segmentations").json()}
    s = sets[seg_id]
    assert s["kind"] == "task" and s["producer"]["run_id"] == rid and s["n_items"] == 3
    assert s["unmatched"] == [1] and s["label_mapping"] == {"1": 4}
    labels = {e["value"]: e["name"] for e in env.get(f"{API}/projects/{proj}").json()["label_map"]}
    assert labels[4] == "foreground"
    item = env.get(f"{API}/projects/{proj}/items/{ITEMS[0]}").json()
    assert (
        item["masks"][seg_id]["ref"]
        == f"DERIVED:{proj}/segment.threshold/runs/{rid}/{ITEMS[0]}.nii.gz"
    )
    assert item["mask"] == item["masks"]["imported"]  # default_seg unchanged
    mask = env.get(f"{API}/projects/{proj}/items/{ITEMS[0]}/mask", params={"seg": seg_id})
    assert mask.status_code == 200 and mask.content == (out_dir / f"{ITEMS[0]}.nii.gz").read_bytes()
    # default_seg switches the deprecated alias
    assert patch_project(env, proj, {"default_seg": seg_id}).status_code == 200
    item = env.get(f"{API}/projects/{proj}/items/{ITEMS[0]}").json()
    assert item["mask"] == item["masks"][seg_id]
    # outputs + ledger
    outs = env.get(f"{API}/projects/{proj}/task-runs/{rid}/outputs").json()
    assert {o["kind"] for o in outs} == {"mask", "segmentation_set"}
    pdir = ctx_of(env).workspace.project_dir(proj)
    ledger = [
        json.loads(line) for line in (pdir / "derived" / "runs.jsonl").read_text().splitlines()
    ]
    assert ledger[0]["run_id"] == rid and len(ledger[0]["outputs"]) == 3
    sha = hashlib.sha256((out_dir / f"{ITEMS[0]}.nii.gz").read_bytes()).hexdigest()
    assert sha in {o["sha256"] for o in ledger[0]["outputs"]}
    # a re-import (index rebuild) keeps the task set (the index is derived, PRJ-10)
    do_import(env, proj, data_root)
    item = env.get(f"{API}/projects/{proj}/items/{ITEMS[0]}").json()
    assert seg_id in item["masks"]
    assert env.get(f"{API}/projects/{proj}/task-runs").json()[0]["run_id"] == rid
    assert env.get(f"{API}/projects/{proj}/task-runs/{rid}/errors").json() == []
    scratch = ctx_of(env).settings.workspace_root / ".scratch" / "jobs"
    assert not scratch.exists() or not any(scratch.iterdir())


def test_explicit_seg_id_and_conflicts(env: TestClient, proj: str, tmp_path: Path) -> None:
    with_derived(env, proj, tmp_path)
    assert_problem(
        env.post(f"{API}/projects/{proj}/task-runs", json=run_body(seg_id="imported")),
        "validation",
    )
    r = env.post(f"{API}/projects/{proj}/task-runs", json=run_body(seg_id="thr-a", delay_s=0.3))
    assert r.status_code == 202
    # TSK-12: one run per (project, task)
    assert_problem(env.post(f"{API}/projects/{proj}/task-runs", json=run_body()), "job-conflict")
    run = finish(env, proj, r.json())
    assert run["status"] == "completed"
    assert "thr-a" in {s["seg_id"] for s in env.get(f"{API}/projects/{proj}/segmentations").json()}


def test_cancel_then_resume_skips_ok_items(env: TestClient, proj: str, tmp_path: Path) -> None:
    with_derived(env, proj, tmp_path)
    r = env.post(f"{API}/projects/{proj}/task-runs", json=run_body(delay_s=0.6))
    started = r.json()
    rid = started["run_id"]
    pdir = ctx_of(env).workspace.project_dir(proj)
    deadline = time.monotonic() + 20
    while not (pdir / "tasks" / "runs" / rid / "items.jsonl").exists():
        assert time.monotonic() < deadline
        time.sleep(0.05)
    run = env.post(f"{API}/projects/{proj}/task-runs/{rid}/cancel").json()
    assert run["status"] == "cancelled", run
    assert 1 <= run["counts"]["ok"] < 3
    ok_before = run["counts"]["ok"]
    r = env.post(f"{API}/projects/{proj}/task-runs/{rid}/resume")
    assert r.status_code == 202, r.text
    run = finish(env, proj, r.json())
    assert run["status"] == "completed" and run["counts"]["ok"] == 3 and run["attempts"] == 2
    lines = (pdir / "tasks" / "runs" / rid / "items.jsonl").read_text().splitlines()
    assert len(lines) == 3  # resumed attempt ran only the remaining items
    assert ok_before + (3 - ok_before) == 3
    assert_problem(env.post(f"{API}/projects/{proj}/task-runs/{rid}/resume"), "job-conflict")


def test_failed_items_do_not_stop_the_run(env: TestClient, proj: str, tmp_path: Path) -> None:
    with_derived(env, proj, tmp_path)
    idx = ctx_of(env).index.load(proj)
    img = ctx_of(env).workspace.resolver(proj).resolve(idx.by_id[ITEMS[1]].image.ref)  # type: ignore[union-attr]
    os.chmod(img, 0)  # unreadable for the task only
    try:
        run = finish(
            env, proj, env.post(f"{API}/projects/{proj}/task-runs", json=run_body()).json()
        )
    finally:
        os.chmod(img, 0o644)
    assert run["status"] == "completed_with_errors"
    assert run["counts"]["ok"] == 2 and run["counts"]["failed"] == 1
    errs = env.get(f"{API}/projects/{proj}/task-runs/{run['run_id']}/errors").json()
    assert [e["item_id"] for e in errs] == [ITEMS[1]] and errs[0]["status"] == "failed"


def test_unknown_run_and_items(env: TestClient, proj: str) -> None:
    assert_problem(
        env.get(f"{API}/projects/{proj}/task-runs/01JAAAAAAAAAAAAAAAAAAAAAAA"), "not-found"
    )
    body = {**run_body(), "selection": {"item_ids": ["nope.01.complete.-"]}}
    assert_problem(env.post(f"{API}/projects/{proj}/task-runs", json=body), "validation")


def test_radiomics_on_a_task_segmentation_set(env: TestClient, proj: str, tmp_path: Path) -> None:
    """RAD-05 / NFR-15: a run on a chosen `seg_id` records it; API-45 is an alias (RAD-13)."""
    pytest.importorskip("radiomics")
    # Inline jobs run units in threads; PyRadiomics' settings loader is not thread-safe
    # (production runs each unit in a worker process), so one unit at a time here.
    ctx_of(env).jobs.workers = 1
    with_derived(env, proj, tmp_path)
    seg = finish(
        env, proj, env.post(f"{API}/projects/{proj}/task-runs", json=run_body(seg_id="thr")).json()
    )
    assert seg["status"] == "completed"
    fg = next(
        e["value"]
        for e in env.get(f"{API}/projects/{proj}").json()["label_map"]
        if e["name"] == "foreground"
    )
    body = {
        "selection": {"item_ids": ITEMS[:2], "labels": [fg], "seg_id": "thr"},
        "settings": {"settings": {"binWidth": 25}},
    }
    r = env.post(f"{API}/projects/{proj}/radiomics/runs", json=body, headers={"X-Reviewer": "T"})
    assert r.status_code == 202, r.text
    wait(env, r.json()["job_id"])
    run = env.get(f"{API}/projects/{proj}/radiomics/runs/{r.json()['run_id']}").json()
    errs = env.get(f"{API}/projects/{proj}/radiomics/runs/{run['run_id']}/errors").json()
    assert run["status"] == "completed", errs
    assert run["selection"]["seg_id"] == "thr" and {i["seg_id"] for i in run["inputs"]} == {"thr"}
    idx = ctx_of(env).index.load(proj)
    assert run["inputs"][0]["mask_fp"] == idx.by_id[ITEMS[0]].masks["thr"].fp
    feats = env.get(
        f"{API}/projects/{proj}/radiomics/runs/{run['run_id']}/features", params={"format": "json"}
    ).json()
    assert feats["total"] > 0 and {row["label"] for row in feats["rows"]} == {fg}
    # the same run through the generic task endpoints (API-45..47 alias the radiomics service)
    alias = {
        "task_id": "radiomics.pyradiomics",
        "settings": {"settings": {"binWidth": 25}},
        "selection": body["selection"],
    }
    r = env.post(f"{API}/projects/{proj}/task-runs", json=alias, headers={"X-Reviewer": "T"})
    assert r.status_code == 202, r.text
    wait(env, r.json()["job_id"])
    t = env.get(f"{API}/projects/{proj}/task-runs/{r.json()['run_id']}").json()
    assert t["task"]["id"] == "radiomics.pyradiomics" and t["selection"]["seg_id"] == "thr"
    assert t["detail_url"].endswith(f"/radiomics/runs/{r.json()['run_id']}")
    assert {
        o["kind"] for o in env.get(f"{API}/projects/{proj}/task-runs/{t['run_id']}/outputs").json()
    } == {"features"}
    listed = {
        x["run_id"]: x["task"]["id"] for x in env.get(f"{API}/projects/{proj}/task-runs").json()
    }
    assert listed[t["run_id"]] == "radiomics.pyradiomics"
    assert_problem(
        env.post(
            f"{API}/projects/{proj}/radiomics/runs",
            json={**body, "selection": {**body["selection"], "seg_id": "nope"}},
            headers={"X-Reviewer": "T"},
        ),
        "validation",
    )


def test_curation_decisions_per_segmentation_set(
    env: TestClient, proj: str, tmp_path: Path
) -> None:
    """CURATION §Targets: mask targets carry `seg_id`; the state key is (item, target, seg_id)."""
    with_derived(env, proj, tmp_path)
    finish(
        env, proj, env.post(f"{API}/projects/{proj}/task-runs", json=run_body(seg_id="thr")).json()
    )
    who = {"X-Reviewer": "T"}
    base = {"item_id": ITEMS[0], "target": "seg"}
    r1 = env.post(
        f"{API}/projects/{proj}/curation/events", json={**base, "status": "accepted"}, headers=who
    )
    r2 = env.post(
        f"{API}/projects/{proj}/curation/events",
        json={**base, "status": "needs_major_correction", "seg_id": "thr"},
        headers=who,
    )
    assert r1.status_code == 201 and r1.json()["seg_id"] == "imported", r1.text
    assert r2.status_code == 201 and r2.json()["seg_id"] == "thr"
    state = env.get(f"{API}/projects/{proj}/curation/state").json()
    targets = next(i for i in state["items"] if i["item_id"] == ITEMS[0])["targets"]
    assert {(t["target"], t["seg_id"], t["status"]) for t in targets} == {
        ("seg", "imported", "accepted"),
        ("seg", "thr", "needs_major_correction"),
    }
    queue = env.get(f"{API}/projects/{proj}/curation/queue").json()
    row = next(q for q in queue if q["item_id"] == ITEMS[0])
    assert "/segment.threshold/runs/" in row["mask_path_abs"]  # the thr set's file
    bad = {**base, "status": "accepted", "seg_id": "nope"}
    assert_problem(
        env.post(f"{API}/projects/{proj}/curation/events", json=bad, headers=who), "validation"
    )
    side = {"item_id": ITEMS[0], "target": "side", "status": "accepted", "seg_id": "thr"}
    assert_problem(
        env.post(f"{API}/projects/{proj}/curation/events", json=side, headers=who), "validation"
    )
