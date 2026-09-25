"""API-56..58 Labeling table plugin (LBL-*), mounted under `/api/v1/plugins/labeling/` (PLG-08)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, File, Header, UploadFile
from fastapi.responses import Response

from app.api.v1.deps import Ctx
from app.api.v1.paging import Paging, offset_of
from app.context import AppContext
from app.labeling.models import (
    CellEvent,
    CellsPage,
    CellsWrite,
    CellsWritten,
    ImportReport,
    LabelTable,
    TableCreate,
    TableInfo,
    TablePatch,
)
from app.labeling.service import LabelingService
from app.variables.rebuild import schedule_variables_rebuild
from app.variables.service import VariableService

router = APIRouter(prefix="/plugins/labeling/projects/{pid}", tags=["labeling"])
Reviewer = Annotated[str | None, Header(alias="X-Reviewer")]
Session = Annotated[str | None, Header(alias="X-Session-Id")]


def svc(ctx: AppContext) -> LabelingService:
    return LabelingService(ctx.workspace, ctx.index, ctx.locks, ctx.bus)


def _rebuild_variables(ctx: AppContext, pid: str) -> None:
    schedule_variables_rebuild(
        pid, VariableService(ctx.workspace, ctx.index, ctx.locks, ctx.bus).rebuild
    )


@router.get("/tables", response_model=list[TableInfo])
def list_tables(ctx: Ctx, pid: str, deleted: bool = False) -> list[TableInfo]:
    """`?deleted=true` lists only the deleted tables (LBL-10)."""
    return svc(ctx).tables(pid, deleted)


@router.post("/tables", response_model=LabelTable, status_code=201)
async def create_table(ctx: Ctx, pid: str, body: TableCreate) -> LabelTable:
    t = await svc(ctx).create(pid, body)
    _rebuild_variables(ctx, pid)
    return t


@router.patch("/tables/{tid}", response_model=LabelTable)
async def patch_table(ctx: Ctx, pid: str, tid: str, body: TablePatch) -> LabelTable:
    t = await svc(ctx).patch(pid, tid, body)
    _rebuild_variables(ctx, pid)
    return t


@router.get("/tables/{tid}/cells", response_model=CellsPage)
def get_cells(ctx: Ctx, pid: str, tid: str, paging: Paging, q: str | None = None) -> CellsPage:
    return svc(ctx).cells(pid, tid, offset_of(paging.cursor), paging.limit, q)


@router.post("/tables/{tid}/cells", response_model=CellsWritten)
async def write_cells(
    ctx: Ctx, pid: str, tid: str, body: CellsWrite, x_reviewer: Reviewer = None,
    x_session_id: Session = None,
) -> CellsWritten:  # fmt: skip
    out = await svc(ctx).write(pid, tid, body.cells, x_reviewer, x_session_id)
    _rebuild_variables(ctx, pid)
    return out


@router.get("/tables/{tid}/history", response_model=list[CellEvent])
def cell_history(
    ctx: Ctx, pid: str, tid: str, target: str | None = None, column_id: str | None = None
) -> list[CellEvent]:
    return svc(ctx).history(pid, tid, target, column_id)


@router.post("/tables/{tid}/import", response_model=ImportReport)
async def import_table(
    ctx: Ctx, pid: str, tid: str, file: Annotated[UploadFile, File()],
    x_reviewer: Reviewer = None, x_session_id: Session = None,
) -> ImportReport:  # fmt: skip
    report = await svc(ctx).import_csv(pid, tid, await file.read(), x_reviewer, x_session_id)
    _rebuild_variables(ctx, pid)
    return report


@router.get(
    "/tables/{tid}/export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}, "application/vnd.apache.parquet": {}}}},
)
def export_table(
    ctx: Ctx, pid: str, tid: str, format: Literal["csv", "parquet"] = "csv"
) -> Response:
    t = svc(ctx).table(pid, tid)
    body = svc(ctx).export(pid, tid, format)
    media = "text/csv" if format == "csv" else "application/vnd.apache.parquet"
    return Response(
        body, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{t.slug}.{format}"'},
    )  # fmt: skip
