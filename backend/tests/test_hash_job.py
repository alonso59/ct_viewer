"""API-15 full-hash job (IMP-09, BE-06): worker hashing, results in `index/hashes.json`, R1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ingest.hashing import HASHES
from tests.test_contract import assert_problem
from tests.test_e2e_import import import_root, sha_tree, wait_job
from tests.test_imaging import forbid_source_writes

API = "/api/v1"
ITEM = "case_00001.01.complete.-"


def _project(client: TestClient, data_root: Path) -> str:
    pid: str = client.post(f"{API}/projects", json={"name": "hash", "packs": ["ccrcc"]}).json()[
        "project_id"
    ]
    import_root(client, pid, data_root)
    return pid


def test_hash_job_hashes_every_source_file_read_only(
    client: TestClient, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = _project(client, data_root)
    before = sha_tree(data_root)
    forbid_source_writes(monkeypatch, data_root)  # BE-03: any write-mode open fails the job

    r = client.post(f"{API}/projects/{pid}/hash-jobs")
    assert r.status_code == 202, r.text
    started = r.json()
    assert started["n_files"] > 0 and started["n_skipped"] == 0
    job = wait_job(client, started["job_id"])
    assert (job["status"], job["kind"], job["done"]) == ("succeeded", "hash", started["n_files"])

    # progress + completion on the event bus like other jobs (API-40)
    bus = client.app.state.ctx.bus  # type: ignore[attr-defined]
    events = [(e.event, e.data) for e in bus._buffers[pid]]
    mine = [(ev, d) for ev, d in events if d.get("job_id") == job["job_id"]]
    assert {ev for ev, _ in mine} == {"job.progress", "job.finished"}
    assert mine[-1] == ("job.finished", {**mine[-1][1], "kind": "hash", "status": "succeeded"})

    pdir = client.app.state.ctx.workspace.project_dir(pid)  # type: ignore[attr-defined]
    stored = json.loads((pdir / "index" / HASHES).read_text())["files"]
    assert len(stored) == started["n_files"]
    item = client.get(f"{API}/projects/{pid}/items/{ITEM}").json()
    img = data_root / item["image"]["ref"].split(":", 1)[1]
    assert item["image"]["sha256"] == hashlib.sha256(img.read_bytes()).hexdigest()
    assert item["mask"]["sha256"] and stored[item["image"]["ref"]]["fp"] == item["image"]["fp"]
    case = client.get(f"{API}/projects/{pid}/cases/case_00001").json()
    assert all(i["image"]["sha256"] for s in case["scans"] for i in s["items"] if i["image"])
    # one fact, one place: items.jsonl never stores the hash
    assert '"sha256"' not in (pdir / "index" / "items.jsonl").read_text()

    again = client.post(f"{API}/projects/{pid}/hash-jobs", json={}).json()
    assert (again["n_files"], again["n_skipped"]) == (0, started["n_files"])
    assert wait_job(client, again["job_id"])["status"] == "succeeded"
    forced = client.post(f"{API}/projects/{pid}/hash-jobs", json={"force": True}).json()
    assert forced["n_files"] == started["n_files"]
    assert wait_job(client, forced["job_id"])["status"] == "succeeded"

    assert sha_tree(data_root) == before  # R1 / TST-07


def test_changed_file_loses_its_hash_until_reindexed(client: TestClient, data_root: Path) -> None:
    pid = _project(client, data_root)
    wait_job(client, client.post(f"{API}/projects/{pid}/hash-jobs").json()["job_id"])
    item = client.get(f"{API}/projects/{pid}/items/{ITEM}").json()
    img = data_root / item["image"]["ref"].split(":", 1)[1]
    img.write_bytes(img.read_bytes() + b"\0")  # the test's own copy changes upstream
    r = client.post(f"{API}/projects/{pid}/hash-jobs", json={"force": True}).json()
    wait_job(client, r["job_id"])
    after = client.get(f"{API}/projects/{pid}/items/{ITEM}").json()
    assert after["image"]["sha256"] is None  # hash is for another fingerprint than the index
    assert after["mask"]["sha256"]


def test_hash_job_errors(client: TestClient, data_root: Path) -> None:
    assert_problem(client.post(f"{API}/projects/01JAAAAAAAAAAAAAAAAAAAAAAA/hash-jobs"), "not-found")
    pid = client.post(f"{API}/projects", json={"name": "empty", "packs": ["ccrcc"]}).json()[
        "project_id"
    ]
    empty = client.post(f"{API}/projects/{pid}/hash-jobs").json()
    assert empty["n_files"] == 0
    assert wait_job(client, empty["job_id"])["status"] == "succeeded"
    assert_problem(
        client.post(f"{API}/projects/{pid}/hash-jobs", json={"force": 1.5}), "validation"
    )
