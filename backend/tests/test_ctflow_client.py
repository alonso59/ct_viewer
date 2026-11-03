"""CTF-18: the `ctflow` terminal client against a live server (stdlib HTTP, exit codes, attach)."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.main import create_app
from app.tasks.registry import manifest_hash
from tests.test_format_v2 import derived_settings
from tests.test_tasks import ITEMS, builtin_threshold
from tools.make_fixtures import DATASET

CTFLOW = Path(__file__).resolve().parents[2] / "scripts" / "ctflow.py"
API = "/api/v1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _job_done(c: httpx.Client, job_id: str) -> None:
    deadline = time.monotonic() + 60
    while c.get(f"{API}/jobs/{job_id}").json()["status"] not in {"succeeded", "failed"}:
        assert time.monotonic() < deadline
        time.sleep(0.05)


@pytest.fixture
def live(tmp_path: Path, fixtures_copy: Path) -> Iterator[tuple[str, str]]:
    """A running app with an imported project and the builtin threshold task: (url, pid)."""
    derived = tmp_path / "derived"
    derived.mkdir()
    app = create_app(derived_settings(tmp_path, fixtures_copy / DATASET, derived), inline_jobs=True)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline and thread.is_alive(), "server did not start"
        time.sleep(0.02)
    reg = app.state.ctx.registry
    reg.tasks.pop("segment.threshold", None)  # the external CI manifest, when PLUGINS_ROOT has it
    m = builtin_threshold()
    reg.add(m, manifest_hash(m.model_dump_json().encode()), "builtin")
    url = f"http://127.0.0.1:{port}"
    with httpx.Client(base_url=url, timeout=60) as c:
        pid = c.post(f"{API}/projects", json={"name": "cli", "packs": ["ccrcc"]}).json()[
            "project_id"
        ]
        root = str(fixtures_copy / DATASET)
        preview = c.post(f"{API}/projects/{pid}/imports/preview", json={"root": root}).json()
        commit = c.post(f"{API}/projects/{pid}/imports", json={"preview_id": preview["preview_id"]})
        _job_done(c, commit.json()["job_id"])
        roots = f"{API}/projects/{pid}/roots/DERIVED"
        assert c.put(roots, json={"path": str(derived), "role": "derived"}).is_success
    try:
        yield url, pid
    finally:
        server.should_exit = True
        thread.join(10)


def ctflow(tmp_path: Path, url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "config"), "CTFLOW_REVIEWER": "Term T"}
    return subprocess.run(
        [sys.executable, str(CTFLOW), "--url", url, *args],
        capture_output=True, text=True, timeout=120, env=env, stdin=subprocess.DEVNULL,
    )  # fmt: skip


def test_one_command_follows_to_the_end_and_exits_with_the_result(
    live: tuple[str, str], tmp_path: Path
) -> None:
    url, pid = live
    done = ctflow(tmp_path, url, "-p", pid, "segment.threshold", ITEMS[0], "-threshold", "100")
    assert done.returncode == 0, done.stderr
    assert "target: items · 1 items" in done.stdout and "] completed" in done.stdout
    runs = httpx.get(f"{url}{API}/projects/{pid}/task-runs").json()
    assert runs[0]["origin"]["client"] == "terminal" and runs[0]["reviewer"] == "Term T"
    status = ctflow(tmp_path, url, "-p", pid, "--json", "status", runs[0]["run_id"])
    assert json.loads(status.stdout)["work"]["status"] == "completed"
    assert not (tmp_path / "config").exists()  # one-shot use writes nothing locally


def test_detach_returns_at_once_and_attach_follows_later(
    live: tuple[str, str], tmp_path: Path
) -> None:
    url, pid = live
    started = ctflow(tmp_path, url, "-p", pid, "--detach", "-c", "segment.threshold all -delay-s 1")
    assert started.returncode == 0, started.stderr
    run_id = next(
        w for line in started.stdout.splitlines() if line.startswith("follow with:")
        for w in line.split()[-1:]
    )  # fmt: skip
    attached = ctflow(tmp_path, url, "-p", pid, "attach", run_id)
    # the fixture holds one corrupt image: the run ends with errors, and so does attach
    assert attached.returncode == 1 and "] completed_with_errors" in attached.stdout
    assert "case_00011.01.complete.- failed:" in attached.stdout
    logs = ctflow(tmp_path, url, "-p", pid, "logs", run_id)
    assert logs.returncode == 0


def test_refusals_print_the_cause_and_next_actions(live: tuple[str, str], tmp_path: Path) -> None:
    url, pid = live
    refused = ctflow(tmp_path, url, "segment.threshold", ITEMS[0])  # no project
    assert refused.returncode == 2
    assert "needs a project" in refused.stderr and "next: choose_project" in refused.stderr
    plan = ctflow(
        tmp_path, url, "-p", pid, "--plan", "segment.threshold", ITEMS[0], "-label", "999"
    )
    assert plan.returncode == 2 and "plan: settings need changes" in plan.stdout
    down = ctflow(tmp_path, f"http://127.0.0.1:{_free_port()}", "runs")
    assert down.returncode == 2 and "is the app running" in down.stderr


def test_interactive_console_keeps_the_project_and_saves_history_without_paths(
    live: tuple[str, str], tmp_path: Path
) -> None:
    url, pid = live
    lines = f"project {pid}\ncases\nstatus /data/patient-name\nhelp segment.threshold\nexit\n"
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "config"), "CTFLOW_REVIEWER": "Term T"}
    session = subprocess.run(
        [sys.executable, str(CTFLOW), "--url", url],
        input=lines, capture_output=True, text=True, timeout=60, env=env,
    )  # fmt: skip
    assert session.returncode in {0, 2}, session.stderr
    assert f"ctflow[{pid}]>" in session.stdout and "case_00001" in session.stdout
    history = tmp_path / "config" / "ctflow" / "history"
    if history.exists():  # readline is present
        saved = history.read_text()
        assert "cases" in saved and "patient-name" not in saved
