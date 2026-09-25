"""API-63..65 native phase selection (PHS-*, ADR-0026): core routes, not under `/plugins/`."""

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
    str | None, Header(alias="X-Reviewer", description="Reviewer name or initials (ADR-0004)")
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
    """API-63 history, newest first (PHS-07)."""
    return paginate(phase_service(ctx).history(pid, case_id=case_id, scan_idx=scan_idx), paging)


@router.post("/events", response_model=PhaseEvent, status_code=201)
async def append_event(
    pid: str, body: PhaseIn, ctx: Ctx, x_reviewer: Reviewer = None, x_session_id: Session = None
) -> PhaseEvent:
    """API-63 one-click selection (PHS-01) or accepting the analyzer guess (PHS-04); replaces
    the effective phase at once and pushes `phase.appended` (PHS-05). 428 without `X-Reviewer`.
    """
    ev = await phase_service(ctx).append(pid, body, reviewer=x_reviewer, session_id=x_session_id)
    schedule_variables_rebuild(
        pid, VariableService(ctx.workspace, ctx.index, ctx.locks, ctx.bus).rebuild
    )  # the `phase` variable follows the effective value (VAR-12)
    return ev


@router.get("/state", response_model=PhaseState)
def get_state(pid: str, ctx: Ctx, case_id: Annotated[str | None, Query()] = None) -> PhaseState:
    """API-64 latest selection per scan (PHS-02) next to the value it overrides (PHS-03)."""
    return phase_service(ctx).state(pid, case_id=case_id)


@router.post("/exports", response_model=PhaseExportResult, status_code=201)
async def export_phase(pid: str, ctx: Ctx) -> PhaseExportResult:
    """API-65 write `exports/phase_selections.json` (PHS-06)."""
    return await phase_service(ctx).export(pid)
