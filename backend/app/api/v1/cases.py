"""API-20/21 case summaries and detail."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from app.api.v1.deps import Ctx
from app.api.v1.imports import ingest_service
from app.api.v1.paging import Page, Paging, paginate
from app.curation.models import RollupStatus
from app.ingest.codes import QcCode
from app.ingest.models import CaseSummary, ItemStatus, Phase
from app.ingest.schemas import CaseDetail
from app.variables.table import parse_var_params

router = APIRouter(tags=["cases"])

CaseSort = Literal["case_id", "-case_id", "n_warnings", "-n_warnings"]


@router.get("/projects/{pid}/cases", response_model=Page[CaseSummary])
async def list_cases(
    pid: str,
    ctx: Ctx,
    paging: Paging,
    request: Request,
    q: Annotated[str | None, Query(description="Substring of case_id / patient_id")] = None,
    phase: Annotated[Phase | None, Query()] = None,
    status: Annotated[
        ItemStatus | None, Query(description="Default hides all-excluded_upstream cases")
    ] = None,
    curation_status: Annotated[
        RollupStatus | None, Query(description="CUR-08 case rollup (the Search view's Status)")
    ] = None,
    warning: Annotated[QcCode | None, Query()] = None,
    has_voi: Annotated[bool | None, Query()] = None,
    sort: Annotated[CaseSort, Query()] = "case_id",
) -> Page[CaseSummary]:
    """Also accepts `var.{name}=value` (repeatable, OR) and `var.{name}=min..max` (VAR-10);
    a case matches when any of its items matches every variable filter."""
    svc = ingest_service(ctx)
    filters = parse_var_params(list(request.query_params.multi_items()))
    var_cases = (await svc.variables.filter_ids(pid, filters))["cases"] if filters else None
    rows = svc.cases(
        pid,
        q=q,
        var_cases=var_cases,
        phase=phase,
        status=status,
        curation_status=curation_status,
        warning=warning,
        has_voi=has_voi,
        sort=sort,
    )
    return paginate(rows, paging)


@router.get("/projects/{pid}/cases/{cid}", response_model=CaseDetail)
def get_case(pid: str, cid: str, ctx: Ctx) -> CaseDetail:
    return ingest_service(ctx).case_detail(pid, cid)
