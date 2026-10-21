"""API-22 item record."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Header

from app.api.v1.deps import Ctx
from app.api.v1.imports import ingest_service
from app.core.errors import NotFound, SourceMissing
from app.core.fsio import read_json
from app.ingest.recycle import RecyclePlan, RecycleRequest, RecycleResult, RecycleService
from app.ingest.schemas import ItemDetail
from app.variables.rebuild import schedule_variables_rebuild
from app.variables.service import VariableService

router = APIRouter(tags=["items"])


@router.get("/projects/{pid}/items/{iid}", response_model=ItemDetail)
def get_item(pid: str, iid: str, ctx: Ctx) -> ItemDetail:
    """Item record + `advanced` absolute paths + its warnings."""
    return ingest_service(ctx).item_detail(pid, iid)


@router.get("/projects/{pid}/items/{iid}/dicom-tags", response_model=dict[str, Any])
async def get_dicom_tags(pid: str, iid: str, ctx: Ctx) -> dict[str, Any]:
    """The item's DICOM JSON sidecar (DCM-04), read on demand only (DCM-05: PHI stays here)."""
    item = ctx.index.get_item(pid, iid)
    ref = item.extra.get("dicom_sidecar")
    if not isinstance(ref, str) or not ref:
        raise NotFound("item has no DICOM sidecar")
    path = ctx.workspace.resolver(pid).resolve(ref)
    if not path.is_file():
        raise SourceMissing("DICOM sidecar is missing")
    raw: Any = await asyncio.to_thread(read_json, path)
    if not isinstance(raw, dict):
        raise NotFound("DICOM sidecar is not a JSON object")
    return raw


@router.get("/projects/{pid}/items/{iid}/recycle", response_model=RecyclePlan)
def preview_recycle(pid: str, iid: str, ctx: Ctx) -> RecyclePlan:
    """API-66 / CUR-16: preview the whole scan, related outputs and default recycle bin."""
    return RecycleService(ctx.workspace, ctx.index, ctx.jobs, ctx.bus).preview(pid, iid)


@router.post("/projects/{pid}/items/{iid}/recycle", response_model=RecycleResult)
async def recycle_scan(
    pid: str,
    iid: str,
    body: RecycleRequest,
    ctx: Ctx,
    x_reviewer: Annotated[str | None, Header(alias="X-Reviewer")] = None,
) -> RecycleResult:
    """API-66: confirmed, audited removal; never a permanent delete."""
    service = RecycleService(ctx.workspace, ctx.index, ctx.jobs, ctx.bus)
    result = await service.recycle(pid, iid, body, x_reviewer)
    for project_id in result.project_ids:
        schedule_variables_rebuild(
            project_id, VariableService(ctx.workspace, ctx.index, ctx.locks, ctx.bus).rebuild
        )
    return result
