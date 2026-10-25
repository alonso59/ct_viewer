from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query

from app.api.v1.deps import Ctx
from app.api.v1.paging import Page, Paging, paginate
from app.context import AppContext
from app.phase.models import PhaseEvent, PhaseExportResult, PhaseIn, PhaseState
from app.phase.service import PhaseService
from app.variables.rebuild import schedule_variables_rebuild
from app.variables.service import VariableService

router = APIRouter(prefix="/projects/{pid}/phase", tags=["phase"])
Reviewer = Annotated[
    str | None, Header(alias="X-Reviewer", description="Reviewer name or initials")
]
Session = Annotated[str | None, Header(alias="X-Session-Id", description="Per-tab id for audit")]


def phase_service(ctx: AppContext) -> PhaseService:
    return PhaseService(ctx.workspace, ctx.index, ctx.locks, ctx.bus)


@router.get("/events", response_model=Page[PhaseEvent])
def list_events(
    pid: str,
    ctx: Ctx,
    paging: Paging,
    case_id: Annotated[str | None, Query()] = None,
    scan_idx: Annotated[str | None, Query()] = None,
) -> Page[PhaseEvent]:
    """History, newest first."""
    return paginate(phase_service(ctx).history(pid, case_id=case_id, scan_idx=scan_idx), paging)


@router.post("/events", response_model=PhaseEvent, status_code=201)
async def append_event(
    pid: str, body: PhaseIn, ctx: Ctx, x_reviewer: Reviewer = None, x_session_id: Session = None
) -> PhaseEvent:
    """One-click selection or accepting the analyzer guess; replaces the effective phase at once
    and pushes `phase.appended`. 428 without `X-Reviewer`.
    """
    ev = await phase_service(ctx).append(pid, body, reviewer=x_reviewer, session_id=x_session_id)
    schedule_variables_rebuild(
        pid, VariableService(ctx.workspace, ctx.index, ctx.locks, ctx.bus).rebuild
    )  # the `phase` variable follows the effective value
    return ev


@router.get("/state", response_model=PhaseState)
def get_state(pid: str, ctx: Ctx, case_id: Annotated[str | None, Query()] = None) -> PhaseState:
    """Latest selection per scan next to the value it overrides."""
    return phase_service(ctx).state(pid, case_id=case_id)


@router.post("/exports", response_model=PhaseExportResult, status_code=201)
async def export_phase(pid: str, ctx: Ctx) -> PhaseExportResult:
    """Write `exports/phase_selections.json`."""
    return await phase_service(ctx).export(pid)
