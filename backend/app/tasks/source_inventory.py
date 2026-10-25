"""DCM-15/16: bounded durable header inventory; complete folders become browsable series.

SQLite is a managed workspace artifact. It is never created in the input root. Header facts
are committed in batches and reused after interruption; pixel conversion has separate commits.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from pydicom.dataset import Dataset

from app.core.cursors import decode_cursor, encode_cursor
from app.core.errors import JobConflict, NotFound, SourceMissing, ValidationProblem
from app.core.fsio import workspace_database
from app.core.ids import new_ulid

if TYPE_CHECKING:
    from plugins.dicom import scan as dicom_scan

VERSION = 1
BATCH_SIZE = 64
NON_IMAGES = {".txt", ".csv", ".json", ".jsonl", ".yaml", ".yml", ".npz"}


def scanner_identity() -> str:
    import pydicom
    from plugins.dicom import files, scan

    assert scan.__file__ is not None and files.__file__ is not None
    contract = {
        "scanner": scan.INVENTORY_VERSION,
        "tags": scan.SCAN_TAGS,
        "header_bytes": scan.MAX_HEADER_BYTES,
        "reader": pydicom.__version__,
        "code": [
            hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in (scan.__file__, files.__file__)
        ],
    }
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()


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


class SourceInventory:
    def __init__(self, path: Path, root: Path) -> None:
        self.source = root.resolve()
        self.single_file = self.source.is_file()
        self.root = self.source.parent if self.single_file else self.source
        self._changed = False
        self.path = path
        self._scanner = scanner_identity()
        if path.resolve().is_relative_to(self.root):
            raise ValidationProblem("An inventory must be stored outside its source root")
        self.db = workspace_database(path)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS directories (rel TEXT PRIMARY KEY, "
            "complete INTEGER NOT NULL);"
            "CREATE TABLE IF NOT EXISTS files (rel TEXT PRIMARY KEY, directory TEXT NOT NULL, "
            "signature TEXT NOT NULL, kind TEXT NOT NULL, uid TEXT NOT NULL, "
            "header TEXT NOT NULL, size INTEGER NOT NULL, error TEXT NOT NULL, "
            "series_key TEXT NOT NULL);"
            "CREATE INDEX IF NOT EXISTS series_members ON files(directory, uid, kind);"
            "CREATE INDEX IF NOT EXISTS series_keys ON files(series_key);"
            "CREATE INDEX IF NOT EXISTS file_errors ON files(error) WHERE error != '';"
        )
        existing_root = self._get("root")
        if existing_root is not None and existing_root != str(self.source):
            self.db.close()
            raise JobConflict("Inventory belongs to a different source")
        if existing_root is not None and self._get("single_file") is not None:
            self.single_file = self._get("single_file") == "1"
            self.root = self.source.parent if self.single_file else self.source
            if path.resolve().is_relative_to(self.root):
                self.db.close()
                raise ValidationProblem("An inventory must be stored outside its source root")
        if existing_root is None:
            for key, value in {
                "root": str(self.source),
                "single_file": "1" if self.single_file else "0",
                "version": str(VERSION),
                "generation": new_ulid(),
                "complete": "0",
                "limited": "0",
                "walk_errors": "0",
            }.items():
                self._set(key, value)
            self.db.commit()
        elif self._get("version") != str(VERSION):
            self.db.close()
            raise JobConflict("Inventory version is incompatible; discover this source again")

    def __enter__(self) -> SourceInventory:
        return self

    def __exit__(self, *args: Any) -> None:
        self.db.close()

    def _get(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else None

    def _set(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    @property
    def generation(self) -> str:
        return str(self._get("generation"))

    def _change(self) -> None:
        if not self._changed:
            self._set("generation", new_ulid())
            self._changed = True

    def _record(self, path: Path) -> str:
        from plugins.dicom import scan as dicom_scan

        rel = path.relative_to(self.root).as_posix()
        directory = path.parent.relative_to(self.root).as_posix()
        signature, kind, uid, header, size, error = "", "ignored", "", "", 0, ""
        try:
            st = path.stat(follow_symlinks=False)
            signature = json.dumps(
                [self._scanner, st.st_size, st.st_mtime_ns, st.st_dev, st.st_ino]
            )
            previous = self.db.execute(
                "SELECT signature, error, kind FROM files WHERE rel=?", (rel,)
            ).fetchone()
            if previous is not None and previous[0] == signature and not previous[1]:
                return str(previous[2])
            ext = path.suffix.lower()
            if ext in (".nii", ".gz") and (ext == ".nii" or path.name.lower().endswith(".nii.gz")):
                kind = "nifti"
            elif ext == ".npy":
                kind = "npy"
            elif ext not in NON_IMAGES:
                found = dicom_scan.image_info(path, self.root)
                if found is not None:
                    ds, size = found
                    kind, uid, header = "dicom", str(ds.SeriesInstanceUID), ds.to_json()
        except Exception as exc:
            error = type(exc).__name__
        self._change()
        self.db.execute(
            "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rel, directory, signature, kind, uid, header, size, error, self._key(directory, uid)),
        )
        self.db.execute("UPDATE directories SET complete=0 WHERE rel=?", (directory,))
        return kind

    def scan(
        self,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        max_files: int | None = None,
        batch_size: int = BATCH_SIZE,
        max_bytes: int = 512 * 1024**2,
        on_progress: Callable[[dict[str, int]], None] | None = None,
    ) -> dict[str, Any]:
        """Resume valid batches; complete becomes true only after a successful whole traversal."""
        try:
            return self._scan(
                cancelled=cancelled,
                max_files=max_files,
                batch_size=batch_size,
                max_bytes=max_bytes,
                on_progress=on_progress,
            )
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode != sqlite3.SQLITE_FULL:
                raise
            self.db.rollback()
            self._changed = False
            return self._limited("inventory_bytes")

    def _scan(
        self,
        *,
        cancelled: Callable[[], bool],
        max_files: int | None,
        batch_size: int,
        max_bytes: int,
        on_progress: Callable[[dict[str, int]], None] | None,
    ) -> dict[str, Any]:
        from plugins.dicom import files as source_files

        if not self.source.exists():
            raise SourceMissing("Source unavailable; restore it before discovery")
        if not 1 <= batch_size <= 512 or max_bytes < 1024**2:
            raise ValidationProblem("Inventory needs a 1..512 batch size and at least 1 MiB")
        self._changed = False
        self._set("complete", "0")
        self._set("limited", "0")
        self._set("limit_reason", "")
        self.db.commit()
        # Leave room for the WAL, SQLite's shared-memory index and a bounded transaction.
        # Cap pages as well as checkpointing: a large header must not bypass the quota.
        page_size = int(self.db.execute("PRAGMA page_size").fetchone()[0])
        pages = max_bytes // (4 * page_size)
        actual_pages = self.db.execute(f"PRAGMA max_page_count={pages}").fetchone()[0]
        self.db.execute(f"PRAGMA cache_size=-{max(64, max_bytes // 4096)}")
        self.db.execute("PRAGMA wal_autocheckpoint=0")
        if actual_pages > pages or not self._checkpoint(max_bytes):
            return self._limited("inventory_bytes")
        self.db.execute("CREATE TEMP TABLE IF NOT EXISTS visited (rel TEXT PRIMARY KEY)")
        self.db.execute("DELETE FROM visited")
        seen = 0
        dicom_count = series_count = 0
        errors: list[OSError] = []
        stopped = False
        self.db.commit()
        candidates = (
            iter([(self.root, [self.source])])
            if self.single_file
            else source_files.folders(self.root, errors.append)
        )
        for folders, (directory, paths) in enumerate(candidates, 1):
            if cancelled():
                stopped = True
                break
            folder = directory.relative_to(self.root).as_posix()
            self.db.execute("INSERT OR IGNORE INTO directories VALUES (?, 0)", (folder,))
            if on_progress is not None:
                on_progress(
                    {
                        "folders": folders,
                        "files": seen,
                        "dicom": dicom_count,
                        "series": series_count,
                    }
                )
            for path in paths:
                if cancelled() or (max_files is not None and seen >= max_files):
                    stopped = True
                    self._set("limited", "1" if not cancelled() else "0")
                    break
                seen += 1
                kind = self._record(path)
                if kind == "dicom":
                    dicom_count += 1
                self.db.execute(
                    "INSERT INTO visited VALUES (?)", (path.relative_to(self.root).as_posix(),)
                )
                if seen % batch_size == 0:
                    self.db.commit()
                    if not self._checkpoint(max_bytes):
                        return self._limited("inventory_bytes")
                if on_progress is not None:
                    on_progress(
                        {
                            "folders": folders,
                            "files": seen,
                            "dicom": dicom_count,
                            "series": series_count,
                        }
                    )
            if stopped:
                break
            self.db.execute("UPDATE directories SET complete=1 WHERE rel=?", (folder,))
            series_count += self.db.execute(
                "SELECT COUNT(DISTINCT uid) FROM files WHERE directory=? AND kind='dicom'",
                (folder,),
            ).fetchone()[0]
            self.db.commit()
            if not self._checkpoint(max_bytes):
                return self._limited("inventory_bytes")
        if not stopped and not errors:
            removed = self.db.execute(
                "SELECT COUNT(*) FROM files WHERE rel NOT IN (SELECT rel FROM visited)"
            ).fetchone()[0]
            if removed:
                self._change()
                self.db.execute("DELETE FROM files WHERE rel NOT IN (SELECT rel FROM visited)")
            error = self.db.execute("SELECT 1 FROM files WHERE error != '' LIMIT 1").fetchone()
            self._set("complete", "0" if error else "1")
        self._set("walk_errors", str(len(errors)))
        self.db.commit()
        self._checkpoint(max_bytes)
        return self.summary()

    def _checkpoint(self, max_bytes: int) -> bool:
        # A reader holding an old snapshot may prevent truncation. Stop rather than
        # letting subsequent batches grow an unbounded WAL behind that reader.
        self.db.execute("PRAGMA busy_timeout=0")
        try:
            busy = self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
        finally:
            self.db.execute("PRAGMA busy_timeout=5000")
        return not busy and self.cache_bytes() <= max_bytes - 64 * 1024

    def cache_bytes(self) -> int:
        return sum(
            path.stat().st_size
            for path in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm"))
            if path.exists()
        )

    def _limited(self, reason: str) -> dict[str, Any]:
        self._set("complete", "0")
        self._set("limited", "1")
        self._set("limit_reason", reason)
        self.db.commit()
        self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        return self.summary()

    def check_reader(self) -> None:
        """Read cached facts only when every batch used the current scanner."""
        for row in self.db.execute("SELECT signature FROM files"):
            if not row[0] or json.loads(row[0])[0] != self._scanner:
                raise JobConflict("Inventory scanner changed; discover this source again")

    def summary(self) -> dict[str, Any]:
        counts = dict(self.db.execute("SELECT kind, COUNT(*) FROM files GROUP BY kind").fetchall())
        errors = self.db.execute("SELECT COUNT(*) FROM files WHERE error != ''").fetchone()[0]
        errors += int(self._get("walk_errors") or 0)
        total = self.db.execute(
            "SELECT COUNT(*) FROM (SELECT f.directory, f.uid FROM files f JOIN directories d "
            "ON f.directory=d.rel WHERE f.kind='dicom' AND d.complete=1 "
            "GROUP BY f.directory, f.uid)"
        ).fetchone()[0]
        return {
            "complete": self._get("complete") == "1" and not errors,
            "limited": self._get("limited") == "1",
            "limit_reason": self._get("limit_reason") or None,
            "cache_bytes": self.cache_bytes(),
            "generation": self.generation,
            "files": sum(counts.values()),
            "dicom": counts.get("dicom", 0),
            "series": total,
            "ignored": counts.get("ignored", 0),
            "nifti": counts.get("nifti", 0),
            "npy": counts.get("npy", 0),
            "errors": errors,
            "folders": self.db.execute("SELECT COUNT(*) FROM directories").fetchone()[0],
        }

    @staticmethod
    def _key(directory: str, uid: str) -> str:
        return hashlib.sha256(json.dumps([directory, uid]).encode()).hexdigest()

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
            "SELECT f.directory, f.uid, COUNT(*) AS n_files, SUM(f.size) AS source_bytes, "
            "MIN(f.rel) AS first_rel FROM files f JOIN directories d ON f.directory=d.rel "
            "WHERE f.kind='dicom' AND d.complete=1 GROUP BY f.directory, f.uid "
            "ORDER BY f.directory, f.uid LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = self.summary()["series"]
        items = [{**dict(row), "key": self._key(row["directory"], row["uid"])} for row in rows]
        nxt = None
        if offset + len(items) < total:
            nxt = encode_cursor(self.generation, offset + len(items))
        return {"items": items, "next_cursor": nxt, "total": total, "generation": self.generation}

    def series(self, key: str) -> dicom_scan.Series:
        """Materialize one complete series, not every file/header in the inventory."""
        from plugins.dicom import scan as dicom_scan

        members = self.db.execute(
            "SELECT f.rel, f.header, f.size, f.directory, f.uid FROM files f "
            "JOIN directories d ON f.directory=d.rel WHERE f.series_key=? "
            "AND f.kind='dicom' AND d.complete=1 ORDER BY f.rel",
            (key,),
        ).fetchall()
        if not members:
            raise NotFound("Series is absent or its inventory is incomplete")
        paths = [self.root / r["rel"] for r in members]
        headers = [Dataset.from_json(r["header"]) for r in members]
        order = dicom_scan._ipp_order(paths, headers)
        return dicom_scan.Series(
            self.root / members[0]["directory"],
            members[0]["uid"],
            tuple(paths[i] for i in order),
            tuple(headers[i] for i in order),
            sum(r["size"] for r in members),
            self.root,
        )

    def discover(self, subtree: Path) -> list[dicom_scan.Series]:
        """Task-side cache adapter: query one patient subtree without rescanning its files."""
        if self._get("complete") != "1":
            raise JobConflict("Finish source discovery before planning its series")
        rel = subtree.relative_to(self.root).as_posix()
        condition = ""
        parameters: tuple[str, ...] = ()
        if rel != "." and not self.single_file:
            condition = " AND (directory=? OR (directory>=? AND directory<?))"
            parameters = (rel, rel + "/", rel + "0")
        keys = self.db.execute(
            "SELECT series_key FROM files WHERE kind='dicom'"
            + condition
            + " GROUP BY directory, uid ORDER BY directory, uid",
            parameters,
        ).fetchall()
        return [self.series(row[0]) for row in keys]
