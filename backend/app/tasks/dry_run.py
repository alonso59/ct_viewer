"""Source-task dry runs (DCM-06, TSK-05) shared by project and workspace estimates (TSK-13).

A converter source with no DICOM, or a dry run that finds no series, is refused with the cause
and next steps instead of "completing" an empty dataset (SRC-11, UI-18, AUD-A2-07).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Final

from app.core.errors import UnsupportedFormat
from app.sources import formats
from app.tasks.models import SeriesPlan, TaskEstimate

DICOM_CONVERT: Final = "dicom.convert"
MAX_PLAN_ROWS: Final = 1000


def _no_dicom(path: Path) -> UnsupportedFormat | None:
    s = formats.scan(path.parent, [path.name]) if path.is_file() else formats.scan(path)
    if s.files["dicom"]:
        return None
    n_nifti = len(s.files["nifti"])
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
    return TaskEstimate(
        n_units=selected,
        n_skipped=n_series - selected,
        seconds_per_item=None,
        estimated_total_s=None,
        output_bytes=int(est.get("nifti_gz_estimated_bytes", 0)) or None,
        basis="sample",
        sample_errors=[str(result["error"])] if result.get("error") else [],
        detail={**est, "scan_s": round(scan_s, 3)},
        series=rows[:MAX_PLAN_ROWS],
        series_truncated=len(rows) > MAX_PLAN_ROWS,
    )
