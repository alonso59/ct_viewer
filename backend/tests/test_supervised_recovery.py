"""TSK-14: an observed owned invocation repairs a lost launch acknowledgement."""

import json
from pathlib import Path

import pytest
from plugins.runner import service

from tests.test_runner_paths import setup


def test_recovery_acknowledges_observed_owned_launch_before_it_can_be_collected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor, job, _dataset, spec = setup(tmp_path)
    record = supervisor.prepare(
        job,
        {"runtime": {"command": ["{python}"]}},
        job.parent,
        spec,
        ["GPU-test"],
        [],
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
