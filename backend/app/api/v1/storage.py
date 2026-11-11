from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.v1.deps import Ctx
from app.projects.backups import Backup, BackupState
from app.projects.storage import DefaultBody, LocationBody, LocationTest, StorageState
from app.tasks.compute import report

router = APIRouter(tags=["storage"])


def _workspaces(ctx: Ctx) -> dict[str, Any] | None:
    """Managed workspaces as the runner last read them from the site's tool, if it has one."""
    found = (report(ctx.workspace.root / "queue").get("scheduler") or {}).get("workspaces")
    return found if isinstance(found, dict) else None


def _state(ctx: Ctx) -> StorageState:
    return ctx.storage.state(ctx.workspace.entries(), _workspaces(ctx))


@router.get("/storage", response_model=StorageState)
def get_storage(ctx: Ctx) -> StorageState:
    return _state(ctx)


@router.post("/storage/locations", response_model=StorageState, status_code=201)
def register_location(ctx: Ctx, body: LocationBody) -> StorageState:
    """Only at or below a folder the operator allows; nothing on disk is changed."""
    ctx.storage.register(body, _workspaces(ctx))
    return _state(ctx)


@router.delete("/storage/locations/{location_id}", response_model=StorageState)
def remove_location(ctx: Ctx, location_id: str) -> StorageState:
    ctx.storage.remove(location_id)
    return _state(ctx)


@router.post("/storage/locations/{location_id}/test", response_model=LocationTest)
def test_location(ctx: Ctx, location_id: str) -> LocationTest:
    return ctx.storage.test(location_id, ctx.workspace.entries())


@router.put("/storage/default", response_model=StorageState)
def set_default_location(ctx: Ctx, body: DefaultBody) -> StorageState:
    ctx.storage.set_default(body.location_id)
    return _state(ctx)


def _backup_state(ctx: Ctx, pid: str) -> BackupState:
    entry = ctx.workspace.entry(pid)
    folder = ctx.workspace.folder(pid) if entry.dataset_root else None
    return ctx.backups.state(pid, folder, bool(entry.dataset_root))


@router.get("/projects/{pid}/backups", response_model=BackupState)
def list_backups(ctx: Ctx, pid: str) -> BackupState:
    return _backup_state(ctx, pid)


@router.post("/projects/{pid}/backups", response_model=Backup, status_code=201)
async def create_backup(ctx: Ctx, pid: str) -> Backup:
    """Copies the project's state, never images or outputs, into the application state folder."""
    return await ctx.workspace.backup(pid, ctx.backups)


@router.get("/projects/{pid}/backups/{name}", response_class=FileResponse)
def download_backup(ctx: Ctx, pid: str, name: str) -> FileResponse:
    """The backup file, to restore with the bundle import."""
    ctx.workspace.entry(pid)
    return FileResponse(ctx.backups.path(pid, name), media_type="application/zip", filename=name)


@router.delete("/projects/{pid}/backups/{name}", status_code=204)
async def delete_backup(ctx: Ctx, pid: str, name: str) -> None:
    ctx.workspace.entry(pid)
    await asyncio.to_thread(ctx.backups.delete, pid, name)
