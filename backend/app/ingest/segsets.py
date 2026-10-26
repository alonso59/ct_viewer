"""Rejoin active task and manual segmentation manifests into the derived index."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.fsio import append_jsonl, iter_jsonl
from app.ingest.models import Item, VolumeRef
from app.projects.models import ProjectConfig

MASKS = "masks.jsonl"
IMPORTS = Path("segmentations") / "imports"


def masks_path(project_dir: Path, run_id: str) -> Path:
    return project_dir / "tasks" / "runs" / run_id / MASKS


def record_masks(project_dir: Path, run_id: str, rows: Sequence[dict[str, Any]]) -> None:
    """API process only, under the project lock."""
    path = masks_path(project_dir, run_id)
    seen = {(row["item_id"], row["ref"]) for row in iter_jsonl(path)}
    fresh: list[dict[str, Any]] = []
    for row in rows:
        key = row["item_id"], row["ref"]
        if key not in seen:
            fresh.append(row)
            seen.add(key)
    if fresh:
        append_jsonl(path, fresh)


def apply_registered_masks(items: Sequence[Item], project_dir: Path, cfg: ProjectConfig) -> None:
    """Apply active task/manual manifests; later rows win without changing source volumes."""
    by_id = {item.item_id: item for item in items}
    for seg in cfg.segmentations:
        if not seg.active:
            continue
        if seg.producer is not None:
            path = masks_path(project_dir, seg.producer.run_id)
        elif seg.artifact_id is not None:
            path = project_dir / IMPORTS / seg.artifact_id / MASKS
        else:
            continue
        for row in iter_jsonl(path):
            item = by_id.get(str(row["item_id"]))
            if item is None:
                continue
            fmt = row.get("format", "nifti")
            item.masks[seg.seg_id] = VolumeRef(
                ref=row["ref"],
                format=fmt,
                fp=row.get("fp"),
                labels=row.get("labels") if fmt == "nifti_dir" else None,
            )
            if seg.seg_id == "imported":
                item.labels_present = list(row.get("labels_present", []))
