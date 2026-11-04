"""ct_viewer's view of the converter's durable inventory (`rw_dicom.inventory`).

Adds paged series reads, the aggregate inventory budget and problem+json errors; the inventory
itself (schema, scanning, reuse, series) lives in the converter package.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from rw_dicom import inventory as core

from app.core.cursors import decode_cursor, encode_cursor
from app.core.errors import JobConflict, NotFound, Problem, SourceMissing, ValidationProblem

PROBLEMS: dict[str, type[Problem]] = {
    "conflict": JobConflict,
    "not_found": NotFound,
    "missing": SourceMissing,
    "invalid": ValidationProblem,
}


class InventorySeries(BaseModel):
    key: str
    directory: str
    uid: str
    n_files: int
    source_bytes: int
    first_rel: str


class InventoryPage(BaseModel):
    items: list[InventorySeries]
    next_cursor: str | None = None
    generation: str | None = None
    total: int


def inventory_limit(root: Path, target: Path, per_mb: int, total_mb: int) -> int:
    """Allocate the sole writer's SQLite allowance while execution.lock is held."""
    if target.name != "inventory.sqlite" or not target.parent.is_relative_to(root):
        raise ValidationProblem("Inventory budget needs a managed operation inventory")
    others = 0
    directories = {path.parent for path in root.glob("*/inventory.sqlite*")}
    for directory in directories:
        if directory.is_symlink():
            raise JobConflict("Inventory state contains an unsafe directory")
        if directory == target.parent:
            continue
        size = 0
        for name in ("inventory.sqlite", "inventory.sqlite-wal", "inventory.sqlite-shm"):
            path = directory / name
            try:
                if path.is_symlink():
                    raise JobConflict("Inventory state contains an unsafe database file")
                size += path.stat(follow_symlinks=False).st_size
            except FileNotFoundError:
                pass
        # A read-only connection may recreate its 32 KiB SQLite shared-memory index.
        others += size + 64 * 1024
    remaining = total_mb * 1024**2 - others
    allowance = min(per_mb, remaining // 1024**2)
    if allowance < 1:
        raise ValidationProblem(
            "The aggregate inventory budget is exhausted; retain recoverable work and increase "
            "DICOM_INVENTORY_TOTAL_MB before resuming",
            actions=["configure:DICOM_INVENTORY_TOTAL_MB"],
        )
    return allowance


def checked_folders(source: Path, folders: Sequence[str]) -> list[str]:
    """Validated top-level folder scope in the converter's patient order (case-insensitive)."""
    try:
        return core.checked_folders(source, folders)
    except ValueError as exc:
        raise ValidationProblem(str(exc)) from None


class SourceInventory(core.SourceInventory):
    def _error(self, kind: str, message: str) -> Exception:
        return PROBLEMS[kind](message)

    def page(self, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        self.db.execute("SAVEPOINT inventory_page")
        try:
            return self._page(limit=limit, cursor=cursor)
        finally:
            self.db.execute("RELEASE inventory_page")

    def _page(self, *, limit: int, cursor: str | None) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise ValidationProblem("Inventory page size must be in 1..500")
        offset = decode_cursor(cursor, self.generation)
        rows = self.db.execute(
            "SELECT d.rel AS directory, s.uid, s.key, COUNT(*) AS n_files, "
            "SUM(f.size) AS source_bytes, MIN(f.name) AS first_name FROM files f "
            "JOIN directories d ON f.directory_id=d.id JOIN series s ON s.id=f.series_id "
            "WHERE f.kind='dicom' AND d.complete=1 GROUP BY f.series_id "
            "ORDER BY d.rel, s.uid LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = self.summary()["series"]
        items = [
            {
                "key": row["key"],
                "directory": row["directory"],
                "uid": row["uid"],
                "n_files": row["n_files"],
                "source_bytes": row["source_bytes"],
                "first_rel": self._rel(row["directory"], row["first_name"]),
            }
            for row in rows
        ]
        nxt = None
        if offset + len(items) < total:
            nxt = encode_cursor(self.generation, offset + len(items))
        return {"items": items, "next_cursor": nxt, "total": total, "generation": self.generation}
