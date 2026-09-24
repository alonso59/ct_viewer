"""TST-14 external half (TSK-06/07/11, BE-14): the fake `segment.threshold` plugin through the file
queue and the real host runner (`scripts/rw-runner.py`): `waiting_for_runner`, claim, progress,
mask registration, cancel (SIGTERM), resume, a crashing task, a lost runner, single claim."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.tasks import service as task_service
from tests.test_api_ingest import ctx_of, do_import, wait
from tools.make_fixtures import DATASET

API = "/api/v1"
REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "scripts" / "rw-runner.py"
ITEMS = [f"case_{n:05d}.01.complete.-" for n in (1, 2, 3)]


def load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rw_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rw_runner"] = mod  # dataclasses resolve their module
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def plugins(tmp_path: Path) -> Path:
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "threshold").symlink_to(REPO / "plugins" / "threshold")
    crash = root / "crash"
    crash.mkdir()
    manifest = json.loads((REPO / "plugins" / "threshold" / "task.json").read_text())
    manifest.update(
        id="test.crash",
        title="crash",
        runtime={
            "type": "external",
            "command": ["{python}", "-c", "import sys; print('boom'); sys.exit(3)"],
        },
    )
    (crash / "task.json").write_text(json.dumps(manifest))
    return root


@pytest.fixture
def env(tmp_path: Path, fixtures_copy: Path, plugins: Path) -> Iterator[tuple[TestClient, str]]:
    derived = tmp_path / "derived"
    derived.mkdir()
    s = Settings(
        workspace_root=tmp_path / "ws",
        allowed_data_roots=str((fixtures_copy / DATASET).resolve()),
        allowed_derived_roots=str(derived.resolve()),
        plugins_root=plugins,
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(s, inline_jobs=True)) as c:
        pid = str(c.post(f"{API}/projects", json={"name": "ext"}).json()["project_id"])
        do_import(c, pid, fixtures_copy / DATASET)
        r = c.put(
            f"{API}/projects/{pid}/roots/DERIVED", json={"path": str(derived), "role": "derived"}
        )
        assert r.status_code == 200, r.text
        yield c, pid


def start_runner(ws: Path, plugins: Path, *extra: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            sys.executable,
            str(RUNNER),
            "--workspace",
            str(ws),
            "--plugins",
            str(plugins),
            "--poll",
            "0.1",
            *extra,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def poll(pred: Any, timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.05)


def run_status(c: TestClient, pid: str, rid: str) -> str:
    return str(c.get(f"{API}/projects/{pid}/task-runs/{rid}").json()["status"])


def test_waiting_then_runner_claims_and_registers_masks(
    env: tuple[TestClient, str], plugins: Path
) -> None:
    c, pid = env
    ws = ctx_of(c).settings.workspace_root
    t = c.get(f"{API}/tasks/segment.threshold").json()
    assert t["source"] == "plugins_root" and t["runner_online"] is False
    body = {
        "task_id": "segment.threshold",
        "settings": {"threshold": 100},
        "selection": {"item_ids": ITEMS},
    }
    started = c.post(f"{API}/projects/{pid}/task-runs", json=body).json()
    rid, job_id = started["run_id"], started["job_id"]
    poll(lambda: run_status(c, pid, rid) == "waiting_for_runner")  # TSK-06: not an error
    assert c.get(f"{API}/jobs/{job_id}").json()["status"] == "waiting_for_runner"
    job_dir = ws / "queue" / job_id
    spec = json.loads((job_dir / "job.json").read_text())
    assert spec["protocol"] == 1 and spec["task"]["id"] == "segment.threshold"
    assert all(
        Path(it["image"]["path"]).is_absolute() for it in spec["items"]
    )  # mirror-mounted paths
    runner = start_runner(ws, plugins)
    try:
        poll(lambda: bool(c.get(f"{API}/tasks").json()["runners"]))
        assert c.get(f"{API}/tasks/segment.threshold").json()["runner_online"] is True
        wait(c, job_id)
        run = c.get(f"{API}/projects/{pid}/task-runs/{rid}").json()
        assert run["status"] == "completed", run
        assert run["runtime"] == "external" and run["counts"]["ok"] == 3
        claim = json.loads((job_dir / "claim").read_text())
        poll(lambda: (job_dir / "exit.json").is_file())  # written after the process exits
        assert claim["runner_id"] and json.loads((job_dir / "exit.json").read_text())["code"] == 0
        seg = f"threshold-{rid[:8].lower()}"
        sets = {s["seg_id"]: s for s in c.get(f"{API}/projects/{pid}/segmentations").json()}
        assert sets[seg]["producer"]["run_id"] == rid and sets[seg]["n_items"] == 3
        item = c.get(f"{API}/projects/{pid}/items/{ITEMS[0]}").json()
        assert (
            c.get(f"{API}/projects/{pid}/items/{ITEMS[0]}/mask", params={"seg": seg}).status_code
            == 200
        )
        assert item["masks"][seg]["ref"].startswith(f"DERIVED:{pid}/segment.threshold/runs/{rid}/")
        assert (job_dir / "job.json").is_file()  # queue files stay for audit (the runner's dir)
    finally:
        runner.terminate()
        runner.wait(10)
    assert not list((ws / "queue" / "runners").glob("*.json"))  # heartbeat removed on exit


def test_cancel_sigterm_then_resume(env: tuple[TestClient, str], plugins: Path) -> None:
    c, pid = env
    ws = ctx_of(c).settings.workspace_root
    body = {
        "task_id": "segment.threshold",
        "settings": {"threshold": 100, "delay_s": 1.5},
        "selection": {"item_ids": ITEMS},
    }
    started = c.post(f"{API}/projects/{pid}/task-runs", json=body).json()
    rid = started["run_id"]
    runner = start_runner(ws, plugins)
    try:
        pdir = ctx_of(c).workspace.project_dir(pid)
        poll(lambda: (pdir / "tasks" / "runs" / rid / "items.jsonl").is_file())
        run = c.post(f"{API}/projects/{pid}/task-runs/{rid}/cancel").json()
        assert run["status"] == "cancelled" and run["counts"]["ok"] < 3
        job_dir = ws / "queue" / started["job_id"]
        poll(lambda: (job_dir / "exit.json").is_file())
        assert json.loads((job_dir / "exit.json").read_text())["code"] != 0  # SIGTERM
        again = c.post(f"{API}/projects/{pid}/task-runs/{rid}/resume").json()
        wait(c, again["job_id"])
        run = c.get(f"{API}/projects/{pid}/task-runs/{rid}").json()
        assert run["status"] == "completed" and run["counts"]["ok"] == 3 and run["attempts"] == 2
        second = json.loads((ws / "queue" / again["job_id"] / "job.json").read_text())
        assert set(second["resume"]["skip"]) and len(second["resume"]["skip"]) < 3
    finally:
        runner.terminate()
        runner.wait(10)


def test_crashing_task_and_cancel_before_claim(env: tuple[TestClient, str], plugins: Path) -> None:
    c, pid = env
    ws = ctx_of(c).settings.workspace_root
    started = c.post(
        f"{API}/projects/{pid}/task-runs",
        json={"task_id": "test.crash", "selection": {"item_ids": ITEMS}},
    ).json()
    runner = start_runner(ws, plugins, "--once")
    try:
        wait(c, started["job_id"])
        run = c.get(f"{API}/projects/{pid}/task-runs/{started['run_id']}").json()
        assert run["status"] == "failed" and "code 3" in run["error"] and "boom" in run["error"]
    finally:
        runner.wait(20)
    # a job cancelled while waiting is never claimed (TSK-07)
    s2 = c.post(
        f"{API}/projects/{pid}/task-runs",
        json={"task_id": "test.crash", "selection": {"item_ids": ITEMS}},
    ).json()
    run = c.post(f"{API}/projects/{pid}/task-runs/{s2['run_id']}/cancel").json()
    assert run["status"] == "cancelled"
    r2 = start_runner(ws, plugins, "--once")
    assert r2.wait(20) == 0
    assert not (ws / "queue" / s2["job_id"] / "claim").exists()


def test_lost_runner_fails_the_run(
    env: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    c, pid = env
    monkeypatch.setattr(task_service, "RUNNER_LOST_S", 0.5)
    ws = ctx_of(c).settings.workspace_root
    started = c.post(
        f"{API}/projects/{pid}/task-runs",
        json={"task_id": "segment.threshold", "selection": {"item_ids": ITEMS}},
    ).json()
    job_dir = ws / "queue" / started["job_id"]
    poll(lambda: (job_dir / "job.json").is_file())
    (job_dir / "claim").write_text(
        json.dumps({"runner_id": "gone", "pid": 1, "at": "2026-01-01T00:00:00Z"})
    )
    wait(c, started["job_id"])
    run = c.get(f"{API}/projects/{pid}/task-runs/{started['run_id']}").json()
    assert run["status"] == "failed" and "heartbeats" in (run["error"] or "")


def test_runner_claims_once(tmp_path: Path, plugins: Path) -> None:
    mod = load_runner()
    job = tmp_path / "queue" / "J1"
    job.mkdir(parents=True)
    a = mod.Runner(tmp_path, plugins, set(), 1)
    b = mod.Runner(tmp_path, plugins, set(), 1)
    assert a.claim(job) is True and b.claim(job) is False  # O_EXCL
    assert set(a.manifests) == {"segment.threshold", "test.crash"}
    assert set(mod.Runner(tmp_path, plugins, {"segment.threshold"}, 1).manifests) == {
        "segment.threshold"
    }
