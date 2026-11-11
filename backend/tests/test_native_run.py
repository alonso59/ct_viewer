"""ADR-0055 §1-§4: `rw-native.py run` in the foreground and the app-job commands, against a stub
release and a fake scheduler. Nothing here certifies a cluster (OPS-20)."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "scripts" / "rw-native.py"
TEMPLATE = TOOL.with_name("rw-app.sbatch")
APP = """
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

Path(os.environ["SEEN"]).write_text(json.dumps(dict(os.environ)))
if os.environ.get("EXIT_WITH"):
    sys.exit(int(os.environ["EXIT_WITH"]))

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')
    def log_message(self, *args):
        pass

HTTPServer((os.environ["HOST"], int(os.environ["PORT"])), Health).serve_forever()
"""
SCHEDULER = {
    "sbatch": '#!/bin/sh\necho "$@" > "$FAKE/submitted"\n'
    'echo "41|RUNNING|node07|0:05|1:00:00" > "$FAKE/queue"\n'
    'cp "$FAKE/connection" "$FAKE/job/app-job.json" 2>/dev/null\necho 41\n',
    "squeue": '#!/bin/sh\ncat "$FAKE/queue" 2>/dev/null\nexit 0\n',
    "scancel": '#!/bin/sh\necho "$@" > "$FAKE/cancelled"\nrm -f "$FAKE/queue"\n',
}


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A state folder with one stub release, and fake scheduler commands on PATH."""
    state, fake = tmp_path / "state", tmp_path / "fake"
    release = state / "releases/native-test"
    (release / "scripts").mkdir(parents=True)
    (release / "backend").mkdir()
    (release / "scripts/container_app.py").write_text(APP)
    prefix = tmp_path / "env"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin/python").symlink_to(sys.executable)
    meta = {"tag": "native-test", "python_env": str(prefix)}
    (release / "release.json").write_text(json.dumps(meta))
    (state / "config").mkdir()
    (state / "config/runtime.env").write_text(f"WORKSPACE_ROOT={state / 'workspace'}\nPORT=18431\n")
    (state / "config/app-job.env").write_text(
        "TAG=native-test\nTIME=1:00:00\nACCOUNT=lab\nPARTITION=cpu_long\n"
    )
    (fake / "bin").mkdir(parents=True)
    (fake / "job").mkdir(mode=0o700)
    for name, text in SCHEDULER.items():
        (fake / "bin" / name).write_text(text)
        (fake / "bin" / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE", str(fake))
    monkeypatch.setenv("SEEN", str(tmp_path / "seen.json"))
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    return tmp_path


def command(site: Path, *args: str) -> list[str]:
    base = [
        "--state",
        str(site / "state"),
        "--job-dir",
        str(site / "fake/job"),
        "--allocation",
        str(site / "pool"),
    ]
    return [sys.executable, str(TOOL), *base, "--poll", "0.05", "--wait", "1", *args]


def tool(site: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command(site, *args), capture_output=True, text=True, timeout=60, check=False
    )


def wait_for(path: Path) -> None:
    deadline = time.monotonic() + 30
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.05)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_run_in_a_job_announces_itself_and_cleans_up_on_sigterm(site: Path) -> None:
    job = site / "fake/job"
    env = {**os.environ, "SLURM_JOB_ID": "41", "SLURM_JOB_END_TIME": "1800000000"}
    process = subprocess.Popen(command(site, "run"), env=env)
    try:
        wait_for(job / "app-job.json")
        record = json.loads((job / "app-job.json").read_text())
        credential = (job / "app-job.credential").read_text().strip()
        seen = json.loads((site / "seen.json").read_text())
        assert (record["job_id"], record["bind"], record["tag"]) == (
            "41",
            "loopback",
            "native-test",
        )
        assert record["port"] >= 18431 and record["ends"].startswith("2027-01-15")
        assert len(credential) >= 43 and credential not in json.dumps(record)
        assert (
            mode(job) == 0o700
            and mode(job / "app-job.json") == mode(job / "app-job.credential") == 0o600
        )
        assert seen["HOST"] == "127.0.0.1" and seen["PORT"] == str(record["port"])
        assert seen["SESSION_CREDENTIAL_FILE"] == str(job / "app-job.credential")
        assert seen["CONTAINER_MODE"] == "0" and seen["STATIC_ROOT"].endswith("native-test/static")
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=30) == 0
    finally:
        process.kill()
    assert not (job / "app-job.json").exists() and not (job / "app-job.credential").exists()


def test_run_outside_a_job_has_no_credential_and_ends_with_the_app(
    site: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXIT_WITH", "7")
    done = tool(site, "run", "native-test", "--bind", "node")
    seen = json.loads((site / "seen.json").read_text())
    assert done.returncode == 7
    assert seen["HOST"] == "0.0.0.0" and "SESSION_CREDENTIAL_FILE" not in seen
    assert not list((site / "fake/job").iterdir())


def test_run_refuses_a_state_folder_without_working_locks(site: Path) -> None:
    (site / "state/workspace").write_text("not a folder")
    done = tool(site, "run")
    assert done.returncode != 0 and "refusing to start" in done.stderr
    assert not (site / "seen.json").exists()


def test_start_submits_a_clean_cpu_job_from_the_settings(site: Path) -> None:
    fake = site / "fake"
    record = {
        "job_id": "41",
        "node": "node07",
        "port": 18431,
        "bind": "loopback",
        "tag": "native-test",
        "ends": None,
    }
    (fake / "connection").write_text(json.dumps(record))
    done = tool(site, "start")
    assert done.returncode == 0, done.stderr
    submitted = (fake / "submitted").read_text().split()
    assert "--export=NONE" in submitted and "--job-name=rw-app" in submitted
    assert {
        "--account=lab",
        "--partition=cpu_long",
        "--time=1:00:00",
        "--cpus-per-task=4",
        "--mem=16G",
    } <= set(submitted)
    assert not any(flag.startswith(("--gres", "--gpus")) for flag in submitted)
    assert submitted[-6:-4] == [str(TEMPLATE), "_run"] and submitted[-4].endswith("env/bin/python")
    assert "node07" in done.stdout and "forward port 18431" in done.stdout
    assert "credential" in done.stdout


def test_start_refuses_a_second_job_and_bad_settings(site: Path) -> None:
    fake = site / "fake"
    (fake / "queue").write_text("40|PENDING||0:00|1:00:00\n")
    assert tool(site, "start").returncode == 1
    assert not (fake / "submitted").exists()
    (fake / "queue").unlink()
    (site / "state/config/app-job.env").write_text("TIME=1:00:00\nPARTITION=cpu --wrap=id\n")
    refused = tool(site, "start")
    assert refused.returncode != 0 and "invalid PARTITION" in refused.stderr
    assert not (fake / "submitted").exists()


def test_status_trusts_the_scheduler_over_a_stale_connection_file(site: Path) -> None:
    job = site / "fake/job"
    (job / "app-job.json").write_text(json.dumps({"job_id": "39", "node": "node01", "port": 1}))
    (job / "app-job.credential").write_text("old")
    done = tool(site, "status")
    assert done.returncode == 0 and "No app job" in done.stdout
    assert not list(job.iterdir())
    assert tool(site, "credential").returncode != 0


def test_credential_and_stop(site: Path) -> None:
    fake, job = site / "fake", site / "fake/job"
    (fake / "queue").write_text("41|RUNNING|node07|0:05|1:00:00\n")
    (job / "app-job.json").write_text(json.dumps({"job_id": "41", "node": "node07", "port": 18431}))
    (job / "app-job.credential").write_text("s" * 43 + "\n")
    assert tool(site, "credential").stdout.strip() == "s" * 43
    done = tool(site, "stop")
    assert done.returncode == 0 and (fake / "cancelled").read_text().strip() == "41"
    assert not list(job.iterdir())


def test_the_job_script_starts_run_with_the_arguments_it_was_given(site: Path) -> None:
    echo = site / "echo"
    echo.write_text('#!/bin/sh\necho "$@"\n')
    echo.chmod(0o755)
    env = {**os.environ, "SLURM_JOB_ID": "41", "SLURM_EXPORT_ENV": "NONE"}
    done = subprocess.run(
        [str(TEMPLATE), "_run", str(echo), "tool.py", "/state", "/job"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert done.stdout.split() == ["tool.py", "--state", "/state", "--job-dir", "/job", "run"]
