"""CTF-10..14: durable script runs — journal, replay after a restart without duplicate children,
bounded wait for a busy task, attention, and control cascade."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ctflow import runs as script_runs
from app.main import create_app
from app.tasks.registry import manifest_hash
from tests.test_api_ingest import ctx_of
from tests.test_tasks import ITEMS, builtin_threshold, with_derived
from tests.test_tasks import env as env
from tests.test_tasks import plugins_root as plugins_root
from tests.test_tasks import proj as proj

API = "/api/v1"
RUNS = f"{API}/ctflow/script-runs"
THR = "segment.threshold"


def start(c: TestClient, script: str, pid: str) -> str:
    r = c.post(RUNS, json={"script": script, "project_id": pid}, headers={"X-Reviewer": "Sc"})
    assert r.status_code == 202, r.text
    return str(r.json()["run_id"])


def until(
    c: TestClient, rid: str, done: Callable[[dict[str, Any]], bool], timeout: float = 30
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    run: dict[str, Any] = {}
    while time.monotonic() < deadline:
        run = c.get(f"{RUNS}/{rid}").json()
        if done(run):
            return run
        time.sleep(0.05)
    raise AssertionError(run)


def ended(run: dict[str, Any]) -> bool:
    return run["status"] not in script_runs.ACTIVE


def children(c: TestClient, pid: str, rid: str) -> list[dict[str, Any]]:
    runs = c.get(f"{API}/projects/{pid}/task-runs").json()
    return [r for r in runs if (r.get("origin") or {}).get("script_run_id") == rid]


def test_a_script_run_starts_waits_and_journals(env: TestClient, proj: str, tmp_path: Path) -> None:
    with_derived(env, proj, tmp_path)
    rid = start(env, f"set r [{THR} {ITEMS[0]} -threshold 100]\nwait $r\nputs done-$r", proj)
    run = until(env, rid, ended)
    assert run["status"] == "completed" and run["reviewer"] == "Sc" and run["starts"] == 1
    assert [e["words"][0] for e in run["journal"]] == [THR, "wait"]
    assert run["journal"][1]["value"] == "completed"
    child = children(env, proj, rid)
    assert len(child) == 1 and child[0]["origin"] == {
        "client": "script", "session": None, "script_run_id": rid, "step": 1,
    }  # fmt: skip
    assert child[0]["reviewer"] == "Sc" and child[0]["status"] == "completed"
    logs = env.get(f"{API}/logs/script-run/{rid}").json()
    assert f"done-{child[0]['run_id']}" in [line["text"] for line in logs["lines"]]
    assert logs["done"] is True


def test_a_busy_task_is_waited_for(env: TestClient, proj: str, tmp_path: Path) -> None:
    """CTF-13: the second start of one task waits for the first (TSK-12), then starts."""
    with_derived(env, proj, tmp_path)
    rid = start(env, f"{THR} {ITEMS[0]} -delay-s 1\n{THR} {ITEMS[1]}", proj)
    until(env, rid, lambda r: r["status"] == "waiting" or ended(r))
    run = until(env, rid, ended)
    assert run["status"] == "completed" and len(children(env, proj, rid)) == 2


def test_a_long_busy_task_moves_the_run_to_attention(
    env: TestClient, proj: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_derived(env, proj, tmp_path)
    monkeypatch.setattr(script_runs, "BUSY_WAIT_S", 0.3)
    body = {"task_id": THR, "settings": {"delay_s": 2}, "selection": {"item_ids": ITEMS[:1]}}
    blocker = env.post(f"{API}/projects/{proj}/task-runs", json=body).json()
    rid = start(env, f"{THR} {ITEMS[1]}", proj)
    held = until(env, rid, ended)
    assert held["status"] == "attention" and "busy" in held["waiting"]
    assert children(env, proj, rid) == []
    until_run = time.monotonic() + 20
    while env.get(f"{API}/projects/{proj}/task-runs/{blocker['run_id']}").json()["status"] in {
        "queued", "running",
    }:  # fmt: skip
        assert time.monotonic() < until_run
        time.sleep(0.05)
    assert env.post(f"{RUNS}/{rid}/resume").status_code == 202
    assert until(env, rid, ended)["status"] == "completed"
    assert len(children(env, proj, rid)) == 1


def test_cancel_stops_the_script_and_its_child(env: TestClient, proj: str, tmp_path: Path) -> None:
    with_derived(env, proj, tmp_path)
    rid = start(env, f"set r [{THR} all -delay-s 5]\nwait $r\nputs never", proj)
    until(env, rid, lambda r: (r.get("waiting") or "").startswith("wait"))
    assert env.post(f"{RUNS}/{rid}/cancel").json()["status"] == "cancelling"
    run = until(env, rid, ended)
    assert run["status"] == "cancelled"
    child = children(env, proj, rid)[0]
    deadline = time.monotonic() + 20
    while child["status"] not in {"cancelled", "completed_with_errors", "completed"}:
        assert time.monotonic() < deadline
        time.sleep(0.05)
        child = children(env, proj, rid)[0]
    assert child["status"] == "cancelled"
    logs = env.get(f"{API}/logs/script-run/{rid}").json()
    assert "never" not in [line["text"] for line in logs["lines"]]


def test_pause_then_resume_replays_without_repeating(
    env: TestClient, proj: str, tmp_path: Path
) -> None:
    with_derived(env, proj, tmp_path)
    rid = start(env, f"set r [{THR} {ITEMS[0]} -delay-s 1]\nwait $r\n{THR} {ITEMS[1]}", proj)
    until(env, rid, lambda r: (r.get("waiting") or "").startswith("wait"))
    console = env.post(f"{API}/ctflow/eval", json={"line": f"pause {rid}"}).json()
    assert console["steps"][0]["value"] == "pausing"
    assert until(env, rid, ended)["status"] == "paused"
    resumed = env.post(f"{API}/ctflow/eval", json={"line": f"resume {rid}"}).json()
    assert resumed["steps"][0]["work"]["kind"] == "script-run"
    run = until(env, rid, ended)
    assert run["status"] == "completed" and run["attempts"] == 2
    assert [c["origin"]["step"] for c in children(env, proj, rid)] == [3, 1]  # newest first


def test_restart_interrupts_and_resume_finds_a_half_journaled_start(
    tmp_path: Path, fixtures_copy: Path, plugins_root: Path
) -> None:
    """CTF-12: no duplicate child even when the server stopped between a start and its
    journal line; the started run is found by its origin."""
    from tests.test_api_ingest import do_import
    from tests.test_format_v2 import derived_settings
    from tools.make_fixtures import DATASET

    derived = tmp_path / "derived"
    derived.mkdir()
    settings = derived_settings(tmp_path, fixtures_copy / DATASET, derived)

    def app() -> TestClient:
        c = TestClient(create_app(settings, inline_jobs=True))
        c.__enter__()
        reg = ctx_of(c).registry
        reg.tasks.pop(THR, None)
        m = builtin_threshold()
        reg.add(m, manifest_hash(m.model_dump_json().encode()), "builtin")
        return c

    first = app()
    pid = first.post(f"{API}/projects", json={"name": "r", "packs": ["ccrcc"]}).json()["project_id"]
    do_import(first, pid, fixtures_copy / DATASET)
    with_derived(first, pid, tmp_path)
    rid = start(first, f"set r [{THR} {ITEMS[0]}]\nwait $r\nputs after", pid)
    until(first, rid, ended)
    first.__exit__(None, None, None)
    # The server stopped after the start but before its journal said so, and the run was live.
    journal = settings.workspace_root / "plugins/ctflow/runs" / rid / "journal.jsonl"
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    journal.write_text(json.dumps(rows[0]) + "\n")  # only the pending line of call 1
    record = journal.parent / "run.json"
    record.write_text(json.dumps({**json.loads(record.read_text()), "status": "running"}))

    second = app()
    try:
        assert second.get(f"{RUNS}/{rid}").json()["status"] == "interrupted"
        assert second.post(f"{RUNS}/{rid}/resume").status_code == 202
        run = until(second, rid, ended)
        assert run["status"] == "completed", run
        assert len(children(second, pid, rid)) == 1  # found, not started again
        texts = [x["text"] for x in second.get(f"{API}/logs/script-run/{rid}").json()["lines"]]
        assert "— attempt 2 —" in texts and texts.count("after") == 2  # once per attempt
    finally:
        second.__exit__(None, None, None)


def test_a_script_that_takes_another_path_is_refused(
    env: TestClient, proj: str, tmp_path: Path
) -> None:
    with_derived(env, proj, tmp_path)
    rid = start(env, f"{THR} {ITEMS[0]}", proj)
    until(env, rid, ended)
    journal = ctx_of(env).settings.workspace_root / "plugins/ctflow/runs" / rid / "journal.jsonl"
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    journal.write_text("".join(json.dumps({**r, "words": [THR, ITEMS[2]]}) + "\n" for r in rows))
    record = journal.parent / "run.json"
    record.write_text(json.dumps({**json.loads(record.read_text()), "status": "failed"}))
    env.post(f"{RUNS}/{rid}/resume")
    run = until(env, rid, ended)
    assert run["status"] == "failed" and "another path" in run["error"]["detail"]


def test_wait_belongs_to_script_runs(env: TestClient, proj: str) -> None:
    r = env.post(f"{API}/ctflow/eval", json={"line": "wait x", "project_id": proj})
    assert r.status_code == 422 and "script run" in r.json()["detail"]
