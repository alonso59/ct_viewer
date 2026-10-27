"""TSK-14: an observed owned invocation repairs a lost launch acknowledgement."""

import json
import os
from pathlib import Path

import pytest
from plugins.runner import gpu, service

from tests.test_runner_paths import setup


def test_recovery_acknowledges_observed_owned_launch_before_it_can_be_collected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor, job, _dataset, spec = setup(tmp_path)
    monkeypatch.setattr(gpu, "device_path", lambda identity: Path("/dev/null"))
    record = supervisor.prepare(
        job,
        {"runtime": {"command": ["{python}"]}},
        job.parent,
        spec,
        ["GPU-test"],
    )
    assert supervisor.pool.reserve(record)
    (job / "attempt.json").write_text(json.dumps(record))
    state = {
        "LoadState": "loaded",
        "ActiveState": "active",
        "SubState": "running",
        "Description": f"RW attempt {record['attempt']}",
        "InvocationID": "verified-invocation",
    }
    monkeypatch.setattr(service, "show", lambda attempt: state)
    try:
        supervisor.recover()
        saved = supervisor.pool.read()
        assert saved is not None and saved["invocation"] == "verified-invocation"
        assert saved["state"] == "running"
        assert json.loads((job / "attempt.json").read_text())["invocation"] == saved["invocation"]
    finally:
        supervisor.pool.release(record["attempt"])


@pytest.mark.parametrize("accounting", ["foreign", "owned", "unknown"])
def test_empty_attempt_cleanup_distinguishes_foreign_gpu_contexts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accounting: str,
) -> None:
    supervisor, job, _dataset, spec = setup(tmp_path)
    monkeypatch.setattr(gpu, "device_path", lambda identity: Path("/dev/null"))
    record = supervisor.prepare(
        job, {"runtime": {"command": ["{python}"]}}, job.parent, spec, ["GPU-test"]
    )
    record.update(state="running", invocation="verified")
    assert supervisor.pool.reserve(record)
    (job / "worker-exit.json").write_text(json.dumps({"attempt": record["attempt"], "code": 0}))
    monkeypatch.setattr(
        service, "show", lambda attempt: {"ActiveState": "inactive", "LoadState": "loaded"}
    )
    monkeypatch.setattr(
        gpu,
        "inventory",
        lambda: (
            []
            if accounting == "unknown"
            else [{"uuid": "GPU-test", "pids": [os.getpid()], "used_mb": 40000, "total_mb": 46068}]
        ),
    )
    original = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, *a, **kw: (
            f"0::/user.slice/{service.unit_name(record['attempt'])}\n"
            if accounting == "owned" and path == Path(f"/proc/{os.getpid()}/cgroup")
            else original(path, *a, **kw)
        ),
    )
    supervisor.recover()
    if accounting == "foreign":
        assert supervisor.pool.read() is None
        assert json.loads((job / "exit.json").read_text())["cleanup_verified"] is True
    else:
        assert supervisor.pool.read() is not None
        assert not (job / "exit.json").exists()
