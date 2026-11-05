from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.deps import Ctx
from app.cohort.models import (
    CohortBalanceRequest,
    CohortBalanceResponse,
    RowsRequest,
    RowsResponse,
    SummaryRequest,
    SummaryResponse,
    Timeline,
)
from app.cohort.service import CohortService
from app.variables.service import VariableService

router = APIRouter(tags=["cohort"])


def cohort_service(ctx: Ctx) -> CohortService:
    variables = VariableService(ctx.workspace, ctx.index, ctx.locks, ctx.bus)
    return CohortService(variables, ctx.index)


@router.post("/projects/{pid}/cohort/rows", response_model=RowsResponse)
async def cohort_rows(pid: str, body: RowsRequest, ctx: Ctx) -> RowsResponse:
    """Case → scan rows over the requested columns: filtered, sorted and paged by case.
    A column shows the common value in the case row, else `null` with the column listed in
    `differs`. `sort.column` is a requested column or `case_id`; missing values sort last."""
    return await cohort_service(ctx).rows(pid, body)


@router.post("/projects/{pid}/cohort/summary", response_model=SummaryResponse)
async def cohort_summary(pid: str, body: SummaryRequest, ctx: Ctx) -> SummaryResponse:
    """The column over the filtered rows, at the variable's level: categorical as the top
    20 values plus `other` and `missing`; numeric/date as 20 equal-width bins plus `missing`."""
    return await cohort_service(ctx).summary(pid, body)


@router.post("/projects/{pid}/cohort/balance", response_model=CohortBalanceResponse)
async def cohort_balance(pid: str, body: CohortBalanceRequest, ctx: Ctx) -> CohortBalanceResponse:
    """Two categorical variables over the filtered rows: counts by level, χ² or Fisher exact
    (expected counts under 5), Cramér's V. Levels with fewer than 5 rows are listed as excluded."""
    return await cohort_service(ctx).balance(pid, body)


@router.get("/projects/{pid}/cohort/timeline/{case_id}", response_model=Timeline)
async def cohort_timeline(pid: str, case_id: str, ctx: Ctx) -> Timeline:
    """One case's scans and events as days from its earliest dated scan. Only day offsets are
    returned, never a calendar date."""
    return await cohort_service(ctx).timeline(pid, case_id)
