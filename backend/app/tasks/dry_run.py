"""Source-task dry runs (DCM-06, TSK-05) shared by project and workspace estimates (TSK-13).

A converter source with no DICOM, or a dry run that finds no series, is refused with the cause
and next steps instead of "completing" an empty dataset (SRC-11, UI-18, AUD-A2-07).
A client may name its dry run (`progress_id`) to poll where it is and to cancel it (DCM-06).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel

from app.core.errors import JobConflict, NotFound, UnsupportedFormat, ValidationProblem
from app.core.ids import new_ulid
from app.sources import formats
from app.tasks import protocol
from app.tasks.models import ConversionTimeEstimate, SeriesPlan, TaskEstimate

DICOM_CONVERT: Final = "dicom.convert"
MAX_PLAN_ROWS: Final = 1000


def _any_dicom(root: Path) -> bool:
    """Stops at the first DICOM file (the full scan below is only for the refusal's counts)."""
    for cur, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if not f.startswith(".") and formats.classify(Path(cur) / f) == "dicom":
                return True
    return False


def _no_dicom(path: Path) -> UnsupportedFormat | None:
    if path.is_dir() and _any_dicom(path):
        return None
    s = formats.scan(path.parent, [path.name]) if path.is_file() else formats.scan(path)
    if s.files["dicom"]:
        return None
    return no_dicom_problem(path, len(s.files["nifti"]))


def no_dicom_problem(path: Path, n_nifti: int) -> UnsupportedFormat:
    """Use the same refusal/actions for synchronous and persisted background plans."""
    found = f"{n_nifti} NIfTI files found" if n_nifti else "no NIfTI files either"
    actions = ["open", "import_as:nifti-files"] if n_nifti else []
    return UnsupportedFormat(
        f"No DICOM files in {path.name or path}; {found}",
        actions=[*actions, "choose_another_path"],
    )


async def require_dicom(task_id: str, source: Path) -> None:
    """The converter needs DICOM files under its source (DCM-01); other tasks pass."""
    if task_id != DICOM_CONVERT:
        return
    problem = await asyncio.to_thread(_no_dicom, source)
    if problem is not None:
        raise problem


def estimate_of(result: dict[str, Any], scan_s: float, source: Path) -> TaskEstimate:
    """The task's `result.json` of a dry run → TSK-05 estimate with one row per series."""
    raw = result.get("estimate")
    est: dict[str, Any] = raw if isinstance(raw, dict) else {}
    plan = est.pop("series_plan", None)
    rows = [SeriesPlan.model_validate(r) for r in plan] if isinstance(plan, list) else []
    n_series = int(est.get("series", 0))
    if n_series == 0 and not result.get("error"):
        raise UnsupportedFormat(
            f"No convertible DICOM series in {source.name or source}: the headers could not "
            "be read, or it holds only DICOM SEG (DCM-11)",
            actions=["choose_another_path"],
        )
    selected = int(est.get("selected", 0))
    timing = (
        ConversionTimeEstimate.model_validate(result["conversion_time"])
        if result.get("conversion_time")
        else None
    )
    seconds = timing.estimated_s if timing else None
    return TaskEstimate(
        n_units=selected,
        n_skipped=n_series - selected,
        seconds_per_item=seconds / selected if seconds is not None and selected else None,
        estimated_total_s=seconds,
        output_bytes=int(est.get("nifti_gz_estimated_bytes", 0)) or None,
        basis="sample" if timing and timing.basis == "history" else "unknown",
        conversion_time=timing,
        sample_errors=[str(result["error"])] if result.get("error") else [],
        detail={**est, "scan_s": round(scan_s, 3)},
        series=rows[:MAX_PLAN_ROWS],
        series_truncated=len(rows) > MAX_PLAN_ROWS,
    )


# -- named dry runs: progress and cancel (DCM-06) --------------------------------------------

PROGRESS_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
TAIL_BYTES: Final = 16_384


class EstimateProgress(BaseModel):
    """The last `stage` line of a running dry run (`listing` | `reading` | `planning`)."""

    stage: str | None = None
    done: int = 0
    total: int = 0


def _estimates(workspace_root: Path) -> Path:
    return workspace_root / ".scratch" / "estimates"


def _named(workspace_root: Path, progress_id: str) -> Path:
    if not PROGRESS_ID.match(progress_id):
        raise ValidationProblem("progress_id: 8-64 letters, digits, '-' or '_'")
    return _estimates(workspace_root) / progress_id


def job_dir(workspace_root: Path, progress_id: str | None) -> Path:
    """Makes the dry run's scratch job folder (the caller removes it); a named one can be
    polled from now on, also while the source is still being checked for DICOM."""
    d = (
        _estimates(workspace_root) / new_ulid()
        if progress_id is None
        else _named(workspace_root, progress_id)
    )
    d.parent.mkdir(parents=True, exist_ok=True)
    try:
        d.mkdir()
    except FileExistsError:
        raise JobConflict(f"A dry run {progress_id} is already running") from None
    return d


def progress(workspace_root: Path, progress_id: str) -> EstimateProgress:
    d = _named(workspace_root, progress_id)
    if not d.is_dir():
        raise NotFound(f"No running dry run {progress_id} (finished, cancelled or not started)")
    try:
        with (d / protocol.PROGRESS).open("rb") as fh:
            fh.seek(max(0, fh.seek(0, os.SEEK_END) - TAIL_BYTES))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except FileNotFoundError:
        return EstimateProgress()
    for raw in reversed(lines):
        try:
            line = json.loads(raw)
        except ValueError:
            continue  # a partial first or last line
        if isinstance(line, dict) and line.get("t") == "stage":
            return EstimateProgress(
                stage=str(line.get("stage") or ""),
                done=int(line.get("done") or 0),
                total=int(line.get("total") or 0),
            )
    return EstimateProgress()


def cancel(workspace_root: Path, progress_id: str) -> None:
    """Asks the dry run to stop between folders or series; its request then returns early."""
    d = _named(workspace_root, progress_id)
    if d.is_dir():
        protocol.request_cancel(d)
