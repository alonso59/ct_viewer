"""API-69: source operations are controlled by durable IDs, never paths in URLs."""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.v1.deps import Ctx
from app.api.v1.paging import Page, Paging, paginate
from app.sources import open as open_mode
from app.tasks.source_inventory import InventoryPage
from app.tasks.source_operations import (
    SourceOperation,
    SourceOperationControl,
    SourceOperationConvert,
    SourceOperationEstimate,
    SourceOperationStart,
)
from app.tasks.source_plans import SourcePlanPage

router = APIRouter(tags=["source-operations"])


@router.post("/source-operations", response_model=SourceOperation, status_code=202)
async def start(ctx: Ctx, body: SourceOperationStart) -> SourceOperation:
    return await ctx.source_operations.start(body)


@router.get("/source-operations", response_model=Page[SourceOperation])
async def list_operations(ctx: Ctx, pg: Paging) -> Page[SourceOperation]:
    page = paginate(ctx.source_operations.list(), pg)
    return page.model_copy(
        update={
            "items": [
                await ctx.source_operations.view(row.operation_id, include_run=False)
                for row in page.items
            ]
        }
    )


@router.get("/source-operations/{oid}", response_model=SourceOperation)
async def get(ctx: Ctx, oid: str) -> SourceOperation:
    return await ctx.source_operations.view(oid)


@router.post("/source-operations/{oid}/open", response_model=open_mode.OpenSession, status_code=201)
def open_result(ctx: Ctx, oid: str) -> open_mode.OpenSession:
    session = ctx.source_operations.open_session(oid, reopen=True)
    ctx.open_sessions.put(session)
    return open_mode.preview(session)


@router.get("/source-operations/{oid}/series", response_model=InventoryPage)
async def series(
    ctx: Ctx,
    oid: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    cursor: str | None = None,
) -> InventoryPage:
    page = await asyncio.to_thread(ctx.source_operations.series_page, oid, limit, cursor)
    return InventoryPage.model_validate(page)


@router.post("/source-operations/{oid}/cancel", response_model=SourceOperation)
async def cancel(ctx: Ctx, oid: str, body: SourceOperationControl) -> SourceOperation:
    return await ctx.source_operations.cancel(oid, body)


@router.post("/source-operations/{oid}/resume", response_model=SourceOperation, status_code=202)
async def resume(ctx: Ctx, oid: str, body: SourceOperationControl) -> SourceOperation:
    return await ctx.source_operations.resume(oid, body)


@router.post(
    "/source-operations/{oid}/retry-failed", response_model=SourceOperation, status_code=202
)
async def retry_failed(ctx: Ctx, oid: str, body: SourceOperationControl) -> SourceOperation:
    return await ctx.source_operations.resume(oid, body, failed_only=True)


@router.post("/source-operations/{oid}/estimate", response_model=SourceOperation, status_code=202)
async def estimate(ctx: Ctx, oid: str, body: SourceOperationEstimate) -> SourceOperation:
    return await ctx.source_operations.estimate(oid, body)


@router.post("/source-operations/{oid}/convert", response_model=SourceOperation, status_code=202)
async def convert(ctx: Ctx, oid: str, body: SourceOperationConvert) -> SourceOperation:
    return await ctx.source_operations.convert(oid, body)


@router.get("/source-operations/{oid}/plan", response_model=SourcePlanPage)
async def plan(
    ctx: Ctx,
    oid: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    cursor: str | None = None,
    action: Literal["convert", "skip"] | None = None,
) -> SourcePlanPage:
    return await asyncio.to_thread(ctx.source_operations.plan_page, oid, limit, cursor, action)
