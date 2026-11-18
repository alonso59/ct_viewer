from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Response

from app.api.v1.deps import Ctx
from app.ingest.recycle_bin import (
    DeleteRequest,
    RecycleBinEntry,
    RecycleBinService,
    RestorePlan,
    RestoreRequest,
    RestoreResult,
)
from app.variables.rebuild import schedule_variables_rebuild
from app.variables.service import VariableService

router = APIRouter(tags=["items"])


def service(ctx: Ctx) -> RecycleBinService:
    return RecycleBinService(ctx.workspace, ctx.index, ctx.jobs, ctx.bus)


@router.get("/projects/{pid}/recycle-bin", response_model=list[RecycleBinEntry])
def list_recycle_bin(pid: str, ctx: Ctx) -> list[RecycleBinEntry]:
    """The project's recycled scans, newest first."""
    return service(ctx).list(pid)


@router.get("/projects/{pid}/recycle-bin/{rid}/restore", response_model=RestorePlan)
def preview_restore(pid: str, rid: str, ctx: Ctx) -> RestorePlan:
    """Check that the scan can go back and count what moves; writes nothing."""
    return service(ctx).preview_restore(pid, rid)


@router.post("/projects/{pid}/recycle-bin/{rid}/restore", response_model=RestoreResult)
async def restore_scan(
    pid: str,
    rid: str,
    body: RestoreRequest,
    ctx: Ctx,
    x_reviewer: Annotated[str | None, Header(alias="X-Reviewer")] = None,
) -> RestoreResult:
    result = await service(ctx).restore(pid, rid, body, x_reviewer)
    for project_id in result.project_ids:
        schedule_variables_rebuild(
            project_id, VariableService(ctx.workspace, ctx.index, ctx.locks, ctx.bus).rebuild
        )
    return result


@router.post("/projects/{pid}/recycle-bin/{rid}/delete", status_code=204)
async def delete_recycled_scan(pid: str, rid: str, body: DeleteRequest, ctx: Ctx) -> Response:
    """Remove the recycled files, manifest and metadata backups for good."""
    await service(ctx).delete(pid, rid, body)
    return Response(status_code=204)
