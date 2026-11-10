"""Read-only queries over prepared source inventories and plans."""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from app.core.errors import JobConflict
from app.sources import detect as source_detect
from app.sources import formats
from app.sources.open_service import RETRY as OPEN_ACTIONS
from app.sources.open_service import guarded_source
from app.tasks.source_inventory import SourceInventory
from app.tasks.source_models import SourceOperation
from app.tasks.source_plans import SourcePlanPage, read_plan_page

if TYPE_CHECKING:
    from app.tasks.source_operations import SourceOperations


def require_inventory(record: SourceOperation) -> None:
    if record.summary.get("inventory_expired"):
        raise JobConflict(
            "The completed operation's inventory expired; start a new source operation",
            actions=["choose_another_path", "home"],
        )


def detection(
    operations: SourceOperations, operation: str, *, dicom_available: bool
) -> source_detect.DetectResult:
    """Bounded adapter hints from the completed inventory, without a rescan."""
    record = operations.get(operation)
    require_inventory(record)
    if (
        record.purpose != "discover"
        or record.status != "completed"
        or record.stage != "discovered"
        or not record.cleanup_verified
    ):
        raise JobConflict(
            "Finish source discovery before choosing an import adapter", actions=OPEN_ACTIONS
        )
    source = guarded_source(operations.guard, record.source)
    database = operations._dir(operation) / "inventory.sqlite"
    try:
        if not database.is_file():
            raise JobConflict("Prepared source inventory is missing")
        with SourceInventory(database, source) as inventory:
            summary = inventory.summary()
            if not summary["complete"] or summary["generation"] != record.summary.get("generation"):
                raise JobConflict("Prepared source inventory changed")
            inventory.check_reader()
            ignored: Counter[str] = Counter()
            for rel in inventory.rels("ignored"):
                name = Path(rel).name
                if name not in formats.SKIP_NAMES:
                    ignored[formats.extension(name)] += 1
            counts = {key: int(summary[key]) for key in ("nifti", "dicom", "npy")}
            counts["ignored"] = sum(ignored.values())
            count = counts["nifti"]
            positions = {
                index * count // min(count, source_detect.SAMPLE)
                for index in range(min(count, source_detect.SAMPLE))
            }
            sample = [
                rel for index, rel in enumerate(inventory.rels("nifti")) if index in positions
            ]
            meta_entry = None if inventory.single_file else inventory.entry("metadata.jsonl")
            has_meta = meta_entry is not None and not meta_entry["error"]
            return source_detect.from_facts(
                source,
                kind="file" if inventory.single_file else "folder",
                counts=counts,
                ignored=dict(ignored),
                nifti_sample=sample,
                has_meta=has_meta,
                truncated=False,
                dicom_available=dicom_available,
            )
    except (OSError, sqlite3.Error, JobConflict, ValueError) as exc:
        raise JobConflict(
            "Source inventory is unavailable or incompatible; discover it again",
            actions=OPEN_ACTIONS,
        ) from exc


def plan_page(
    operations: SourceOperations,
    operation: str,
    limit: int,
    cursor: str | None,
    action: Literal["convert", "skip"] | None = None,
) -> SourcePlanPage:
    record = operations.get(operation)
    require_inventory(record)
    if record.plan_attempt is None:
        if cursor:
            raise JobConflict("No plan is ready for this generation")
        return SourcePlanPage(items=[], total=0)
    return read_plan_page(
        operations._dir(operation) / "plans" / str(record.plan_attempt),
        limit=limit,
        cursor=cursor,
        action=action,
    )


def patient_ids(operations: SourceOperations, operation: str) -> set[str]:
    record = operations.get(operation)
    require_inventory(record)
    database = operations._dir(operation) / "inventory.sqlite"
    if not database.exists():
        return set()
    with SourceInventory(database, Path(record.source)) as inventory:
        return inventory.patient_ids()


def series_page(
    operations: SourceOperations, operation: str, limit: int, cursor: str | None
) -> dict[str, Any]:
    record = operations.get(operation)
    require_inventory(record)
    database = operations._dir(operation) / "inventory.sqlite"
    if not database.exists():
        return {"items": [], "total": 0, "next_cursor": None, "generation": None}
    with SourceInventory(database, Path(record.source)) as inventory:
        return inventory.page(limit=limit, cursor=cursor)
