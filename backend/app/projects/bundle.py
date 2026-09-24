"""Project bundles (PRJ-08/09, API-06): `.zip` of the project folder without `cache/`.

Layout: every entry sits under one top-level folder named after the `project_id`
(`{project_id}/project.json`, `{project_id}/curation/events.jsonl`, …). Left out: `cache/`
(disposable, PRJ-10), the `.lock` file, atomic-write temp files, symlinks and anything that
looks like image data. Bundles hold alias refs only (PRJ-04), so image paths are resolved
against the importing server's roots; the relink dialog (PRJ-05) fixes any that do not resolve.
"""

from __future__ import annotations

import json
import posixpath
import shutil
import stat
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any, Final

from pydantic import ValidationError

from app.core.errors import ValidationProblem
from app.core.fsio import atomic_write_json
from app.core.ids import is_ulid, new_ulid, utc_now
from app.projects.migrations import check_version
from app.projects.models import ProjectConfig

EXCLUDED_DIRS: Final = frozenset({"cache"})
EXCLUDED_FILES: Final = frozenset({".lock"})
# Image data never goes into a bundle (PRJ-08), even if someone dropped a volume in the folder.
IMAGE_SUFFIXES: Final = (".nii", ".nii.gz", ".npy", ".npz", ".nrrd", ".mha", ".mhd", ".dcm")
MAX_ENTRIES: Final = 1_000_000
MAX_UNCOMPRESSED: Final = 50 * 1024**3  # zip-bomb guard (50 GiB)


def _excluded(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return (
        parts[0] in EXCLUDED_DIRS
        or (len(parts) == 1 and name in EXCLUDED_FILES)
        or (name.startswith(".") and name.endswith(".tmp"))  # core.fsio temp files
        or name.lower().endswith(IMAGE_SUFFIXES)
    )


def _walk(folder: Path) -> Iterator[tuple[Path, str]]:
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if p.is_symlink() or not p.is_file() or _excluded(rel):
            continue
        yield p, rel


def write_bundle(folder: Path, project_id: str, out: Path) -> int:
    """Zip the project folder into `out` (outside `folder`'s bundled part); returns entries."""
    n = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path, rel in _walk(folder):
            zf.write(path, f"{project_id}/{rel}")
            n += 1
    return n


def _safe_rel(name: str) -> str | None:
    """Member name → relative POSIX path; None if unsafe (absolute, `..`, backslash)."""
    if not name or "\\" in name or "\x00" in name or name.startswith("/") or ":" in name[:3]:
        return None
    norm = posixpath.normpath(name)
    if norm.startswith("../") or norm in ("..", "."):
        return None
    return norm


def _members(zf: zipfile.ZipFile) -> tuple[str, list[tuple[zipfile.ZipInfo, str]]]:
    """Validate members; returns the top-level folder and (info, path inside it) pairs."""
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ValidationProblem("Bundle has too many entries")
    if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
        raise ValidationProblem("Bundle is too large when uncompressed")
    tops: set[str] = set()
    files: list[tuple[zipfile.ZipInfo, str]] = []
    for info in infos:
        rel = _safe_rel(info.filename)
        if rel is None:
            raise ValidationProblem(f"Unsafe path in bundle: {info.filename!r}")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValidationProblem(f"Symlink in bundle: {info.filename!r}")
        top, _, inner = rel.partition("/")
        tops.add(top)
        if info.is_dir() or not inner:
            if not info.is_dir():
                raise ValidationProblem("Bundle entries must sit inside one project folder")
            continue
        files.append((info, inner))
    if len(tops) != 1:
        raise ValidationProblem("A bundle holds exactly one top-level project folder")
    return tops.pop(), files


def read_config(zf: zipfile.ZipFile, top: str) -> ProjectConfig:
    """`project.json` of the bundle; format checked like PRJ-11 (newer → 409)."""
    try:
        raw: Any = json.loads(zf.read(f"{top}/project.json").decode("utf-8"))
    except KeyError:
        raise ValidationProblem("Bundle has no project.json") from None
    except (UnicodeDecodeError, ValueError):
        raise ValidationProblem("Bundle project.json is not valid JSON") from None
    check_version(raw)  # format-version-unsupported for foreign or newer documents
    try:
        return ProjectConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValidationProblem(
            "Bundle project.json is invalid",
            errors=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
        ) from None


def extract_bundle(
    fileobj: IO[bytes], staging: Path, taken: set[str]
) -> tuple[ProjectConfig, str, int]:
    """Validate and extract into `staging` (created). Returns (config, original id, n files).

    Keeps the bundle's `project_id` unless it is not a ULID or already used in this workspace
    (`taken`); then a new id is assigned and written to the staged `project.json`.
    """
    if not zipfile.is_zipfile(fileobj):
        raise ValidationProblem(
            "Not a zip file", errors=[{"loc": ["body", "bundle"], "msg": "not a zip"}]
        )
    fileobj.seek(0)
    with zipfile.ZipFile(fileobj) as zf:
        top, files = _members(zf)
        cfg = read_config(zf, top)
        original = cfg.project_id
        staging.mkdir(parents=True)
        n = 0
        for info, inner in files:
            if _excluded(inner):
                continue
            dest = staging / inner
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, dest.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            n += 1
    if not is_ulid(cfg.project_id) or cfg.project_id in taken:
        cfg = cfg.model_copy(update={"project_id": new_ulid(), "updated_at": utc_now()})
        atomic_write_json(staging / "project.json", cfg.model_dump(mode="json"))
    return cfg, original, n
