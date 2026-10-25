"""Run inside the product image, on Docker or udocker, without host code binds.

Creates only synthetic data and an isolated API. The SIGKILL targets that API while its
worker is still queued. Active-pixel and cross-container crash matrices remain separate.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
API = "/api/v1"


def hashes(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                result[str(path.relative_to(root))] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    return result


def check_images(images: list[Path]) -> None:
    import nibabel as nib
    import numpy as np

    assert len(images) == 2, images
    for path in images:
        image = nib.load(path)
        assert isinstance(image, nib.Nifti1Image)
        pixels = np.asanyarray(image.dataobj)
        assert image.shape == (12, 10, 14)
        marker = np.argwhere(pixels == 2000)
        assert marker.shape == (1, 3)
        assert np.count_nonzero(pixels == -100) == pixels.size - 1
        # Independent physical oracle: LPS origin (-20,-30,100), spacing (.7,.9,2.5),
        # marker index (2,7,9). The converter's grouping/sorting helpers are not used.
        ras = image.affine @ np.array([*marker[0], 1.0])
        assert np.allclose(ras, [18.6, 23.7, 122.5, 1.0], atol=1e-5), ras


def run(evidence: Path) -> dict[str, Any]:
    if evidence.exists() and (not evidence.is_dir() or any(evidence.iterdir())):
        raise ValueError("Choose an empty evidence directory; existing workspaces are never reused")
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence.chmod(0o700)
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:12])
    threads = {
        key: "1"
        for key in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS",
            "ARROW_NUM_THREADS",
        )
    }
    os.environ.update(threads)
    from tools.dicom_fixtures import write_series

    data, workspace, derived, plugins, allocation = (
        evidence / name for name in ("data", "workspace", "derived", "plugins", "allocation")
    )
    for directory in (data, workspace, derived, plugins, allocation):
        directory.mkdir(mode=0o700)
    for index in (1, 2):
        write_series(data / str(index), patient_id=f"SMOKE{index}", seed="product-image-smoke")
    for path in sorted(data.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    data.chmod(0o555)
    before = hashes(data)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    token = uuid.uuid4().hex
    public_base = base + "/image-smoke-" + token
    marker = f"RW_DICOM_IMAGE_SMOKE={token}".encode()
    env = {
        **os.environ,
        **threads,
        "RW_DICOM_IMAGE_SMOKE": token,
        "PYTHONPATH": f"{REPO / 'backend'}:{REPO}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "WORKSPACE_ROOT": str(workspace),
        "ALLOWED_DATA_ROOTS": str(data),
        "ALLOWED_DERIVED_ROOTS": str(derived),
        "PLUGINS_ROOT": str(plugins),
        "HOST_ALLOCATION_ROOT": str(allocation),
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "PUBLIC_BASE_URL": public_base,
        "DICOM_MEMORY_MB": "1024",
        "DICOM_CPU_THREADS": "1",
        "JOB_WORKERS": "2",
    }
    # Ignore host proxy variables: every request belongs to this disposable loopback API.
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    process: subprocess.Popen[bytes] | None = None
    boots = 0

    def call(path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            base + path, data=None if body is None else json.dumps(body).encode()
        )
        if body is not None:
            request.add_header("Content-Type", "application/json")
        with http.open(request, timeout=10) as response:
            raw = response.read()
            return json.loads(raw) if "json" in response.headers.get("Content-Type", "") else raw

    def send(sig: signal.Signals) -> None:
        assert process is not None
        if process.poll() is not None:
            return
        fd = os.pidfd_open(process.pid)
        try:
            proc = Path("/proc") / str(process.pid)
            assert proc.stat().st_uid == os.getuid()
            assert marker in (proc / "environ").read_bytes().split(b"\0")
            assert str(REPO / "scripts/container_app.py").encode() in (
                proc / "cmdline"
            ).read_bytes().split(b"\0")
            signal.pidfd_send_signal(fd, sig)
        except ProcessLookupError:
            pass
        finally:
            os.close(fd)

    def stop() -> None:
        nonlocal process
        if process is None:
            return
        send(signal.SIGTERM)
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            send(signal.SIGKILL)
            process.wait(timeout=12)
        process = None

    def start() -> None:
        nonlocal process, boots
        with (evidence / f"api-{boots}.log").open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, str(REPO / "scripts/container_app.py")],
                cwd=REPO / "backend",
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        boots += 1
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            assert process.poll() is None, "Disposable API exited; inspect its evidence log"
            try:
                health = call(API + "/health")
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
                continue
            assert health["status"] == "ok"
            assert health["ui_config"]["public_base_url"] == public_base, "Refusing an unowned API"
            return
        raise TimeoutError("Disposable API health timed out; inspect its evidence log")

    def operation(oid: str) -> dict[str, Any]:
        value: dict[str, Any] = call(f"{API}/source-operations/{oid}")
        return value

    def wait(oid: str, ready: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        deadline = time.monotonic() + 60
        record: dict[str, Any] = {}
        while time.monotonic() < deadline:
            record = operation(oid)
            if ready(record):
                return record
            assert record["status"] not in {"failed", "completed_with_errors", "cleanup_pending"}, (
                record
            )
            time.sleep(0.1)
        raise TimeoutError(f"Operation did not reach the expected barrier: {record}")

    def control(oid: str, action: str) -> dict[str, Any]:
        record = operation(oid)
        for retry in range(2):
            try:
                value: dict[str, Any] = call(
                    f"{API}/source-operations/{oid}/{action}",
                    {
                        "expected_revision": record["revision"],
                        "expected_attempt": record["attempt"],
                    },
                )
                return value
            except urllib.error.HTTPError as error:
                if error.code != 409 or retry:
                    raise
                latest = operation(oid)
                assert latest["attempt"] == record["attempt"], (
                    "Control cannot follow a newer attempt"
                )
                record = latest
        raise AssertionError("Control was not acknowledged")

    lock_path = workspace / "plugins/dicom/execution.lock"
    lock_path.parent.mkdir(parents=True)
    try:
        with lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            start()
            created = call(
                API + "/source-operations",
                {
                    "path": str(data),
                    "purpose": "convert",
                    "prepare_plan": True,
                    "idempotency_key": "image-smoke-convert",
                    "name": "product-smoke",
                    "settings": {"phase_analyzer": False},
                },
            )
            oid = created["operation_id"]
            attempt = (
                workspace / "plugins/dicom/operations" / oid / "attempts" / str(created["attempt"])
            )
            deadline = time.monotonic() + 15
            while not (attempt / "reserved.json").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert (attempt / "reserved.json").exists() and not (attempt / "process.json").exists()
            send(signal.SIGKILL)
            assert process is not None
            process.wait(timeout=10)
            process = None
            start()
            interrupted = operation(oid)
            assert interrupted["status"] == "interrupted" and interrupted["cleanup_verified"]
            control(oid, "resume")
            control(oid, "cancel")
            wait(oid, lambda r: r["status"] == "cancelled" and r["cleanup_verified"])
            fcntl.flock(lock, fcntl.LOCK_UN)
        control(oid, "resume")
        ready = wait(oid, lambda r: r["stage"] == "ready" and r["status"] == "completed")
        call(
            f"{API}/source-operations/{oid}/convert",
            {
                "expected_revision": ready["revision"],
                "expected_attempt": ready["attempt"],
                "inventory_generation": ready["summary"]["generation"],
                "plan_attempt": ready["plan_attempt"],
            },
        )
        completed = wait(oid, lambda r: r["stage"] == "result" and r["status"] == "completed")
        native = completed["conversion_run"]
        assert native["cleanup_verified"] and native["conversion_time"]["basis"] == "complete"
        images = sorted(
            path
            for path in derived.rglob("*.nii.gz")
            if not any(part.startswith(".") for part in path.relative_to(derived).parts)
        )
        check_images(images)
        outputs = hashes(derived)
        opened = call(
            API + "/source-operations",
            {
                "path": str(data),
                "purpose": "open",
                "idempotency_key": "image-smoke-open",
            },
        )
        sid = opened["operation_id"]
        wait(sid, lambda r: r["stage"] == "opened" and r["status"] == "completed")
        session = call(f"{API}/source-operations/{sid}/open", {})
        assert len(session["items"]) == 2
        image_bytes = call(f"{API}/open/{sid}/items/0/image")
        stop()
        start()
        restored = operation(oid)
        assert (
            restored["conversion_run"]["run_id"] == native["run_id"]
            and restored["stage"] == "result"
        )
        assert call(f"{API}/open/{sid}")["items"] == session["items"]
        assert call(f"{API}/open/{sid}/items/0/image") == image_bytes
        assert len(call(API + "/task-runs")) == 1
        assert call(API + "/projects") == []
        assert hashes(data) == before and hashes(derived) == outputs
        report = {
            "uid": os.getuid(),
            "images": len(images),
            "operation_id": oid,
            "run_id": native["run_id"],
            "queued_api_sigkill_resume": True,
            "queued_cancel_resume": True,
            "native_cleanup_verified": True,
            "open_restored": True,
            "source_unchanged": True,
            "outputs_unchanged": True,
            "no_hidden_project": True,
            "gpu_compute": False,
            "scope": "Queued API crash; active-pixel and cross-container matrices remain separate",
        }
        (evidence / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
    finally:
        stop()
        for path in [data, *data.rglob("*")]:
            path.chmod(0o700 if path.is_dir() else 0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    root = args.evidence or Path(tempfile.mkdtemp(prefix="rw-dicom-image-smoke-"))
    print(json.dumps({"evidence": str(root), **run(root)}))


if __name__ == "__main__":
    main()
