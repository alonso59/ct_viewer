"""TST-10/22, ADR-0035: reproducible product-image lifecycle check on disposable data."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_product_smoke_runs_real_api_crash_resume_conversion_and_open(tmp_path: Path) -> None:
    backend = Path(__file__).resolve().parents[1]
    evidence = tmp_path / "evidence"
    result = subprocess.run(
        [sys.executable, "-m", "tools.dicom_image_smoke", "--evidence", str(evidence)],
        cwd=backend,
        env={**os.environ, "PYTHONPATH": f"{backend}:{backend.parent}"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((evidence / "result.json").read_text())
    assert report["images"] == 2
    for key in (
        "queued_api_sigkill_resume",
        "queued_cancel_resume",
        "native_cleanup_verified",
        "open_restored",
        "source_unchanged",
        "outputs_unchanged",
        "no_hidden_project",
    ):
        assert report[key] is True, key
    assert report["gpu_compute"] is False
    assert report["uid"] == os.getuid()


def test_product_smoke_refuses_an_existing_nonempty_workspace(tmp_path: Path) -> None:
    backend = Path(__file__).resolve().parents[1]
    sentinel = tmp_path / "do-not-touch"
    sentinel.write_text("existing workspace")
    result = subprocess.run(
        [sys.executable, "-m", "tools.dicom_image_smoke", "--evidence", str(tmp_path)],
        cwd=backend,
        env={**os.environ, "PYTHONPATH": f"{backend}:{backend.parent}"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "empty evidence" in result.stderr
    assert sentinel.read_text() == "existing workspace"
    assert list(tmp_path.iterdir()) == [sentinel]
