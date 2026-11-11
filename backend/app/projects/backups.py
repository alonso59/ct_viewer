"""Explicit backups of a dataset-local project's state into the application state folder.

A backup is the project's bundle: state only, never images, masks, outputs or caches. It is
restored with the existing bundle import. Nothing here runs on its own."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from app.core.errors import NotFound, ValidationProblem
from app.core.ids import new_ulid, utc_now
from app.projects.bundle import _walk, write_bundle

NAME_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9A-Z]{26}\.zip$")
MIB = 1024**2


class Backup(BaseModel):
    name: str
    created_at: str
    size_bytes: int


class BackupState(BaseModel):
    """`estimate_bytes` is the uncompressed state size, an upper bound for a new backup.
    `free_bytes` is what the file system reports; it does not prove quota."""

    backups: list[Backup] = Field(default_factory=list)
    estimate_bytes: int | None = None
    total_bytes: int = 0
    limit_bytes: int
    total_limit_bytes: int
    free_bytes: int | None = None
    # Empty when a backup can be made now; else why not.
    blocked: str = ""


class Backups:
    def __init__(self, workspace_root: Path, limit_mb: int, total_mb: int) -> None:
        self.root = workspace_root / "backups"
        self.limit, self.total_limit = limit_mb * MIB, total_mb * MIB

    def _used(self) -> int:
        return sum(p.stat().st_size for p in self.root.glob("*/*.zip")) if self.root.is_dir() else 0

    def _list(self, project_id: str) -> list[Backup]:
        rows = []
        for path in sorted((self.root / project_id).glob("*.zip"), reverse=True):
            if NAME_RE.match(path.name):
                stamp = path.name[:16]
                created = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:11]}:{stamp[11:13]}:{stamp[13:15]}Z"
                rows.append(
                    Backup(name=path.name, created_at=created, size_bytes=path.stat().st_size)
                )
        return rows

    def state(self, project_id: str, folder: Path | None, dataset_local: bool) -> BackupState:
        estimate = None
        blocked = ""
        if not dataset_local:
            blocked = "This project's state already lives in the application state folder"
        elif folder is None or not folder.is_dir():
            blocked = "The project's storage is unavailable"
        else:
            estimate = sum(path.stat().st_size for path, _rel in _walk(folder))
        used = self._used()
        if not blocked and estimate is not None:
            if estimate > self.limit:
                blocked = "The project state is larger than the limit for one backup"
            elif used + estimate > self.total_limit:
                blocked = "The limit for all backups would be exceeded; delete an older backup"
        free = None
        with contextlib.suppress(OSError):
            free = shutil.disk_usage(self.root if self.root.is_dir() else self.root.parent).free
        if not blocked and free is not None and estimate is not None and estimate > free:
            blocked = "Not enough free space for the backup"
        return BackupState(
            backups=self._list(project_id),
            estimate_bytes=estimate,
            total_bytes=used,
            limit_bytes=self.limit,
            total_limit_bytes=self.total_limit,
            free_bytes=free,
            blocked=blocked,
        )

    def create(self, project_id: str, folder: Path, redact: list[str]) -> Backup:
        """Writes beside the other backups under a temporary name and renames only when the
        finished file fits both limits; a failure removes the temporary file and nothing else."""
        target = self.root / project_id
        target.mkdir(parents=True, exist_ok=True)
        name = f"{utc_now().replace('-', '').replace(':', '')[:15]}Z-{new_ulid()}.zip"
        temporary = target / f".{name}.tmp"
        try:
            write_bundle(folder, project_id, temporary, redact)
            size = temporary.stat().st_size
            if size > self.limit:
                raise ValidationProblem("The backup is larger than the limit for one backup")
            if self._used() + size > self.total_limit:
                raise ValidationProblem(
                    "The limit for all backups would be exceeded; delete an older backup"
                )
            os.replace(temporary, target / name)
        except OSError as exc:
            raise ValidationProblem(
                f"The backup could not be written: {exc.strerror or exc}"
            ) from None
        finally:
            temporary.unlink(missing_ok=True)
        return self._list(project_id)[0]

    def path(self, project_id: str, name: str) -> Path:
        path = self.root / project_id / name
        if not NAME_RE.match(name) or not path.is_file():
            raise NotFound("Backup not found")
        return path

    def delete(self, project_id: str, name: str) -> None:
        self.path(project_id, name).unlink()
