"""API-10 server folder browser (IMP-01), limited to `ALLOWED_DATA_ROOTS` (OPS-04)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.v1.deps import Ctx
from app.core.errors import DerivedRootRequired, NotFound, ValidationProblem
from app.core.paths import PathGuard, is_within, realpath

router = APIRouter(tags=["fs"])

MAX_ENTRIES = 5000
METADATA_FILE = "metadata.jsonl"


class FsEntry(BaseModel):
    name: str
    path: str
    kind: Literal["dir", "file"]
    size: int | None = None
    has_metadata: bool = False


class FsListing(BaseModel):
    path: str | None
    parent: str | None
    entries: list[FsEntry]
    truncated: bool = False


def _roots(guard: PathGuard) -> list[Path]:
    return guard.allowed_roots or [realpath(Path.home())]


def _dir_entry(path: Path, name: str | None = None) -> FsEntry:
    return FsEntry(
        name=name or path.name or str(path),
        path=str(path),
        kind="dir",
        has_metadata=(path / METADATA_FILE).exists(),
    )


def _parent(real: Path, guard: PathGuard) -> str | None:
    roots = _roots(guard)
    if real in roots or real.parent == real:
        return None
    if not any(is_within(real.parent, r) for r in roots):
        return None
    return str(real.parent)


def _entry(real_dir: Path, de: os.DirEntry[str], guard: PathGuard) -> FsEntry | None:
    path = real_dir / de.name
    try:
        if not guard.is_allowed(path):
            return None  # symlink escaping the allowed roots
        if de.is_dir():
            return _dir_entry(path, de.name)
        if de.is_file():
            return FsEntry(name=de.name, path=str(path), kind="file", size=de.stat().st_size)
    except OSError:
        return None
    return None


def _is_dir(de: os.DirEntry[str]) -> bool:
    try:
        return de.is_dir()
    except OSError:
        return False


def list_dir(real: Path, guard: PathGuard) -> FsListing:
    try:
        with os.scandir(real) as it:
            visible = [de for de in it if not de.name.startswith(".")]
    except OSError:
        raise NotFound("Directory is not readable") from None
    visible.sort(key=lambda de: (not _is_dir(de), de.name.casefold(), de.name))
    entries = [e for de in visible[:MAX_ENTRIES] if (e := _entry(real, de, guard)) is not None]
    return FsListing(
        path=str(real),
        parent=_parent(real, guard),
        entries=entries,
        truncated=len(visible) > MAX_ENTRIES,
    )


@router.get("/fs/list", response_model=FsListing)
def fs_list(
    ctx: Ctx, path: str | None = None, role: Literal["source", "derived"] = "source"
) -> FsListing:
    """`role=derived` browses ALLOWED_DERIVED_ROOTS (PRJ-13) instead of ALLOWED_DATA_ROOTS."""
    guard = ctx.workspace.derived_guard if role == "derived" else ctx.guard
    if role == "derived" and not guard.allowed_roots:
        raise DerivedRootRequired(
            "ALLOWED_DERIVED_ROOTS is empty: the server has no writable derived folder (OPS-11)",
            actions=["configure:ALLOWED_DERIVED_ROOTS"],
        )
    if not path:
        roots = [r for r in _roots(guard) if r.is_dir()]
        return FsListing(path=None, parent=None, entries=[_dir_entry(r, str(r)) for r in roots])
    p = Path(path)
    if not p.is_absolute():
        raise ValidationProblem(
            "path must be absolute", errors=[{"loc": ["query", "path"], "msg": "not absolute"}]
        )
    real = guard.check(p)
    if not real.is_dir():
        raise NotFound("Directory not found")
    return list_dir(real, guard)
