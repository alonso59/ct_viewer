"""TSK-11, OPS-16/17, TST-22: runner admission, path boundaries and cancellation races."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.test_runner import RUNNER, load_runner


def setup_queue(tmp_path: Path, *, gpu: str = "none") -> tuple[Path, Path, Path]:
    plugins = tmp_path / "plugins"
    plugin = plugins / "harmless"
    plugin.mkdir(parents=True)
    marker = tmp_path / "launched"
    manifest = {
        "id": "test.harmless",
        "runtime": {
            "type": "external",
            "command": [
                "{python}",
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
                str(marker),
            ],
        },
        "resources": {"gpu": gpu},
    }
    (plugin / "task.json").write_text(json.dumps(manifest))
    job = tmp_path / "queue" / "J1"
    job.mkdir(parents=True)
    (job / "job.json").write_text(json.dumps({"task": {"id": "test.harmless"}}))
    return plugins, job, marker


@pytest.mark.parametrize("action", ["cancel", "pause"])
def test_supervised_control_at_claim_publishes_matching_cleanup_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    from plugins.runner import supervised

    from app.tasks.protocol import external_finished

    workspace = tmp_path / "workspace"
    plugins, job, marker = setup_queue(workspace, gpu="required")
    for name in ("source", "models", "derived"):
        (tmp_path / name).mkdir()
    spec = json.loads((job / "job.json").read_text())
    spec["output_dir"] = str(tmp_path / "derived")
    (job / "job.json").write_text(json.dumps(spec))
    configuration = {
        "deployment": 1,
        "backend": "server",
        "environment": str(Path(sys.executable).parent.parent),
        "workspace": str(workspace),
        "source_roots": [str(tmp_path / "source")],
        "model_roots": [str(tmp_path / "models")],
        "derived_roots": [str(tmp_path / "derived")],
        "state_dir": str(tmp_path / "host-state"),
        "gpu_pool": ["0"],
        "limits": {"cpus": 1, "memory_mb": 128, "tasks": 16, "seconds": 30, "gpus": 1},
    }
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(configuration))
    path.chmod(0o600)
    monkeypatch.setattr(supervised.Supervisor, "verify", lambda self: {"ready": True})
    monkeypatch.setattr(
        supervised.gpu,
        "inventory",
        lambda: [{"index": "0", "uuid": "GPU-test", "used_mb": 0, "utilization": 0, "pids": []}],
    )

    def no_launch(*args: Any) -> None:
        raise AssertionError("cancelled claim launched an attempt")

    monkeypatch.setattr(supervised.service, "launch", no_launch)
    runner = load_runner().Runner(workspace, plugins, set(), 1, path)
    original = runner.claim

    def control_at_claim(candidate: Path) -> bool:
        claimed = bool(original(candidate))
        (candidate / "control.json").write_text(json.dumps({"id": "C1", "action": action}))
        (candidate / action).touch()
        return claimed

    runner.claim = control_at_claim
    runner.start(job)
    assert not marker.exists()
    assert external_finished(job), f"{action} at claim has no matching cleanup acknowledgement"
    assert not (tmp_path / "host-state/lease.json").exists()
    attempt = json.loads((job / "attempt.json").read_text())["attempt"]
    ack = json.loads((job / "control-ack.json").read_text())
    assert (ack["id"], ack["attempt"]) == ("C1", attempt)


def test_paused_queued_job_is_never_claimed(tmp_path: Path) -> None:
    plugins, job, marker = setup_queue(tmp_path)
    (job / "pause").touch()
    runner = load_runner().Runner(tmp_path, plugins, set(), 1)
    assert runner.pending() == []
    assert runner.claim(job) is False
    runner.start(job)
    assert not (job / "claim").exists() and not marker.exists()


def test_cancel_arriving_during_claim_never_launches(tmp_path: Path) -> None:
    plugins, job, marker = setup_queue(tmp_path)
    runner = load_runner().Runner(tmp_path, plugins, set(), 1)
    claim = runner.claim

    def cancel_at_claim(path: Path) -> bool:
        result = bool(claim(path))
        (job / "cancel").touch()
        return result

    runner.claim = cancel_at_claim
    try:
        runner.start(job)
        for running in runner.running.values():
            running.proc.wait(5)
        assert not marker.exists(), "a cancelled claim executed its command"
    finally:
        for running in runner.running.values():
            if running.proc.poll() is None:
                running.proc.terminate()
            running.proc.wait(5)
            running.log.close()


def test_queue_symlink_cannot_claim_outside_job(tmp_path: Path) -> None:
    plugins, job, marker = setup_queue(tmp_path)
    outside = tmp_path / "outside"
    job.rename(outside)
    job.symlink_to(outside, target_is_directory=True)
    runner = load_runner().Runner(tmp_path, plugins, set(), 1)
    try:
        runner.step()
        for running in runner.running.values():
            running.proc.wait(5)
        assert not (outside / "claim").exists()
        assert not marker.exists()
    finally:
        for running in runner.running.values():
            if running.proc.poll() is None:
                running.proc.terminate()
            running.proc.wait(5)
            running.log.close()
        runner.stop_heartbeat()


@pytest.mark.parametrize("gpu", ["required", "optional"])
def test_gpu_job_without_verified_containment_cannot_launch(tmp_path: Path, gpu: str) -> None:
    plugins, job, marker = setup_queue(tmp_path, gpu=gpu)
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--workspace",
            str(tmp_path),
            "--plugins",
            str(plugins),
            "--once",
        ],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0, result.stdout.decode()
    assert not marker.exists(), "GPU admission fell back to an unsupervised process"
    assert not (job / "claim").exists()
    assert b"containment" in result.stderr.lower()


def test_preflight_reports_without_starting_runner(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--preflight"],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode in (0, 2), result.stderr.decode()
    report: dict[str, Any] = json.loads(result.stdout)
    assert report["ready"] is False  # no verified runner/storage policy was configured
    assert report["checks"] and report["blockers"]
    assert not (tmp_path / "queue").exists()


def test_runner_shutdown_waits_for_owned_task_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugins, job, _marker = setup_queue(tmp_path)
    manifest_path = plugins / "harmless" / "task.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime"]["command"] = ["{python}", "-c", "import time; time.sleep(60)"]
    manifest_path.write_text(json.dumps(manifest))
    runner = load_runner().Runner(tmp_path, plugins, set(), 1)
    runner.start(job)
    running = next(iter(runner.running.values()))

    def stop() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "step", stop)
    try:
        assert runner.run(0.01, False) == 0
        assert running.proc.returncode is not None, "shutdown returned before reaping its task"
        assert running.log.closed
    finally:
        if running.proc.poll() is None:
            running.proc.kill()
        running.proc.wait(5)
        running.log.close()
        runner.stop_heartbeat()


def test_once_runner_does_not_wait_forever_for_unadvertised_tasks(tmp_path: Path) -> None:
    plugins, job, marker = setup_queue(tmp_path)
    other = plugins / "other"
    other.mkdir()
    manifest = json.loads((plugins / "harmless" / "task.json").read_text())
    manifest["id"] = "test.other"
    (other / "task.json").write_text(json.dumps(manifest))
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--workspace",
            str(tmp_path),
            "--plugins",
            str(plugins),
            "--tasks",
            "test.other",
            "--poll",
            "0.05",
            "--once",
        ],
        capture_output=True,
        timeout=3,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert not marker.exists() and not (job / "claim").exists()


def test_log_symlink_is_refused_without_modifying_target(tmp_path: Path) -> None:
    plugins, job, marker = setup_queue(tmp_path)
    target = tmp_path / "outside-log"
    target.write_bytes(b"unchanged")
    (job / "task.log").symlink_to(target)
    runner = load_runner().Runner(tmp_path, plugins, set(), 1)
    try:
        runner.start(job)
        for running in runner.running.values():
            running.proc.wait(5)
        assert not marker.exists() and target.read_bytes() == b"unchanged"
        assert json.loads((job / "exit.json").read_text())["code"] == 1
    finally:
        runner.stop_tasks()
