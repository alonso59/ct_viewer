"""Durable writes: complete files replace earlier ones only after fsync, then the folder is synced."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    sync_dir(path.parent)


def write_json_atomic(path: Path, obj: Any) -> None:
    write_text_atomic(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, items: Iterable[dict[str, Any]]) -> None:
    write_text_atomic(path, "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in items))


def private_database(path: Path) -> sqlite3.Connection:
    """SQLite with owner-only files: cached headers may hold PHI (never the host umask)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for name in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        try:
            fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if name == path else 0), 0o600)
        except FileNotFoundError:
            continue
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA busy_timeout=5000")
    return db


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_generation() -> str:
    """A ULID-formatted identifier (48-bit time, 80 random bits), like the app's record IDs."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))
