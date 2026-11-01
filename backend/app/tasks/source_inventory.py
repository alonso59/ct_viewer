"""Bounded durable header inventory; complete folders become browsable series.

SQLite is a managed workspace artifact. It is never created in the input root. Header facts
are committed in batches and reused after interruption.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterator, Sequence
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

VERSION = 2
BASE_CACHE = 256
BATCH_SIZE = 64
PROJECTION_MIN_READS = 5000
PROJECTION_WARN = 0.9
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


# Per-file rows hold only identity and the tags that differ from the series' shared header
# (`delta`: a JSON object of changed tags, null meaning absent, or `[full header]` when that is
# shorter; a changed tag whose VR is unchanged keeps only its value list). Scanner identity
# lives once in `meta`.
SCHEMA = """
CREATE TABLE IF NOT EXISTS directories (
    id INTEGER PRIMARY KEY, rel TEXT NOT NULL UNIQUE, complete INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS series (
    id INTEGER PRIMARY KEY, directory_id INTEGER NOT NULL, uid TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE, header TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (
    directory_id INTEGER NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, series_id INTEGER,
    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, dev INTEGER NOT NULL, ino INTEGER NOT NULL,
    delta TEXT NOT NULL, error TEXT NOT NULL, PRIMARY KEY (directory_id, name)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS file_errors ON files(error) WHERE error != '';
"""


def stat_identity(st: os.stat_result) -> tuple[int, int, int, int]:
    """(size, mtime_ns, dev, ino) as stored; SQLite ints are signed, Windows ids can be larger."""
    dev, ino = (v - (1 << 64) if v >= 1 << 63 else v for v in (st.st_dev, st.st_ino))
    return st.st_size, st.st_mtime_ns, dev, ino


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _delta(base: dict[str, Any], header: dict[str, Any]) -> str:
    changed: dict[str, Any] = {}
    for tag, value in header.items():
        old = base.get(tag)
        if old == value:
            continue
        same_vr = old is not None and old.get("vr") == value.get("vr")
        changed[tag] = value["Value"] if same_vr and set(value) == {"vr", "Value"} else value
    changed.update({tag: None for tag in base if tag not in header})
    if not changed:
        return ""
    short, full = _compact(changed), _compact([header])
    return short if len(short) < len(full) else full


def _merge(base: dict[str, Any], delta: str) -> dict[str, Any]:
    if not delta:
        return base
    changed = json.loads(delta)
    if isinstance(changed, list):
        return dict(changed[0])
    merged = dict(base)
    for tag, value in changed.items():
        if value is None:
            del merged[tag]
        else:
            merged[tag] = {**base[tag], "Value": value} if isinstance(value, list) else value
    return merged


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
    from plugins.dicom import files as source_files
    from plugins.dicom import scan as dicom_scan

    if not source.is_dir():
        raise ValidationProblem("Choose a source folder to limit it to patient folders")
    if dicom_scan.has_dicom_files(source):
        raise ValidationProblem(
            "The source folder holds DICOM files directly; patient folders cannot split it"
        )
    names = set(folders)
    for name in names:
        if (
            not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or "\x00" in name
            or source_files.excluded(name)
        ):
            raise ValidationProblem("A patient folder name is not a plain top-level folder name")
        path = source / name
        if path.is_symlink() or not path.is_dir():
            raise ValidationProblem("A patient folder is missing, not a folder or a link")
    return sorted(names, key=str.lower)


def scope_hash(folders: Sequence[str] | None) -> str:
    """Stable identity of a top-level folder scope; empty for the whole source."""
    if folders is None:
        return ""
    return hashlib.sha256(json.dumps(sorted(set(folders))).encode()).hexdigest()


class SourceInventory:
    def __init__(self, path: Path, root: Path, folders: Sequence[str] | None = None) -> None:
        self.source = root.resolve()
        self.single_file = self.source.is_file()
        self.root = self.source.parent if self.single_file else self.source
        self._changed = False
        self._reused = False
        self._initial_rows = 0
        self._projection: dict[str, Any] | None = None
        self.path = path
        self._scanner = scanner_identity()
        if path.resolve().is_relative_to(self.root):
            raise ValidationProblem("An inventory must be stored outside its source root")
        self.db = workspace_database(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID"
        )
        existing_root = self._get("root")
        if existing_root is not None and existing_root != str(self.source):
            self.db.close()
            raise JobConflict("Inventory belongs to a different source")
        if existing_root is not None and self._get("version") != str(VERSION):
            self.db.close()
            raise JobConflict(
                "Inventory was written by an older version; rescan this source to rebuild it"
            )
        self.db.executescript(SCHEMA)
        if (
            existing_root is not None
            and folders is not None
            and self._get("scope_hash") != scope_hash(folders)
        ):
            self.db.close()
            raise JobConflict("Inventory was built for a different folder scope")
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
                "scanner": self._scanner,
                "generation": new_ulid(),
                "complete": "0",
                "limited": "0",
                "walk_errors": "0",
                "scope": json.dumps(sorted(set(folders))) if folders is not None else "",
                "scope_hash": scope_hash(folders),
            }.items():
                self._set(key, value)
            self.db.commit()
        self._dir: tuple[str, int] | None = None
        self._bases: dict[str, tuple[int, dict[str, Any]]] = {}

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
    def scope(self) -> set[str] | None:
        raw = self._get("scope")
        return set(json.loads(raw)) if raw else None

    @property
    def generation(self) -> str:
        return str(self._get("generation"))

    def _change(self) -> None:
        if not self._changed:
            self._set("generation", new_ulid())
            self._changed = True

    def _directory_id(self, rel: str) -> int:
        if self._dir is None or self._dir[0] != rel:
            self.db.execute(
                "INSERT OR IGNORE INTO directories (rel, complete) VALUES (?, 0)", (rel,)
            )
            row = self.db.execute("SELECT id FROM directories WHERE rel=?", (rel,)).fetchone()
            self._dir = (rel, int(row[0]))
            self._bases.clear()
        return self._dir[1]

    def _series_base(
        self, directory_id: int, uid: str, header: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        """The series row (created from this file's header when new) and its shared header."""
        cached = self._bases.get(uid)
        if cached is not None:
            return cached
        key = self._key(self._dir[0] if self._dir else ".", uid)
        row = self.db.execute("SELECT id, header FROM series WHERE key=?", (key,)).fetchone()
        if row is not None:
            found = (int(row[0]), json.loads(row[1]))
        else:
            cursor = self.db.execute(
                "INSERT INTO series (directory_id, uid, key, header) VALUES (?, ?, ?, ?)",
                (directory_id, uid, key, _compact(header)),
            )
            found = (int(cursor.lastrowid or 0), header)
        if len(self._bases) >= BASE_CACHE:
            self._bases.clear()
        self._bases[uid] = found
        return found

    def _record(self, path: Path) -> str:
        """Cache one file's facts; `_reused` tells whether a cached record was kept."""
        from plugins.dicom import scan as dicom_scan

        self._reused = False

        directory = path.parent.relative_to(self.root).as_posix()
        directory_id = self._directory_id(directory)
        kind, uid, error, delta = "ignored", "", "", ""
        header: dict[str, Any] = {}
        series_id: int | None = None
        size = mtime_ns = dev = ino = 0
        try:
            st = path.stat(follow_symlinks=False)
            size, mtime_ns, dev, ino = stat_identity(st)
            previous = self.db.execute(
                "SELECT kind, error, size, mtime_ns, dev, ino FROM files "
                "WHERE directory_id=? AND name=?",
                (directory_id, path.name),
            ).fetchone()
            if (
                previous is not None
                and tuple(previous[2:]) == (size, mtime_ns, dev, ino)
                and (not previous[1] or previous[0] == "rejected")
            ):
                self._reused = True
                return str(previous[0])
            ext = path.suffix.lower()
            if ext == ".nii" or path.name.lower().endswith(".nii.gz"):
                kind = "nifti"
            elif ext == ".npy":
                kind = "npy"
            elif ext not in NON_IMAGES and path.name.lower() != "dicomdir":
                found = dicom_scan.image_info(path, self.root)
                if found is not None:
                    ds, _ = found
                    header, kind, uid = ds.to_json_dict(), "dicom", str(ds.SeriesInstanceUID)
        except dicom_scan.HeaderRejected as exc:
            kind, error = "rejected", exc.code
        except Exception as exc:
            error = type(exc).__name__
        if kind == "dicom":
            series_id, base = self._series_base(directory_id, uid, header)
            delta = _delta(base, header)
        self._change()
        self.db.execute(
            "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (directory_id, path.name, kind, series_id, size, mtime_ns, dev, ino, delta, error),
        )
        self.db.execute("UPDATE directories SET complete=0 WHERE id=?", (directory_id,))
        return kind

    def precount(
        self,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[int, int] | None:
        """Name-only walk with the discovery traversal rules; totals persist and are reused.

        Returns (files, folders), or None when cancelled before the walk finished.
        """
        from plugins.dicom import files as source_files

        files_known, folders_known = self._totals()
        if files_known is not None and folders_known is not None:
            return files_known, folders_known
        if not self.source.exists():
            raise SourceMissing("Source unavailable; restore it before discovery")
        files = folders = 0
        pending = [str(self.root)]
        top = self.scope
        last = float("-inf")
        while pending and not self.single_file:
            if cancelled():
                return None
            folders += 1
            current = pending.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        if entry.name.startswith(".") or entry.is_symlink():
                            continue
                        scoped = top is not None and current == str(self.root)
                        if entry.is_dir(follow_symlinks=False):
                            if not source_files.excluded(entry.name) and (
                                top is None or not scoped or entry.name in top
                            ):
                                pending.append(entry.path)
                        elif entry.is_file(follow_symlinks=False) and not scoped:
                            files += 1
            except OSError:
                pass
            if on_progress is not None and time.monotonic() - last >= 0.25:
                on_progress({"stage": "counting", "folders": folders, "files": files})
                last = time.monotonic()
        if self.single_file:
            files = folders = 1
        if on_progress is not None:
            on_progress({"stage": "counting", "folders": folders, "files": files})
        self._set("precount_files", str(files))
        self._set("precount_folders", str(folders))
        self.db.commit()
        return files, folders

    def _totals(self) -> tuple[int | None, int | None]:
        files, folders = self._get("precount_files"), self._get("precount_folders")
        return (
            int(files) if files is not None else None,
            int(folders) if folders is not None else None,
        )

    def _project(self, read: int, seen: int, max_bytes: int) -> None:
        """Extrapolate the final database size from the bytes spent per cached file so far."""
        total = self._totals()[0]
        if total is None or read < PROJECTION_MIN_READS:
            return
        projected = int(self.cache_bytes() / max(self._initial_rows, seen) * total)
        cap = max_bytes // 4
        self._projection = {
            "projected_bytes": projected,
            "cap_bytes": cap,
            "warning": projected > PROJECTION_WARN * cap,
        }
        self._set("projection", json.dumps(self._projection))

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
            self._dir = None
            self._bases.clear()
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
        self._dir = None
        self._bases.clear()
        self._set("complete", "0")
        self._set("limited", "0")
        self._set("limit_reason", "")
        self._set("cap_bytes", str(max_bytes // 4))
        self._projection = None
        if self._get("scanner") != self._scanner:
            # Cached facts from another scanner are unusable; every file is read again.
            self.db.execute("DELETE FROM files")
            self.db.execute("DELETE FROM series")
            self._set("scanner", self._scanner)
            self._change()
        self.db.commit()
        self._initial_rows = int(self.db.execute("SELECT COUNT(*) FROM files").fetchone()[0])
        # Leave room for the WAL, SQLite's shared-memory index and a bounded transaction.
        # Cap pages as well as checkpointing: a large header must not bypass the quota.
        page_size = int(self.db.execute("PRAGMA page_size").fetchone()[0])
        pages = max_bytes // (4 * page_size)
        actual_pages = self.db.execute(f"PRAGMA max_page_count={pages}").fetchone()[0]
        self.db.execute(f"PRAGMA cache_size=-{max(64, max_bytes // 4096)}")
        self.db.execute("PRAGMA wal_autocheckpoint=0")
        if actual_pages > pages or not self._checkpoint(max_bytes):
            return self._limited("inventory_bytes")
        self.db.execute(
            "CREATE TEMP TABLE IF NOT EXISTS visited (directory_id INTEGER NOT NULL, "
            "name TEXT NOT NULL, PRIMARY KEY (directory_id, name)) WITHOUT ROWID"
        )
        self.db.execute("DELETE FROM visited")
        seen = read = 0
        files_total, folders_total = self._totals()
        dicom_count = series_count = rejected_count = 0
        errors: list[OSError] = []
        stopped = False
        self.db.commit()
        candidates = (
            iter([(self.root, [self.source])])
            if self.single_file
            else source_files.folders(self.root, errors.append, self.scope)
        )

        def row(folders: int) -> dict[str, Any]:
            counters: dict[str, Any] = {
                "folders": folders,
                "files": seen,
                "read": read,
                "dicom": dicom_count,
                "rejected": rejected_count,
                "series": series_count,
            }
            if files_total is not None and folders_total is not None:
                counters.update(files_total=files_total, folders_total=folders_total)
            if self._projection is not None:
                counters["inventory_projection"] = self._projection
            return counters

        for folders, (directory, paths) in enumerate(candidates, 1):
            if cancelled():
                stopped = True
                break
            folder = directory.relative_to(self.root).as_posix()
            directory_id = self._directory_id(folder)
            if on_progress is not None:
                on_progress(row(folders))
            for path in paths:
                if cancelled() or (max_files is not None and seen >= max_files):
                    stopped = True
                    self._set("limited", "1" if not cancelled() else "0")
                    break
                seen += 1
                kind = self._record(path)
                read += 0 if self._reused else 1
                if kind == "dicom":
                    dicom_count += 1
                elif kind == "rejected":
                    rejected_count += 1
                self.db.execute("INSERT INTO visited VALUES (?, ?)", (directory_id, path.name))
                if seen % batch_size == 0:
                    self.db.commit()
                    if not self._checkpoint(max_bytes):
                        return self._limited("inventory_bytes")
                    self._project(read, seen, max_bytes)
                if on_progress is not None:
                    on_progress(row(folders))
            if stopped:
                break
            ambiguous = self.db.execute(
                "SELECT 1 FROM files f JOIN visited v ON f.directory_id=v.directory_id "
                "AND f.name=v.name WHERE f.directory_id=? "
                "AND f.error='MISSING_SERIES_INSTANCE_UID' LIMIT 1",
                (directory_id,),
            ).fetchone()
            condition = "kind='dicom'" if ambiguous else "error='AMBIGUOUS_SERIES_MEMBERSHIP'"
            affected = self.db.execute(
                f"SELECT COUNT(*) FROM files WHERE directory_id=? AND {condition}",
                (directory_id,),
            ).fetchone()[0]
            if affected:
                self._change()
                self.db.execute(
                    f"UPDATE files SET kind=?, error=? WHERE directory_id=? AND {condition}",
                    (
                        "rejected" if ambiguous else "dicom",
                        "AMBIGUOUS_SERIES_MEMBERSHIP" if ambiguous else "",
                        directory_id,
                    ),
                )
                dicom_count += -affected if ambiguous else affected
                rejected_count += affected if ambiguous else -affected
            self.db.execute("UPDATE directories SET complete=1 WHERE id=?", (directory_id,))
            series_count += self.db.execute(
                "SELECT COUNT(DISTINCT series_id) FROM files WHERE directory_id=? AND kind='dicom'",
                (directory_id,),
            ).fetchone()[0]
            self.db.commit()
            if not self._checkpoint(max_bytes):
                return self._limited("inventory_bytes")
        if not stopped and not errors:
            gone = "(directory_id, name) NOT IN (SELECT directory_id, name FROM visited)"
            removed = self.db.execute(f"SELECT COUNT(*) FROM files WHERE {gone}").fetchone()[0]
            if removed:
                self._change()
                self.db.execute(f"DELETE FROM files WHERE {gone}")
            self.db.execute(
                "DELETE FROM series WHERE id NOT IN "
                "(SELECT DISTINCT series_id FROM files WHERE series_id IS NOT NULL)"
            )
            error = self.db.execute(
                "SELECT 1 FROM files WHERE error != '' AND kind != 'rejected' LIMIT 1"
            ).fetchone()
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
        if self._get("scanner") != self._scanner:
            raise JobConflict("Inventory scanner changed; discover this source again")

    def summary(self) -> dict[str, Any]:
        counts = dict(self.db.execute("SELECT kind, COUNT(*) FROM files GROUP BY kind").fetchall())
        errors = self.db.execute(
            "SELECT COUNT(*) FROM files WHERE error != '' AND kind != 'rejected'"
        ).fetchone()[0]
        errors += int(self._get("walk_errors") or 0)
        totals = self._totals()
        total = self.db.execute(
            "SELECT COUNT(*) FROM (SELECT f.series_id FROM files f JOIN directories d "
            "ON f.directory_id=d.id WHERE f.kind='dicom' AND d.complete=1 "
            "GROUP BY f.series_id)"
        ).fetchone()[0]
        return {
            "complete": self._get("complete") == "1" and not errors,
            "limited": self._get("limited") == "1",
            "limit_reason": self._get("limit_reason") or None,
            "cache_bytes": self.cache_bytes(),
            "generation": self.generation,
            "files": sum(counts.values()),
            "dicom": counts.get("dicom", 0),
            "rejected": counts.get("rejected", 0),
            "rejections": dict(
                self.db.execute(
                    "SELECT error, COUNT(*) FROM files WHERE kind='rejected' GROUP BY error"
                ).fetchall()
            ),
            "series": total,
            "ignored": counts.get("ignored", 0),
            "nifti": counts.get("nifti", 0),
            "npy": counts.get("npy", 0),
            "errors": errors,
            "folders": self.db.execute("SELECT COUNT(*) FROM directories").fetchone()[0],
            "files_total": totals[0],
            "folders_total": totals[1],
            "scope_hash": self._get("scope_hash") or None,
            "inventory_cap_bytes": int(self._get("cap_bytes") or 0) or None,
            "inventory_projection": json.loads(self._get("projection") or "null"),
        }

    def patient_ids(self) -> set[str]:
        """PatientIDs of the discovered series, read from each series' first file."""
        from plugins.dicom import files as source_files
        from pydicom import dcmread

        found: set[str] = set()
        rows = self.db.execute(
            "SELECT d.rel, MIN(f.name) FROM files f JOIN directories d ON f.directory_id=d.id "
            "WHERE f.kind='dicom' AND d.complete=1 GROUP BY f.series_id"
        ).fetchall()
        for rel, name in rows:
            path = self.root / self._rel(rel, name)
            try:
                with source_files.open_file(path, self.root) as handle:
                    ds = dcmread(
                        handle, stop_before_pixels=True, specific_tags=["PatientID"], force=True
                    )
            except Exception:
                continue
            if str(getattr(ds, "PatientID", "")).strip():
                found.add(str(ds.PatientID).strip())
        return found

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

    @staticmethod
    def _rel(directory: str, name: str) -> str:
        return name if directory == "." else f"{directory}/{name}"

    @staticmethod
    def _split(rel: str) -> tuple[str, str]:
        directory, _, name = rel.rpartition("/")
        return directory or ".", name

    def entry(self, rel: str) -> sqlite3.Row | None:
        """Cached identity facts of one file: kind, error, size, mtime_ns, dev, ino."""
        directory, name = self._split(rel)
        row: sqlite3.Row | None = self.db.execute(
            "SELECT f.kind, f.error, f.size, f.mtime_ns, f.dev, f.ino FROM files f "
            "JOIN directories d ON d.id=f.directory_id WHERE d.rel=? AND f.name=?",
            (directory, name),
        ).fetchone()
        return row

    @property
    def scanner(self) -> str | None:
        return self._get("scanner")

    def rels(self, kind: str) -> list[str]:
        """Relative paths of every file of one kind, sorted."""
        rows = self.db.execute(
            "SELECT d.rel, f.name FROM files f JOIN directories d ON d.id=f.directory_id "
            "WHERE f.kind=?",
            (kind,),
        )
        return sorted(self._rel(r[0], r[1]) for r in rows)

    def dicom_units(self) -> Iterator[tuple[str, list[str]]]:
        """(series key, member paths) for every DICOM series, in directory/uid order."""
        groups = self.db.execute(
            "SELECT s.key, s.id, s.directory_id, d.rel FROM (SELECT DISTINCT directory_id, "
            "series_id FROM files WHERE kind='dicom') x JOIN series s ON s.id=x.series_id "
            "JOIN directories d ON d.id=x.directory_id ORDER BY d.rel, s.uid"
        ).fetchall()
        for group in groups:
            names = self.db.execute(
                "SELECT name FROM files WHERE directory_id=? AND series_id=? AND kind='dicom' "
                "ORDER BY name",
                (group["directory_id"], group["id"]),
            )
            yield group["key"], [self._rel(group["rel"], row[0]) for row in names]

    def series(self, key: str) -> dicom_scan.Series:
        """Materialize one series whose folder discovery completed."""
        from plugins.dicom import scan as dicom_scan

        head = self.db.execute(
            "SELECT s.id, s.uid, s.header, d.id AS directory_id, d.rel FROM series s "
            "JOIN directories d ON d.id=s.directory_id WHERE s.key=? AND d.complete=1",
            (key,),
        ).fetchone()
        members = (
            self.db.execute(
                "SELECT name, size, delta FROM files WHERE directory_id=? AND series_id=? "
                "AND kind='dicom' ORDER BY name",
                (head["directory_id"], head["id"]),
            ).fetchall()
            if head is not None
            else []
        )
        if not members:
            raise NotFound("Series is absent or its inventory is incomplete")
        base = json.loads(head["header"])
        paths = [self.root / self._rel(head["rel"], r["name"]) for r in members]
        headers = [Dataset.from_json(_merge(base, r["delta"])) for r in members]
        order = dicom_scan._ipp_order(paths, headers)
        return dicom_scan.Series(
            self.root / head["rel"],
            head["uid"],
            tuple(paths[i] for i in order),
            tuple(headers[i] for i in order),
            sum(r["size"] for r in members),
            self.root,
        )

    def discover(self, subtree: Path) -> list[dicom_scan.Series]:
        """Cached stand-in for a patient-subtree scan."""
        if self._get("complete") != "1":
            raise JobConflict("Finish source discovery before planning its series")
        rel = subtree.relative_to(self.root).as_posix()
        condition = ""
        parameters: tuple[str, ...] = ()
        if rel != "." and not self.single_file:
            condition = " WHERE d.rel=? OR (d.rel>=? AND d.rel<?)"
            parameters = (rel, rel + "/", rel + "0")
        keys = self.db.execute(
            "SELECT s.key FROM (SELECT DISTINCT directory_id, series_id FROM files "
            "WHERE kind='dicom') x JOIN series s ON s.id=x.series_id "
            "JOIN directories d ON d.id=x.directory_id" + condition + " ORDER BY d.rel, s.uid",
            parameters,
        ).fetchall()
        return [self.series(row[0]) for row in keys]
