"""Segmentation sets; `default_seg` is set through `PATCH /projects/{pid}`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from app.api.v1.deps import Ctx
from app.core.errors import JobConflict, NotFound, ValidationProblem
from app.ingest.segmentation_imports import (
    SegmentationImportRequest,
    SegmentationImportStarted,
    start_import,
)
from app.ingest.service import IngestService
from app.jobs.types import JobInfo
from app.projects.models import SegmentationSet

router = APIRouter(tags=["segmentations"])


class SegmentationInfo(SegmentationSet):
    n_items: int = 0  # items with a mask in this set
    is_default: bool = False


class SegmentationPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    label_mapping: dict[str, int] | None = None


def _infos(ctx: Ctx, pid: str, *, removed: bool = False) -> list[SegmentationInfo]:
    cfg = ctx.workspace.get(pid)
    items = ctx.index.load(pid).items
    return [
        SegmentationInfo(
            **s.model_dump(),
            n_items=sum(1 for i in items if s.seg_id in i.masks),
            is_default=s.seg_id == cfg.default_seg,
        )
        for s in cfg.segmentations
        if s.active != removed
    ]


@router.get("/projects/{pid}/segmentations", response_model=list[SegmentationInfo])
def list_segmentations(
    ctx: Ctx,
    pid: str,
    removed: Annotated[bool, Query()] = False,
) -> list[SegmentationInfo]:
    return _infos(ctx, pid, removed=removed)


@router.patch("/projects/{pid}/segmentations/{seg}", response_model=SegmentationInfo)
async def patch_segmentation(
    ctx: Ctx, pid: str, seg: str, body: SegmentationPatch
) -> SegmentationInfo:
    cur = ctx.workspace.get(pid).segmentation(seg)
    if cur is None:
        raise NotFound(f"Segmentation set {seg!r} not found")
    update: dict[str, object] = {}
    if body.name is not None:
        update["name"] = body.name.strip()
    if body.label_mapping is not None:
        values = {e.value for e in ctx.workspace.get(pid).label_map}
        bad = [k for k, v in body.label_mapping.items() if v not in values or not k.isdigit()]
        if bad:
            raise ValidationProblem(
                "label_mapping keys must be set values and targets project label values",
                errors=[{"loc": ["body", "label_mapping", k], "msg": "unknown"} for k in bad],
            )
        update["label_mapping"] = body.label_mapping
        update["unmatched"] = [u for u in cur.unmatched if str(u) not in body.label_mapping]
    await ctx.workspace.put_segmentation(pid, cur.model_copy(update=update))
    ctx.bus.publish(pid, "project.updated", {"fields": ["segmentations"]})
    return next(i for i in _infos(ctx, pid) if i.seg_id == seg)


@router.post(
    "/projects/{pid}/segmentations/imports",
    response_model=SegmentationImportStarted,
    status_code=202,
)
async def import_segmentation(
    ctx: Ctx, pid: str, body: SegmentationImportRequest
) -> SegmentationImportStarted:
    return await start_import(ctx, pid, body)


@router.post("/projects/{pid}/segmentations/reindex", response_model=JobInfo, status_code=202)
async def reindex_segmentations(ctx: Ctx, pid: str) -> JobInfo:
    job_id = await IngestService(
        ctx.workspace, ctx.index, ctx.jobs, ctx.bus, ctx.locks, ctx.after_index
    ).reindex(pid)
    if job_id is None:
        raise ValidationProblem("The project has no committed source import to reindex")
    return ctx.jobs.get(job_id)


@router.delete("/projects/{pid}/segmentations/{seg}", status_code=204)
async def remove_segmentation(ctx: Ctx, pid: str, seg: str) -> Response:
    if ctx.jobs.active(pid, "index") is not None:
        raise JobConflict("Wait for indexing or segmentation import to finish")
    await ctx.workspace.set_segmentation_active(pid, seg, False)
    ctx.index.invalidate(pid)
    ctx.bus.publish(pid, "project.updated", {"fields": ["segmentations", "default_seg"]})
    return Response(status_code=204)


@router.post("/projects/{pid}/segmentations/{seg}/restore", response_model=SegmentationInfo)
async def restore_segmentation(ctx: Ctx, pid: str, seg: str) -> SegmentationInfo:
    if ctx.jobs.active(pid, "index") is not None:
        raise JobConflict("Wait for indexing or segmentation import to finish")
    await ctx.workspace.set_segmentation_active(pid, seg, True)
    await IngestService(
        ctx.workspace, ctx.index, ctx.jobs, ctx.bus, ctx.locks, ctx.after_index
    ).reapply_segmentations(pid)
    ctx.bus.publish(pid, "project.updated", {"fields": ["segmentations", "default_seg"]})
    return next(i for i in _infos(ctx, pid) if i.seg_id == seg)
