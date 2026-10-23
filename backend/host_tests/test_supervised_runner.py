"""OPS-16/18/19: configured real user-service execution with fake GPU telemetry."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from plugins.runner import service

from tests.test_runner import RUNNER
from tests.test_runner_safety import setup_queue


@pytest.fixture
def deployment(
    tmp_path: Path,
) -> Iterator[dict[str, Any]]:
    plugins, job, marker = setup_queue(tmp_path, gpu="required")
    output = tmp_path / "derived"
    output.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    models = tmp_path / "models"
    models.mkdir()
    spec = json.loads((job / "job.json").read_text())
    spec.update(
        items=[{"item_id": "one", "image": {"path": str(source / "one.nii.gz")}}],
        settings={"gpu_cap": 1},
        output_dir=str(output),
        resume={"skip": []},
    )
    (source / "one.nii.gz").write_bytes(b"synthetic")
    (job / "job.json").write_text(json.dumps(spec))
    manifest_path = plugins / "harmless/task.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime"]["command"] = [
        "{python}",
        "-c",
        (
            "from pathlib import Path; import os,sys; "
            "assert 'rw-seg-' in Path('/proc/self/cgroup').read_text(); "
            "assert os.environ['CUDA_VISIBLE_DEVICES']=='GPU-test'; Path(sys.argv[1]).touch()"
        ),
        str(output / "launched"),
    ]
    manifest_path.write_text(json.dumps(manifest))
    bin_dir = tmp_path / "tools"
    bin_dir.mkdir()
    nvidia = bin_dir / "nvidia-smi"
    nvidia.write_text(
        """#!/bin/sh
case "$1" in
  --query-gpu=*) echo '0, GPU-test, synthetic, 1000, 0, 0';;
esac
"""
    )
    nvidia.chmod(0o755)
    config = {
        "deployment": 1,
        "backend": "server",
        "environment": str(Path(sys.executable).parent.parent),
        "workspace": str(tmp_path),
        "source_roots": [str(source)],
        "model_roots": [str(models)],
        "derived_roots": [str(output)],
        "gpu_pool": ["0"],
        "state_dir": str(tmp_path / "host-state"),
        "limits": {"cpus": 1, "memory_mb": 128, "tasks": 16, "seconds": 30, "gpus": 1},
    }
    # The workspace must be separate from the source/output roots, just as in production.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "queue").rename(workspace / "queue")
    job = workspace / "queue/J1"
    config["workspace"] = str(workspace)
    config_path = tmp_path / "deployment.json"
    config_path.write_text(json.dumps(config))
    config_path.chmod(0o600)
    argv = [
        sys.executable,
        str(RUNNER),
        "--workspace",
        str(workspace),
        "--plugins",
        str(plugins),
        "--deployment",
        str(config_path),
        "--poll",
        "0.05",
        "--once",
    ]
    environment = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    try:
        yield {
            "argv": argv,
            "env": environment,
            "job": job,
            "output": output,
            "marker": marker,
            "root": tmp_path,
            "manifest": manifest_path,
        }
    finally:
        record_path = job / "attempt.json"
        if record_path.exists():
            record = json.loads(record_path.read_text())
            assert service.stop(record), "test-owned service cleanup could not be verified"


def test_configured_gpu_task_runs_in_a_bounded_service_without_real_gpu_work(
    deployment: dict[str, Any],
) -> None:
    result = subprocess.run(
        deployment["argv"],
        env=deployment["env"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (deployment["output"] / "launched").exists(), result.stdout + result.stderr
    assert not deployment["marker"].exists()
    assert json.loads((deployment["job"] / "exit.json").read_text())["cleanup_verified"] is True
    assert not (deployment["root"] / "host-state/lease.json").exists()


def test_manager_ipc_survives_deep_project_paths(deployment: dict[str, Any]) -> None:
    manifest_path = deployment["manifest"]
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime"]["command"] = [
        "{python}",
        "-c",
        (
            "import multiprocessing,sys; from pathlib import Path; "
            "manager=multiprocessing.Manager(); data=manager.dict(); data['ok']=True; "
            "assert data['ok']; manager.shutdown(); Path(sys.argv[1]).touch()"
        ),
        str(deployment["output"] / "ipc-ok"),
    ]
    manifest_path.write_text(json.dumps(manifest))
    result = subprocess.run(
        deployment["argv"],
        env=deployment["env"],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (deployment["output"] / "ipc-ok").exists(), (deployment["job"] / "task.log").read_text()


def test_native_image_workers_use_one_itk_thread(deployment: dict[str, Any]) -> None:
    manifest_path = deployment["manifest"]
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime"]["command"] = [
        "{python}",
        "-c",
        (
            "import SimpleITK as itk,sys; from pathlib import Path; "
            "assert itk.ProcessObject.GetGlobalDefaultNumberOfThreads()==1; "
            "Path(sys.argv[1]).touch()"
        ),
        str(deployment["output"] / "thread-ok"),
    ]
    manifest_path.write_text(json.dumps(manifest))
    result = subprocess.run(
        deployment["argv"],
        env=deployment["env"],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (deployment["output"] / "thread-ok").exists(), (
        deployment["job"] / "task.log"
    ).read_text()


def native_command(deployment: dict[str, Any], script: str, arguments: list[str]) -> None:
    root, job = deployment["root"], deployment["job"]
    prefix = root / "native-environment"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin/python").symlink_to(sys.executable)
    executable = prefix / "bin/nnUNetv2_predict"
    executable.write_text(f"#!{sys.executable}\n" + script)
    executable.chmod(0o755)
    config_path = root / "deployment.json"
    config = json.loads(config_path.read_text())
    config["environment"] = str(prefix)
    config["limits"]["cpus"] = 3
    config_path.write_text(json.dumps(config))
    # This fixture tests the native broker, not model validation (covered by SEG-02 tests).
    # Meet the real admission contract; the synthetic CLI has no checkpoint to validate.
    deployment["manifest"].with_name("verify.py").write_text("pass\n")
    manifest = json.loads(deployment["manifest"].read_text())
    manifest["id"] = "segment.nnunet"
    manifest["runtime"]["command"] = [
        "{python}",
        "-c",
        (
            f"import os,sys; sys.path.insert(0, {str(RUNNER.parents[1])!r}); "
            "from plugins.nnunet.run import _spawn; "
            "child=_spawn('part',sys.argv[1:],dict(os.environ)); "
            "raise SystemExit(child.process.wait())"
        ),
        "nnUNetv2_predict",
        *arguments,
    ]
    deployment["manifest"].write_text(json.dumps(manifest))
    spec = json.loads((job / "job.json").read_text())
    spec["task"]["id"] = "segment.nnunet"
    (job / "job.json").write_text(json.dumps(spec))


def test_official_command_gets_own_proc_metadata_and_inherited_source_protection(
    deployment: dict[str, Any],
) -> None:
    root, job = deployment["root"], deployment["job"]
    source = root / "source/one.nii.gz"
    script = (
        "from pathlib import Path\nimport os, socket, sys, threading\n"
        "Path(f'/proc/self/task/{threading.get_native_id()}/comm').write_text('rw-native')\n"
        "source, output = map(Path, sys.argv[1:])\n"
        "try: source.write_text('changed')\n"
        "except PermissionError: pass\n"
        "else: raise AssertionError('source protection lost')\n"
        "try: socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "except PermissionError: pass\n"
        "else: raise AssertionError('network protection lost')\n"
        "assert os.environ['CUDA_VISIBLE_DEVICES']=='GPU-test'\n"
        "output.touch()\n"
    )
    native_command(deployment, script, [str(source), str(deployment["output"] / "native-ok")])
    result = subprocess.run(
        deployment["argv"],
        env=deployment["env"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (deployment["output"] / "native-ok").exists(), (job / "task.log").read_text()
    assert source.read_bytes() == b"synthetic"
    assert json.loads((job / "exit.json").read_text())["cleanup_verified"] is True


def wait_file(path: Path, process: subprocess.Popen[str], seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < deadline:
        assert process.poll() is None, process.communicate(timeout=2)
        time.sleep(0.02)
    assert path.exists(), f"timeout waiting for {path.name}"


def install_tree(deployment: dict[str, Any], native: bool = False) -> None:
    manifest_path = deployment["manifest"]
    manifest = json.loads(manifest_path.read_text())
    code = """
import os, signal, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
with (root / 'launches').open('a') as handle: handle.write('launch\\n')
child = subprocess.Popen([sys.executable, '-c',
    "import os,signal,sys,time; from pathlib import Path; "
    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)",
    str(root / 'child.pid')], start_new_session=True)
(root / 'parent.pid').write_text(str(os.getpid()))
time.sleep(60)
"""
    if native:
        native_command(deployment, code, [str(deployment["output"])])
        return
    manifest["runtime"]["command"] = ["{python}", "-c", code, str(deployment["output"])]
    manifest_path.write_text(json.dumps(manifest))


def alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].strip().split()[0] != "Z"
    except FileNotFoundError:
        return False


@pytest.mark.parametrize("crash_runner", [False, True])
@pytest.mark.parametrize("native", [False, True])
def test_cancel_and_runner_crash_recovery_reap_setsid_descendant(
    deployment: dict[str, Any],
    crash_runner: bool,
    native: bool,
) -> None:
    install_tree(deployment, native=native)
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    runners: list[subprocess.Popen[str]] = []
    try:
        first = subprocess.Popen(
            deployment["argv"],
            env=deployment["env"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        runners.append(first)
        wait_file(deployment["output"] / "child.pid", first)
        parent = int((deployment["output"] / "parent.pid").read_text())
        child = int((deployment["output"] / "child.pid").read_text())
        if crash_runner:
            first.kill()
            first.wait(5)
            assert alive(child), "hard runner crash unexpectedly lost the owned service"
            second = subprocess.Popen(
                deployment["argv"],
                env=deployment["env"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            runners.append(second)
        (deployment["job"] / "cancel").touch()
        last = runners[-1]
        stdout, stderr = last.communicate(timeout=25)
        assert last.returncode == 0, stdout + stderr
        assert not alive(parent) and not alive(child)
        assert (deployment["output"] / "launches").read_text().splitlines() == ["launch"]
        assert json.loads((deployment["job"] / "exit.json").read_text())["cleanup_verified"] is True
        assert sentinel.poll() is None, "unrelated sentinel was affected"
    finally:
        for process in runners:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        sentinel.terminate()
        sentinel.wait(5)
