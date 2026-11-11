"""Storage locations: the folders the user works in, chosen inside the operator's allowed roots.

The registry narrows what the folder browser offers; it never widens the operator's policy, and
existing projects keep resolving through the unchanged guards. Availability and permissions are
computed when asked, never stored."""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.errors import NotFound, ValidationProblem
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import new_ulid
from app.core.paths import PathGuard, is_within, realpath
from app.projects.models import WorkspaceEntry

REGISTRY_FILE = "storage.json"
MAX_LOCATIONS = 64
Access = Literal["read_only", "read_write"]


class LocationBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    access: Access = "read_write"
    label: str = Field(default="", max_length=80)


class ManagedWorkspace(BaseModel):
    """What the site's workspace tool reported, and when; never authoritative."""

    name: str
    filesystem: str | None = None
    expires: str | None = None
    extensions: int | None = None
    observed_at: str | None = None


class StorageLocation(BaseModel):
    id: str
    kind: Literal["local_directory", "managed_hpc_workspace"]
    path: str
    access: Access
    label: str = ""
    workspace: ManagedWorkspace | None = None
    available: bool = False
    readable: bool = False
    writable: bool = False
    # Seconds until the workspace expires, from the last report; None when unknown.
    remaining_seconds: int | None = None
    projects: list[str] = Field(default_factory=list)


class DiscoveredWorkspace(ManagedWorkspace):
    path: str
    # Empty when the workspace can be registered; else why not.
    blocked: str = ""


class StorageState(BaseModel):
    locations: list[StorageLocation] = Field(default_factory=list)
    default_location: str | None = None
    # False when the operator set no allowed roots: nothing can be registered.
    registrable: bool = False
    allowed_roots: list[str] = Field(default_factory=list)
    # None where no workspace tool reports; a list (possibly empty) where one does.
    discovered: list[DiscoveredWorkspace] | None = None
    discovery_error: str | None = None


class DefaultBody(BaseModel):
    location_id: str | None = None


class LocationTest(BaseModel):
    location: StorageLocation
    # How write access was checked: a probe file where outputs may go, else permissions only.
    method: Literal["probe", "permissions", "none"]
    error: str | None = None


class Storage:
    def __init__(self, workspace_root: Path, guard: PathGuard, derived_guard: PathGuard) -> None:
        self.root = realpath(workspace_root)
        self.guard = guard
        self.derived_guard = derived_guard
        self.path = workspace_root / REGISTRY_FILE

    def _read(self) -> dict[str, Any]:
        try:
            raw = read_json(self.path)
        except (OSError, ValueError):
            return {"locations": [], "default": None}
        rows = [row for row in raw.get("locations", []) if isinstance(row, dict)]
        return {"locations": rows, "default": raw.get("default")}

    def _write(self, data: dict[str, Any]) -> None:
        atomic_write_json(self.path, {"format_version": 1, **data})

    def read_only(self, path: Path) -> bool:
        """Whether the closest registered location around `path` is read-only."""
        real = realpath(path)
        around = [row for row in self._read()["locations"] if is_within(real, Path(row["path"]))]
        return (
            bool(around) and max(around, key=lambda row: len(row["path"]))["access"] == "read_only"
        )

    def paths(self) -> list[Path]:
        """Registered folders that still lie inside the operator's roots."""
        found = [Path(row["path"]) for row in self._read()["locations"]]
        return [p for p in found if self.guard.restricted and self.guard.is_allowed(p)]

    def _status(
        self, row: dict[str, Any], entries: list[WorkspaceEntry], reported: dict[str, Any]
    ) -> StorageLocation:
        path = Path(row["path"])
        meta = row.get("workspace")
        live = reported.get(str(path))
        if live is not None:
            meta = {**live, "observed_at": reported.get("at")}
        expires = (meta or {}).get("expires")
        remaining = None
        if expires:
            with contextlib.suppress(ValueError):
                moment = datetime.fromisoformat(expires)
                remaining = int((moment - datetime.now(UTC)).total_seconds())
        allowed = self.guard.restricted and self.guard.is_allowed(path)
        available = allowed and path.is_dir()
        return StorageLocation(
            id=row["id"],
            kind="managed_hpc_workspace" if meta else "local_directory",
            path=str(path),
            access=row["access"],
            label=row.get("label", ""),
            workspace=ManagedWorkspace.model_validate(meta) if meta else None,
            available=available,
            readable=available and os.access(path, os.R_OK | os.X_OK),
            writable=available and row["access"] == "read_write" and os.access(path, os.W_OK),
            remaining_seconds=remaining,
            projects=[
                e.name for e in entries if e.dataset_root and is_within(Path(e.dataset_root), path)
            ],
        )

    def state(
        self, entries: list[WorkspaceEntry], workspaces: dict[str, Any] | None
    ) -> StorageState:
        data = self._read()
        items = (workspaces or {}).get("items") or []
        reported: dict[str, Any] = {
            str(realpath(item["path"])): {
                k: item.get(k) for k in ("name", "filesystem", "expires", "extensions")
            }
            for item in items
            if isinstance(item, dict) and item.get("path") and item.get("name")
        }
        taken = {row["path"] for row in data["locations"]}
        discovered = [
            DiscoveredWorkspace(
                **meta,
                path=path,
                observed_at=(workspaces or {}).get("at"),
                blocked=""
                if self.guard.restricted and self.guard.is_allowed(Path(path))
                else "outside the folders the operator allows",
            )
            for path, meta in reported.items()
            if path not in taken
        ]
        reported["at"] = (workspaces or {}).get("at")
        return StorageState(
            locations=[self._status(row, entries, reported) for row in data["locations"]],
            default_location=data["default"],
            registrable=self.guard.restricted,
            allowed_roots=[str(r) for r in self.guard.allowed_roots],
            discovered=discovered if workspaces is not None else None,
            discovery_error=(workspaces or {}).get("error"),
        )

    def register(self, body: LocationBody, workspaces: dict[str, Any] | None) -> None:
        if not self.guard.restricted:
            raise ValidationProblem(
                "No allowed folders are configured, so no storage location can be registered"
            )
        raw = Path(body.path)
        if not raw.is_absolute():
            raise ValidationProblem("A storage location needs an absolute path")
        real = self.guard.check(raw)
        if is_within(real, self.root):
            raise ValidationProblem(
                "The application's own state folder cannot be a storage location"
            )
        if not real.is_dir():
            raise ValidationProblem("That folder does not exist or is not a folder")
        if not os.access(real, os.R_OK | os.X_OK):
            raise ValidationProblem("You cannot read that folder")
        if body.access == "read_write" and not os.access(real, os.W_OK):
            raise ValidationProblem("You cannot write to that folder; register it as read-only")
        data = self._read()
        if any(row["path"] == str(real) for row in data["locations"]):
            raise ValidationProblem("That folder is already a storage location")
        if len(data["locations"]) >= MAX_LOCATIONS:
            raise ValidationProblem(f"At most {MAX_LOCATIONS} storage locations")
        managed = next(
            (
                item
                for item in (workspaces or {}).get("items") or []
                if isinstance(item, dict) and item.get("path") and realpath(item["path"]) == real
            ),
            None,
        )
        row: dict[str, Any] = {
            "id": new_ulid(),
            "path": str(real),
            "access": body.access,
            "label": body.label.strip(),
        }
        if managed is not None:
            row["workspace"] = {
                **{k: managed.get(k) for k in ("name", "filesystem", "expires", "extensions")},
                "observed_at": (workspaces or {}).get("at"),
            }
        data["locations"].append(row)
        if data["default"] is None and body.access == "read_write":
            data["default"] = row["id"]
        self._write(data)

    def _row(self, data: dict[str, Any], location_id: str) -> dict[str, Any]:
        for row in data["locations"]:
            if row["id"] == location_id:
                return dict(row)
        raise NotFound(f"Storage location {location_id!r} not found")

    def remove(self, location_id: str) -> None:
        """Forgets the location; nothing on disk is touched."""
        data = self._read()
        self._row(data, location_id)
        data["locations"] = [row for row in data["locations"] if row["id"] != location_id]
        if data["default"] == location_id:
            data["default"] = None
        self._write(data)

    def set_default(self, location_id: str | None) -> None:
        data = self._read()
        if location_id is not None and self._row(data, location_id)["access"] != "read_write":
            raise ValidationProblem("The default location for new projects must be writable")
        data["default"] = location_id
        self._write(data)

    def test(self, location_id: str, entries: list[WorkspaceEntry]) -> LocationTest:
        """Checks the folder now. A probe file is written only where task outputs may go; a
        dataset folder is checked by permissions alone, so a source is never written."""
        row = self._row(self._read(), location_id)
        path = Path(row["path"])
        location = self._status(row, entries, {})
        if not location.available or row["access"] != "read_write":
            return LocationTest(location=location, method="none")
        if not self.derived_guard.is_allowed(path):
            return LocationTest(location=location, method="permissions")
        name = f".rw-probe-{new_ulid()}"
        try:
            folder = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                probe = os.open(
                    name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder
                )
                os.close(probe)
                os.unlink(name, dir_fd=folder)
            finally:
                os.close(folder)
        except OSError as exc:
            location.writable = False
            return LocationTest(location=location, method="probe", error=exc.strerror or str(exc))
        return LocationTest(location=location, method="probe")
