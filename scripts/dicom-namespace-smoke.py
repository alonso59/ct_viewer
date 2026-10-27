"""TST-24/D17/D27: exercise the product image across two Docker PID namespaces."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

ACTOR = """
import asyncio, os, signal, sys
from pathlib import Path
from app.config import Settings
from app.core.fsio import atomic_write_json
from app.tasks import protocol
from app.tasks.dicom_execution import run_dicom_job
from app.tasks.dicom_process import process_identity

name, workspace_name, evidence = sys.argv[1:4]
root = Path(evidence)
workspace = root / workspace_name / 'workspace'
workspace.mkdir(parents=True, exist_ok=True)
job = workspace / name
source = root / 'source'
protocol.write_job(job, {
    'operation': 'open', 'attempt': 1, 'source': str(source),
    'files': sorted(p.name for p in source.iterdir()),
    'destination': str(root / 'derived' / (workspace_name + '.nii.gz')),
})
atomic_write_json(root / (name + '.driver.json'), process_identity(os.getpid()))
def started(pid):
    if name in {'A1', 'A2'}:
        os.kill(pid, signal.SIGSTOP)
    atomic_write_json(root / (name + '.started.json'), process_identity(pid))
settings = Settings(workspace_root=workspace, host_allocation_root=root / 'pool',
                    allowed_data_roots=str(source), allowed_derived_roots=str(root / 'derived'),
                    dicom_memory_mb=1024, dicom_cpu_threads=1, job_workers=1,
                    container_mode=True, _env_file=None)
outcome = asyncio.run(run_dicom_job(job, workspace=workspace, settings=settings,
    cancelled=lambda: (root / (name + '.cancel')).exists(), on_started=started))
atomic_write_json(root / (name + '.outcome.json'), outcome)
"""

SIGNAL = """
import json, os, signal, sys
from pathlib import Path
from app.tasks.dicom_process import process_identity
owner = json.loads(Path(sys.argv[1]).read_text())
fd = os.pidfd_open(owner['pid'])
try:
    assert process_identity(owner['pid']) == owner
    signal.pidfd_send_signal(fd, int(sys.argv[2]))
finally:
    os.close(fd)
"""


def run(image: str, root: Path) -> None:
    if not root.is_absolute() or root.exists() and any(root.iterdir()):
        raise ValueError("Choose a new absolute evidence directory")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    (root / "pool").mkdir(mode=0o700)
    (root / "derived").mkdir(mode=0o700)
    containers: list[str] = []
    actors: list[tuple[subprocess.Popen[str], TextIO]] = []

    def docker(*args: str) -> str:
        return subprocess.check_output(["docker", *args], text=True, timeout=60).strip()

    def execute(container: str, code: str, *args: str) -> str:
        return docker("exec", container, "python", "-c", code, *args)

    def wait_file(name: str) -> dict[str, Any]:
        deadline = time.monotonic() + 45
        path = root / name
        while time.monotonic() < deadline:
            if path.exists():
                record: dict[str, Any] = json.loads(path.read_text())
                return record
            time.sleep(0.05)
        raise TimeoutError(f"No acknowledgment: {name}")

    def start(container: str, name: str, workspace: str) -> subprocess.Popen[str]:
        log = (root / f"{name}.log").open("w")
        process = subprocess.Popen(
            ["docker", "exec", container, "python", "-c", ACTOR, name, workspace, "/evidence"],
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        actors.append((process, log))
        return process

    def waiting(name: str) -> None:
        wait_file(f"{name}.driver.json")
        progress = root / "B/workspace" / name / "progress.jsonl"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if progress.exists() and "waiting_for_resources" in progress.read_text():
                assert not (root / f"{name}.started.json").exists()
                return
            time.sleep(0.05)
        raise AssertionError(f"Foreign workspace did not wait: {name}")

    try:
        for label in ("A", "B"):
            name = f"rw-dicom-ns-{label.lower()}-{uuid4().hex[:12]}"
            docker(
                "run",
                "-d",
                "--init",
                "--name",
                name,
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-e",
                "PYTHONPATH=/app/backend:/app",
                "-e",
                "OMP_NUM_THREADS=1",
                "-e",
                "OPENBLAS_NUM_THREADS=1",
                "-e",
                "MKL_NUM_THREADS=1",
                "-e",
                "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=1",
                "-v",
                f"{root}:/evidence",
                image,
                "python",
                "-c",
                "from threading import Event;Event().wait()",
            )
            containers.append(name)
        a, b = containers
        namespaces = [execute(c, "import os;print(os.readlink('/proc/self/ns/pid'))") for c in containers]
        assert len(set(namespaces)) == 2, "Docker did not create distinct PID namespaces"
        execute(
            a,
            """
from pathlib import Path
from tools.dicom_fixtures import write_series
write_series(Path('/evidence/source'), shape=(5,4,12), marker=(2,1,3), seed='namespace-smoke')
""",
        )
        source = {p.name: p.read_bytes() for p in (root / "source").iterdir()}
        first = start(a, "A1", "A")
        owner = wait_file("A1.started.json")
        assert owner["namespace"] == namespaces[0]
        lease = (root / "pool/lease.json").read_bytes()
        queued = start(b, "B1", "B")
        waiting("B1")
        (root / "B1.cancel").touch()
        cancelled = wait_file("B1.outcome.json")
        assert cancelled["cleanup_verified"] and cancelled["cancelled"]
        assert queued.wait(timeout=10) == 0
        assert (root / "pool/lease.json").read_bytes() == lease
        execute(a, SIGNAL, "/evidence/A1.driver.json", str(signal.SIGKILL))
        assert first.wait(timeout=15) == 137
        execute(
            a,
            """
import json,time
from pathlib import Path
from app.tasks.dicom_process import group_running
owner=json.loads(Path('/evidence/A1.started.json').read_text())
deadline=time.monotonic()+10
while group_running(owner['group']) and time.monotonic()<deadline:time.sleep(.05)
assert not group_running(owner['group'])
""",
        )
        second = start(b, "B2", "B")
        waiting("B2")
        assert (root / "pool/lease.json").read_bytes() == lease
        resumed = start(a, "A2", "A")
        wait_file("A2.started.json")
        assert not (root / "B2.started.json").exists()
        execute(a, SIGNAL, "/evidence/A2.started.json", str(signal.SIGCONT))
        for name, process in (("A2", resumed), ("B2", second)):
            result = wait_file(f"{name}.outcome.json")
            assert result["cleanup_verified"] and result["exit_code"] == 0, result
            assert process.wait(timeout=15) == 0
        assert not (root / "pool/lease.json").exists()
        execute(
            a,
            """
from pathlib import Path
import nibabel as nib,numpy as np
for path in Path('/evidence/derived').glob('*.nii.gz'):
    image=nib.load(path);pixels=np.asanyarray(image.dataobj)
    assert image.shape==(5,4,12)
    marker,=np.argwhere(pixels==2000)
    np.testing.assert_allclose(image.affine@[*marker,1],[18.6,29.1,107.5,1],atol=1e-4)
""",
        )
        assert len(list((root / "derived").glob("*.nii.gz"))) == 2
        assert source == {p.name: p.read_bytes() for p in (root / "source").iterdir()}
        assert all(docker("inspect", "-f", "{{.State.Running}}", c) == "true" for c in containers)
        (root / "acceptance.json").write_text(
            json.dumps(
                {
                    "image": image,
                    "namespaces": namespaces,
                    "source_unchanged": True,
                    "foreign_recovery_blocked": True,
                    "owner_recovery_completed": True,
                    "cancelled_waiter_launched": False,
                    "native_outputs": 2,
                    "gpu_compute": False,
                },
                indent=2,
            )
            + "\n"
        )
    finally:
        for container in containers:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30, check=False)
        for process, log in actors:
            if process.poll() is None:
                process.wait(timeout=15)
            log.close()


if __name__ == "__main__":
    run(sys.argv[1], Path(sys.argv[2]))
