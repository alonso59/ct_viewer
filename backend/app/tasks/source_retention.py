"""Expiry of completed DICOM inventories and plan caches."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.errors import (
    Problem,
)
from app.core.fsio import atomic_write_json
from app.core.ids import is_ulid, utc_now
from app.core.locks import FileLock, LockHeldError
from app.tasks.source_inventory import SourceInventory

if TYPE_CHECKING:
    pass

if TYPE_CHECKING:
    from app.tasks.source_operations import SourceOperations


async def prune_inventories(operations: SourceOperations) -> int:
    """Expire completed history only; never reclaim unfinished work to make space."""
    if not operations.root.exists():
        return 0
    execution = FileLock(operations.root.parent / "execution.lock")
    try:
        execution.acquire()
    except LockHeldError:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=operations.settings.dicom_retention_days)
    try:
        removed = 0
        for directory in operations.root.iterdir():
            removed += await _expire_inventory(operations, directory, cutoff)
        return removed
    finally:
        execution.release()


async def _expire_inventory(
    operations: SourceOperations, directory: Path, cutoff: datetime
) -> bool:
    if not is_ulid(directory.name) or directory.is_symlink():
        return False
    try:
        record = operations.get(directory.name)
    except (OSError, Problem):
        return False
    expired = directory / "inventory-expired.json"
    if (
        expired.exists()
        and not any(directory.glob("inventory.sqlite*"))
        and not any((directory / "plans").glob("*/*.json"))
    ):
        return False
    try:
        age = datetime.fromisoformat(record.updated_at.replace("Z", "+00:00"))
        if not expired.exists() and age >= cutoff:
            return False
    except (TypeError, ValueError):
        return False
    lock = operations.locks(f"_source_operation:{record.operation_id}")
    if lock.locked():
        return False
    async with lock:
        current = await operations.view(record.operation_id)
        if current.status != "completed" or not current.cleanup_verified or current.error:
            return False
        if current.purpose == "open" and not (directory / "open-closed.json").is_file():
            return False
        if current.import_context is not None and current.import_context.step != "index":
            return False
        if current.phase_run is not None and current.phase_run.status != "completed":
            return False
        lease = FileLock(directory / "inventory-use.lock")
        try:
            lease.acquire()
        except LockHeldError:
            return False
        try:
            if current.purpose == "open" and not (directory / "open-closed.json").is_file():
                return False
            database = directory / "inventory.sqlite"
            if (
                database.is_file()
                and not expired.exists()
                and not _checkpointed(database, record.source)
            ):
                return False
            atomic_write_json(
                expired,
                {"expired_at": utc_now(), "generation": current.summary.get("generation")},
            )
            for name in ("inventory.sqlite-wal", "inventory.sqlite-shm", "inventory.sqlite"):
                path = directory / name
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            for path in (directory / "plans").glob("*/*.json"):
                if (
                    not path.is_symlink()
                    and path.is_file()
                    and path.resolve().is_relative_to(directory.resolve())
                ):
                    path.unlink()
            return True
        finally:
            lease.release()


def _checkpointed(database: Path, source: str) -> bool:
    try:
        with SourceInventory(database, Path(source)) as inventory:
            inventory.db.execute("PRAGMA busy_timeout=0")
            return not inventory.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
    except (OSError, sqlite3.Error, Problem):
        return False
