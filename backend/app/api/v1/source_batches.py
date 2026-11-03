"""Batch plans are controlled by durable plan IDs, never paths or folder names in URLs."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.deps import Ctx, Reviewer
from app.api.v1.paging import Page, Paging, paginate
from app.tasks.source_batches import (
    BatchPlanCreate,
    BatchPlanUpdate,
    SourceBatchPlan,
    view_of,
)

router = APIRouter(tags=["source-batches"])


@router.post("/source-batches", response_model=SourceBatchPlan, status_code=201)
async def create(ctx: Ctx, body: BatchPlanCreate, x_reviewer: Reviewer = None) -> SourceBatchPlan:
    return view_of(await ctx.source_batches.create(body, x_reviewer))


@router.get("/source-batches", response_model=Page[SourceBatchPlan])
def list_plans(ctx: Ctx, pg: Paging) -> Page[SourceBatchPlan]:
    page = paginate(ctx.source_batches.plans(), pg)
    return Page[SourceBatchPlan](
        items=[view_of(p) for p in page.items], next_cursor=page.next_cursor, total=page.total
    )


@router.get("/source-batches/{plan_id}", response_model=SourceBatchPlan)
def get(ctx: Ctx, plan_id: str) -> SourceBatchPlan:
    return view_of(ctx.source_batches.get(plan_id))


@router.patch("/source-batches/{plan_id}", response_model=SourceBatchPlan)
async def update(ctx: Ctx, plan_id: str, body: BatchPlanUpdate) -> SourceBatchPlan:
    return view_of(await ctx.source_batches.update(plan_id, body))


@router.post("/source-batches/{plan_id}/start", response_model=SourceBatchPlan, status_code=202)
async def start(ctx: Ctx, plan_id: str) -> SourceBatchPlan:
    return view_of(await ctx.source_batches.start(plan_id))


@router.post("/source-batches/{plan_id}/continue", response_model=SourceBatchPlan, status_code=202)
async def resume(ctx: Ctx, plan_id: str) -> SourceBatchPlan:
    return view_of(await ctx.source_batches.resume_plan(plan_id))


@router.post("/source-batches/{plan_id}/cancel", response_model=SourceBatchPlan)
async def cancel(ctx: Ctx, plan_id: str) -> SourceBatchPlan:
    return view_of(await ctx.source_batches.cancel(plan_id))


@router.post(
    "/source-batches/{plan_id}/add-new-folders", response_model=SourceBatchPlan, status_code=202
)
async def add_new_folders(ctx: Ctx, plan_id: str) -> SourceBatchPlan:
    return view_of(await ctx.source_batches.add_new_folders(plan_id))
