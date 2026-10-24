"""U1/J2: opt-in real API/supervisor browser acceptance with a CPU fixture and fake GPU telemetry.

Run after building frontend/dist and passing test-host. No CUDA, production workspace or model
is used. Node and browsers run only in the existing rw-browser-verification udocker container.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from tools.make_fixtures import DATASET, generate
from tools.nnunet_acceptance import sha_tree

REPO = Path(__file__).resolve().parents[2]
FIXTURE = """from pathlib import Path
import sys, time
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from plugins.protocol import Job
from plugins.threshold.run import _segment
job = Job(sys.argv[1])
for item in job.items:
    if item['item_id'] in job.skip: continue
    while not (job.dir / 'continue').exists():
        if job.cancelled() or (job.dir / 'pause').exists(): break
        time.sleep(0.05)
    if job.cancelled() or (job.dir / 'pause').exists(): break
    job.counts['items'] += 1
    job.item(item['item_id'], 'ok', _segment(job, item))
job.finish(status='paused' if (job.dir / 'pause').exists() else None)
"""


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(5)


def ready(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("acceptance API exited; inspect api.log")
        try:
            with urllib.request.urlopen(url + "/api/v1/health", timeout=1) as response:
                if json.load(response)["status"] == "ok":
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.1)
    raise TimeoutError("acceptance API health timed out")


def setup(root: Path) -> dict[str, Any]:
    for name in ("workspace", "derived", "models", "state", "tools", "plugins"):
        (root / name).mkdir(mode=0o700)
    generate(root / "source")
    plugins = root / "plugins"
    shutil.copytree(REPO / "plugins/threshold", plugins / "threshold")
    shutil.copyfile(REPO / "plugins/protocol.py", plugins / "protocol.py")
    (plugins / "__init__.py").touch()
    (plugins / "threshold/browser.py").write_text(FIXTURE)
    path = plugins / "threshold/task.json"
    task = json.loads(path.read_text())
    task["resources"]["gpu"] = "required"
    task["runtime"]["command"] = ["{python}", "browser.py", "{job_dir}"]
    path.write_text(json.dumps(task))
    nvidia = root / "tools/nvidia-smi"
    nvidia.write_text(
        '#!/bin/sh\ncase "$1" in\n'
        " --query-gpu=*) echo '0, GPU-browser, synthetic CPU fixture, 1000, 0, 0';;\nesac\n"
    )
    nvidia.chmod(0o700)
    config = {
        "deployment": 1,
        "backend": "server",
        "environment": str(Path(sys.executable).parent.parent),
        "workspace": str(root / "workspace"),
        "source_roots": [str(root / "source" / DATASET)],
        "model_roots": [str(root / "models")],
        "derived_roots": [str(root / "derived")],
        "state_dir": str(root / "state"),
        "gpu_pool": ["0"],
        "limits": {"cpus": 1, "memory_mb": 1024, "tasks": 64, "seconds": 180, "gpus": 1},
    }
    (root / "deployment.json").write_text(json.dumps(config))
    (root / "deployment.json").chmod(0o600)
    return {
        "root": str(root),
        "workspace": str(root / "workspace"),
        "source": str(root / "source" / DATASET),
        "derived": str(root / "derived"),
        "state": str(root / "state"),
    }


def main() -> int:
    if not (REPO / "frontend/dist/index.html").is_file():
        raise RuntimeError("build frontend/dist first")
    root = Path(tempfile.mkdtemp(prefix="rw-browser-host-"))
    fixture = setup(root)
    (root / "fixture.json").write_text(json.dumps(fixture))
    before = sha_tree(Path(fixture["source"]))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "WORKSPACE_ROOT": fixture["workspace"],
        "HOST_ALLOCATION_ROOT": fixture["state"],
        "DICOM_MEMORY_MB": "1024",
        "ALLOWED_DATA_ROOTS": fixture["source"],
        "ALLOWED_DERIVED_ROOTS": fixture["derived"],
        "PLUGINS_ROOT": str(root / "plugins"),
        "STATIC_ROOT": str(REPO / "frontend/dist"),
        "PUBLIC_BASE_URL": url,
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "PATH": f"{root / 'tools'}:{os.environ['PATH']}",
    }
    processes: list[subprocess.Popen[bytes]] = []
    with (root / "api.log").open("wb") as api_log, (root / "runner.log").open("wb") as log:

        def api_start() -> subprocess.Popen[bytes]:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                cwd=REPO / "backend",
                env=env,
                stdout=api_log,
                stderr=subprocess.STDOUT,
            )
            processes.append(process)
            ready(url, process)
            return process

        try:
            server = api_start()
            runner = subprocess.Popen(
                [
                    sys.executable,
                    str(REPO / "scripts/rw-runner.py"),
                    "--workspace",
                    fixture["workspace"],
                    "--plugins",
                    str(root / "plugins"),
                    "--deployment",
                    str(root / "deployment.json"),
                    "--poll",
                    "0.1",
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            processes.append(runner)
            browser = subprocess.Popen(
                [
                    "python3",
                    "udocker.py",
                    "run",
                    "--hostenv",
                    f"--volume={REPO}:{REPO}",
                    f"--volume={root}:{root}",
                    f"--workdir={REPO / 'frontend'}",
                    f"--env=RW_BROWSER_ACCEPTANCE={root / 'fixture.json'}",
                    f"--env=RW_HOST_URL={url}",
                    "--env=LIBGL_ALWAYS_SOFTWARE=1",
                    "--env=LP_NUM_THREADS=2",
                    "rw-browser-verification",
                    "xvfb-run",
                    "-a",
                    "npx",
                    "playwright",
                    "test",
                    "--config=playwright.host.config.ts",
                    "--reporter=line",
                ],
                cwd=REPO,
                env={**env, "UDOCKER_PYTHON": sys.executable},
            )
            processes.append(browser)
            deadline = time.monotonic() + 300
            while browser.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("host browser acceptance timed out")
                request = root / "restart.request"
                if request.exists():
                    stop(server)
                    server = api_start()
                    request.unlink()
                time.sleep(0.1)
            assert browser.returncode == 0, f"browser failed; retained evidence: {root}"
            assert before == sha_tree(Path(fixture["source"])), "source content changed"
            assert not (root / "state/lease.json").exists(), "test lease was not released"
            print(json.dumps({"passed": True, "gpu_compute": False, "workspace": str(root)}))
            return 0
        finally:
            for process in reversed(processes):
                stop(process)
            print(f"Acceptance evidence retained: {root}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
