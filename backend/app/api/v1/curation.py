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
from app.variables.rebuild import schedule_variables_rebuild
from app.variables.service import VariableService

router = APIRouter(tags=["curation"])

Reviewer = Annotated[
    str | None, Header(description="Reviewer name or initials; required for writes")
]


def curation_service(ctx: Ctx) -> CurationService:
    return CurationService(ctx.workspace, ctx.index, ctx.locks, ctx.bus)


def _after_import(ctx: Ctx, pid: str, report: V2ImportReport) -> V2ImportReport:
    """Phase events from an import change the `phase` variable."""
    if report.phase_events:
        svc = VariableService(ctx.workspace, ctx.index, ctx.locks, ctx.bus)
        schedule_variables_rebuild(pid, svc.rebuild)
    return report


@router.get("/projects/{pid}/curation/events", response_model=Page[CurationEvent])
def list_events(
    pid: str,
    ctx: Ctx,
    paging: Paging,
    item_id: Annotated[str | None, Query()] = None,
    case_id: Annotated[str | None, Query()] = None,
) -> Page[CurationEvent]:
    """History, newest first; every event is kept."""
    return paginate(curation_service(ctx).history(pid, item_id=item_id, case_id=case_id), paging)


@router.post("/projects/{pid}/curation/events", response_model=CurationEvent, status_code=201)
async def append_event(
    pid: str,
    body: EventIn,
    ctx: Ctx,
    x_reviewer: Reviewer = None,
    x_session_id: Annotated[str | None, Header(description="Per-tab id for audit")] = None,
) -> CurationEvent:
    """Append one decision; pushes `curation.appended`.

    428 `reviewer-required` without `X-Reviewer`.
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
    """Derived latest state per item and per case (last writer wins)."""
    return curation_service(ctx).state(pid, case_id=case_id, item_id=item_id)


@router.get(
    "/projects/{pid}/curation/queue",
    response_model=list[QueueRow],
    responses={200: {"content": {"text/csv": {}}, "description": "JSON rows, or CSV"}},
)
def get_queue(
    pid: str, ctx: Ctx, format: Annotated[Literal["json", "csv"], Query()] = "json"
) -> list[QueueRow] | Response:
    """Correction queue; CSV for 3D Slicer with absolute paths."""
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
    """Write `curation_state.csv` and an `events.jsonl` copy into the project's `exports/`."""
    return await curation_service(ctx).export(pid)


@router.post("/projects/{pid}/curation/import-v2", response_model=V2ImportReport, status_code=201)
async def import_v2(
    pid: str,
    ctx: Ctx,
    file: Annotated[UploadFile, File(description="v2 `curation_review.csv`")],
    x_reviewer: Reviewer = None,
) -> V2ImportReport:
    """Import v2 decisions as `source: "v2_import"` events.

    `X-Reviewer` is required and used for rows without a reviewer.
    """
    data = await file.read()
    return _after_import(
        ctx, pid, await curation_service(ctx).import_v2(pid, data, reviewer=x_reviewer)
    )


@router.post(
    "/projects/{pid}/curation/import-converter", response_model=V2ImportReport, status_code=201
)
async def import_converter(
    pid: str,
    ctx: Ctx,
    file: Annotated[UploadFile, File(description="The converter CLI's `curation.csv`")],
    x_reviewer: Reviewer = None,
) -> V2ImportReport:
    """Import the standalone converter's manual decisions once."""
    data = await file.read()
    report = await curation_service(ctx).import_converter(pid, data, reviewer=x_reviewer)
    return _after_import(ctx, pid, report)
