"""API-50..54 curation: events, derived state, correction queue, exports, v2 import (CUR-*)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, File, Header, Query, Response, UploadFile

from app.api.v1.deps import Ctx
from app.api.v1.paging import Page, Paging, paginate
from app.curation.models import (
    CurationEvent,
    CurationState,
    EventIn,
    ExportResult,
    QueueRow,
    V2ImportReport,
)
from app.curation.service import CurationService

router = APIRouter(tags=["curation"])

Reviewer = Annotated[
    str | None, Header(description="Reviewer name or initials (CUR-01); required for writes")
]


def curation_service(ctx: Ctx) -> CurationService:
    return CurationService(ctx.workspace, ctx.index, ctx.locks, ctx.bus)


@router.get("/projects/{pid}/curation/events", response_model=Page[CurationEvent])
def list_events(
    pid: str,
    ctx: Ctx,
    paging: Paging,
    item_id: Annotated[str | None, Query()] = None,
    case_id: Annotated[str | None, Query()] = None,
) -> Page[CurationEvent]:
    """API-50 history, newest first (CUR-14); every event is kept (CUR-02/12)."""
    return paginate(curation_service(ctx).history(pid, item_id=item_id, case_id=case_id), paging)


@router.post("/projects/{pid}/curation/events", response_model=CurationEvent, status_code=201)
async def append_event(
    pid: str,
    body: EventIn,
    ctx: Ctx,
    x_reviewer: Reviewer = None,
    x_session_id: Annotated[str | None, Header(description="Per-tab id for audit")] = None,
) -> CurationEvent:
    """API-50 append one decision (CUR-02/03/05/06/07); pushes `curation.appended` (CUR-11).

    428 `reviewer-required` without `X-Reviewer` (CUR-01).
    """
    return await curation_service(ctx).append(
        pid, body, reviewer=x_reviewer, session_id=x_session_id
    )


@router.get("/projects/{pid}/curation/state", response_model=CurationState)
def get_state(
    pid: str,
    ctx: Ctx,
    case_id: Annotated[str | None, Query()] = None,
    item_id: Annotated[str | None, Query()] = None,
) -> CurationState:
    """API-51 derived latest state per item and per case (CUR-08, last-writer-wins CUR-12)."""
    return curation_service(ctx).state(pid, case_id=case_id, item_id=item_id)


@router.get(
    "/projects/{pid}/curation/queue",
    response_model=list[QueueRow],
    responses={200: {"content": {"text/csv": {}}, "description": "JSON rows, or CSV"}},
)
def get_queue(
    pid: str, ctx: Ctx, format: Annotated[Literal["json", "csv"], Query()] = "json"
) -> list[QueueRow] | Response:
    """API-52 correction queue (CUR-09); CSV for 3D Slicer with absolute paths."""
    svc = curation_service(ctx)
    if format == "csv":
        return Response(
            svc.queue_csv(pid),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="correction_queue.csv"'},
        )
    return svc.queue(pid)


@router.post("/projects/{pid}/curation/exports", response_model=ExportResult, status_code=201)
async def export_curation(pid: str, ctx: Ctx) -> ExportResult:
    """API-53 write the CUR-10 files into the project's `exports/`."""
    return await curation_service(ctx).export(pid)


@router.post("/projects/{pid}/curation/import-v2", response_model=V2ImportReport, status_code=201)
async def import_v2(
    pid: str,
    ctx: Ctx,
    file: Annotated[UploadFile, File(description="v2 `curation_review.csv`")],
    x_reviewer: Reviewer = None,
) -> V2ImportReport:
    """API-54 import v2 decisions as `source: "v2_import"` events (CUR-13).

    `X-Reviewer` is required (CUR-01) and used for rows without a reviewer.
    """
    data = await file.read()
    return await curation_service(ctx).import_v2(pid, data, reviewer=x_reviewer)


@router.post(
    "/projects/{pid}/curation/import-converter", response_model=V2ImportReport, status_code=201
)
async def import_converter(
    pid: str,
    ctx: Ctx,
    file: Annotated[UploadFile, File(description="The converter CLI's `curation.csv`")],
    x_reviewer: Reviewer = None,
) -> V2ImportReport:
    """API-55: import the standalone converter's manual decisions once (CUR-15, DCM-08)."""
    data = await file.read()
    return await curation_service(ctx).import_converter(pid, data, reviewer=x_reviewer)
