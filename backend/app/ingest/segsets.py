"""Segmentation sets produced by task runs, joined into the derived index (ADR-0015, TSK-09).

A task run that outputs masks records them in `tasks/runs/{run_id}/masks.jsonl`, one line per
item `{item_id, ref, format, fp, labels}`. The index is derived (PRJ-10), so every rebuild and
every registration re-applies the masks of each `task` set in `project.json.segmentations`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.fsio import append_jsonl, iter_jsonl
from app.ingest.models import Item, VolumeRef
from app.projects.models import ProjectConfig

MASKS = "masks.jsonl"


def masks_path(project_dir: Path, run_id: str) -> Path:
    return project_dir / "tasks" / "runs" / run_id / MASKS


def record_masks(project_dir: Path, run_id: str, rows: Sequence[dict[str, Any]]) -> None:
    """API process only, under the project lock (BE-05)."""
    append_jsonl(masks_path(project_dir, run_id), rows)


def task_masks(project_dir: Path, cfg: ProjectConfig) -> dict[str, dict[str, VolumeRef]]:
    """item_id → seg_id → mask for every task-produced set (later lines win)."""
    out: dict[str, dict[str, VolumeRef]] = {}
    for seg in cfg.segmentations:
        if seg.producer is None:
            continue
        for row in iter_jsonl(masks_path(project_dir, seg.producer.run_id)):
            ref = VolumeRef(ref=row["ref"], format=row.get("format", "nifti"), fp=row.get("fp"))
            out.setdefault(str(row["item_id"]), {})[seg.seg_id] = ref
    return out


def apply_task_masks(items: Sequence[Item], masks: dict[str, dict[str, VolumeRef]]) -> None:
    """Attach task sets to items in place; the `imported` set is never replaced."""
    for it in items:
        extra = masks.get(it.item_id)
        if extra:
            it.masks = {**it.masks, **{k: v for k, v in extra.items() if k != "imported"}}
