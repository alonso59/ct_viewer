"""SRC-13 / BE-16: lazy Open-mode pixel reads use the same owned, budgeted executor."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.config import Settings
from app.core.ids import new_ulid
from app.tasks import protocol
from app.tasks.dicom_execution import run_dicom_job
from app.tasks.dicom_resources import require_pixel_budget


async def convert_volume(
    settings: Settings,
    root: str,
    files: list[str],
    dst: Path,
    *,
    expected_fingerprint: str | None = None,
) -> str | None:
    require_pixel_budget(settings)
    job = settings.workspace_root / ".scratch/open-executions" / new_ulid()
    protocol.write_job(
        job,
        {
            "operation": "open",
            "attempt": 1,
            "dicom_process_protocol": 1,
            "source": root,
            "files": files,
            "destination": str(dst),
            "expected_fingerprint": expected_fingerprint,
        },
    )
    outcome = await run_dicom_job(job, workspace=settings.workspace_root, settings=settings)
    if not outcome["cleanup_verified"]:
        return "Open conversion cleanup is pending; replacement execution is blocked"
    result = protocol.read_result(job) or {}
    error = result.get("error")
    if outcome["exit_code"] != 0 and error is None:
        error = "Native DICOM worker failed; review the configured memory budget"
    if (job / "allocation-exit.json").exists():
        shutil.rmtree(job)
    return str(error) if error is not None else None
