"""Analysis tables: list, manifest and export. Their dashboard views live in `dashboard`."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from app.api.v1.deps import Ctx
from app.tables.models import TableManifest, TableSummary
from app.tables.service import TablesService

router = APIRouter(tags=["tables"])

MEDIA = {"csv": "text/csv", "parquet": "application/vnd.apache.parquet"}


@router.get("/projects/{pid}/tables", response_model=list[TableSummary])
async def list_tables(pid: str, ctx: Ctx) -> list[TableSummary]:
    """Every analysis table of the project (radiomics runs and task tables), newest first."""
    return await TablesService(ctx.workspace).list(pid)


@router.get("/projects/{pid}/tables/{tid}", response_model=TableManifest)
async def get_table(pid: str, tid: str, ctx: Ctx) -> TableManifest:
    """The table's manifest with its columns."""
    return await TablesService(ctx.workspace).get(pid, tid)


@router.get(
    "/projects/{pid}/tables/{tid}/export",
    response_class=Response,
    responses={200: {"content": {m: {} for m in MEDIA.values()}, "description": "The table"}},
)
async def export_table(
    pid: str,
    tid: str,
    ctx: Ctx,
    format: Annotated[Literal["csv", "parquet"], Query()] = "csv",
    shape: Annotated[Literal["long", "wide"], Query()] = "wide",
) -> Response:
    """The table's values: `long` (one row per value) or `wide` (one row per observation)."""
    data = await TablesService(ctx.workspace).export(pid, tid, format, shape)
    return Response(
        data,
        media_type=MEDIA[format],
        headers={"Content-Disposition": f'attachment; filename="table_{tid}_{shape}.{format}"'},
    )
