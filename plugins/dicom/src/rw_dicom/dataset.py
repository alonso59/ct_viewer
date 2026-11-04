"""Dataset artifacts written identically by ct_viewer workspace runs and `rw-dicom` (DCM-14/28/34).

A dataset folder holds `metadata.jsonl` (paths relative to the folder), `nifti/`, `sidecars/`,
`diagnostics.jsonl`, `summary.json`, `annotations.jsonl` and one manifest: `dataset.json` once
every selected series is converted (complete and sealed), else `dataset.incomplete.json`, which
readers that predate it ignore. Every file is replaced atomically and fsynced, manifest last.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from rw_dicom import pipeline
from rw_dicom.durable import sync_dir, utc_now, write_json_atomic, write_jsonl
from rw_dicom.settings import settings_hash, task_manifest

DATASET_JSON = "dataset.json"
INCOMPLETE_JSON = "dataset.incomplete.json"


def relative_rows(rows: list[dict[str, Any]], nifti_dir: str = "nifti") -> None:
    """Rows of a dataset imported as-is: images and sidecars relative to its folder."""
    for row in rows:
        row["relative_path"] = f"{nifti_dir}/{row.get('filename', '')}"
        if row.get("dicom_sidecar"):
            row["dicom_sidecar"] = f"sidecars/{row['filename']}.dicom.json"


def is_complete(result: pipeline.Result, cancelled: bool) -> bool:
    counts = result.counts
    return not cancelled and not counts["failed"] and not counts["pending"] and result.resource_wait is None


def manifest(
    *,
    name: str,
    run_id: str | None,
    phase_run_id: str | None,
    source: Path,
    settings: dict[str, Any],
    result: pipeline.Result,
) -> dict[str, Any]:
    task = task_manifest()
    return {
        "dataset": 1,
        "name": name,
        "task": {"id": task["id"], "version": pipeline.VERSION},
        "run_id": run_id,
        "phase_run_id": phase_run_id,
        "source": str(source),
        "settings": settings,
        "settings_hash": settings_hash(task["id"], task["version"], settings),
        "created_at": utc_now(),
        "counts": result.counts,
        "units_by_versions": result.units_by_versions,
    }


def write(
    out_dir: Path,
    *,
    rows: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    summary: dict[str, Any],
    annotations: list[dict[str, Any]] | None = None,
    dataset: dict[str, Any] | None = None,
    complete: bool = False,
    metadata_name: str = "metadata.jsonl",
) -> None:
    """Rows, diagnostics and summary; for a dataset also annotations and its manifest."""
    write_jsonl(out_dir / metadata_name, rows)
    write_jsonl(out_dir / "diagnostics.jsonl", diagnostics)
    write_json_atomic(out_dir / "summary.json", {**summary, "complete": complete})
    if dataset is None:
        return
    write_jsonl(out_dir / "annotations.jsonl", annotations or [])
    if complete:
        write_json_atomic(out_dir / DATASET_JSON, dataset)
        with contextlib.suppress(FileNotFoundError):
            (out_dir / INCOMPLETE_JSON).unlink()
            sync_dir(out_dir)
    else:
        write_json_atomic(out_dir / INCOMPLETE_JSON, {**dataset, "complete": False})
