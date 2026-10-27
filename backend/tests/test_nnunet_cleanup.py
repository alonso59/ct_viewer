"""SEG-11, OPS-16, TST-22: partial-start cleanup, reaping and hermetic fake inference."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from plugins.nnunet import run as inference
from plugins.nnunet.profile import load_profile
from plugins.protocol import Job

from tests.test_nnunet import make_images, make_model, plugin_env, run_plugin, write_job


def stop_owned(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(5)


def test_second_spawn_failure_reaps_already_started_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, profiles = make_model(tmp_path)
    monkeypatch.setenv("nnUNet_results", str(results))
    monkeypatch.setenv("RW_NNUNET_PROFILES_DIR", str(profiles))
    profile = load_profile("kits2023-dataset220")
    items = make_images(tmp_path, 2)
    job_dir = tmp_path / "job"
    write_job(job_dir, items, tmp_path / "derived")
    children: list[subprocess.Popen[bytes]] = []

    def spawn(name: str, command: list[str], env: dict[str, str]) -> Any:
        if children:
            raise OSError("second spawn failed")
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
        )
        children.append(process)
        return inference.Child(name, process)

    monkeypatch.setattr(inference, "_spawn", spawn)
    try:
        with pytest.raises(OSError, match="second spawn failed"):
            inference._execute(Job(str(job_dir)), profile, ["2", "5"])
        assert children[0].poll() is not None, "first worker survived failed partial startup"
    finally:
        for process in children:
            stop_owned(process)


def test_escalation_reaps_worker_and_preserves_unrelated_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = tmp_path / "ready"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,time,sys; from pathlib import Path; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "Path(sys.argv[1]).touch(); time.sleep(60)",
            str(ready),
        ],
        start_new_session=True,
    )
    sentinel = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    monkeypatch.setattr(inference, "TERM_GRACE_S", 0.1)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert time.monotonic() < deadline, "test worker failed to become ready"
            time.sleep(0.01)
        inference._terminate([inference.Child("owned", process)])
        assert process.returncode is not None, "worker was signalled but not reaped"
        assert sentinel.poll() is None
    finally:
        stop_owned(process)
        stop_owned(sentinel)


def test_fake_cli_ignores_inherited_failure_switches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, profiles = make_model(tmp_path)
    items = make_images(tmp_path, 2)
    job = tmp_path / "job"
    write_job(job, items, tmp_path / "derived")
    monkeypatch.setenv("FAKE_NNUNET_FAIL_PART", "1")
    monkeypatch.setenv("FAKE_NNUNET_BAD_GEOMETRY", "case_000000")
    environment = plugin_env(tmp_path / "fake", results, profiles)
    assert "FAKE_NNUNET_FAIL_PART" not in environment
    assert "FAKE_NNUNET_BAD_GEOMETRY" not in environment
    assert run_plugin(job, environment).returncode == 0
    assert len(list((tmp_path / "derived").glob("*.nii.gz"))) == 2


def test_cuda_oom_preserves_detail_and_stops_later_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, profiles = make_model(tmp_path)
    monkeypatch.setenv("nnUNet_results", str(results))
    monkeypatch.setenv("RW_NNUNET_PROFILES_DIR", str(profiles))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-one,GPU-two")
    profile = load_profile("kits2023-dataset220")
    job = tmp_path / "job"
    write_job(job, make_images(tmp_path, 4), tmp_path / "outputs")
    monkeypatch.setattr(inference, "_command_exists", lambda name: None)
    monkeypatch.setattr(inference, "_versions", lambda: {})
    calls = []

    class FailedProcess:
        def poll(self) -> int:
            return 1

    def spawn(name: str, command: list[str], env: dict[str, str]) -> Any:
        calls.append(name)
        with (job / "task.log").open("a") as log:
            log.write("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 1 GiB.\n")
        return inference.Child(name, FailedProcess())

    monkeypatch.setattr(inference, "load_profile", lambda name: profile)
    monkeypatch.setattr(inference, "_spawn", spawn)
    assert inference.run(str(job)) == 1
    result = json.loads((job / "result.json").read_text())
    assert result["status"] == "failed"
    assert "CUDA out of memory" in result["error"]
    assert "resume" in result["error"]
    assert result["counts"]["failed"] == 2
    assert len(calls) == 2
