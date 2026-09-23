"""API-20/21 case summaries and detail."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.v1.deps import Ctx
from app.api.v1.imports import ingest_service
from app.api.v1.paging import Page, Paging, paginate
from app.ingest.codes import QcCode
from app.ingest.models import CaseSummary, ItemStatus, Phase
from app.ingest.schemas import CaseDetail

router = APIRouter(tags=["cases"])

CaseSort = Literal["case_id", "-case_id", "n_warnings", "-n_warnings"]


@router.get("/projects/{pid}/cases", response_model=Page[CaseSummary])
def list_cases(
    pid: str,
    ctx: Ctx,
    paging: Paging,
    q: Annotated[str | None, Query(description="Substring of case_id / patient_id")] = None,
    group: Annotated[str | None, Query()] = None,
    phase: Annotated[Phase | None, Query()] = None,
    status: Annotated[
        ItemStatus | None, Query(description="Default hides all-excluded_upstream cases")
    ] = None,
    warning: Annotated[QcCode | None, Query()] = None,
    has_voi: Annotated[bool | None, Query()] = None,
    sort: Annotated[CaseSort, Query()] = "case_id",
) -> Page[CaseSummary]:
    rows = ingest_service(ctx).cases(
        pid,
        q=q,
        group=group,
        phase=phase,
        status=status,
        warning=warning,
        has_voi=has_voi,
        sort=sort,
    )
    return paginate(rows, paging)


@router.get("/projects/{pid}/cases/{cid}", response_model=CaseDetail)
def get_case(pid: str, cid: str, ctx: Ctx) -> CaseDetail:
    return ingest_service(ctx).case_detail(pid, cid)
