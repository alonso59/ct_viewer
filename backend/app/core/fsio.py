"""File I/O for project state (PROJECT_FORMAT.md §Write rules).

Only project/workspace files are written here; source data is never passed in (R1).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any


def _dumps(obj: Any, *, indent: int | None) -> str:
    return json.dumps(obj, indent=indent, ensure_ascii=False, sort_keys=False)


def atomic_write_bytes(path: Path, data: bytes, *, backup: bool = False) -> None:
    """Temp file in the same dir → fsync → rename. `backup` keeps `{name}.bak` of the old file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if backup and path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def _fsync_dir(d: Path) -> None:
    try:
        fd = os.open(d, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_json(path: Path, obj: Any, *, backup: bool = False) -> None:
    atomic_write_bytes(path, (_dumps(obj, indent=2) + "\n").encode("utf-8"), backup=backup)


def read_json(path: Path) -> Any:
    with path.open("rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Append one JSON object per line, `\\n`-terminated, flushed (API process only)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(_dumps(row, indent=None) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Rewrite a derived jsonl file (index/*) atomically."""
    data = "".join(_dumps(r, indent=None) + "\n" for r in rows)
    atomic_write_bytes(path, data.encode("utf-8"))


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield objects from a jsonl file; skips blank lines. Missing file yields nothing."""
    if not path.exists():
        return
    with path.open("rb") as fh:
        for raw in fh:
            line = raw.strip()
            if line:
                yield json.loads(line.decode("utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))
