"""Request and response models for the Cohort read endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.analytics.models import TestOverride

CellValue = float | str | None


class RowsSort(BaseModel):
    """`column`: a requested column or `case_id`; missing values sort last."""

    column: str
    desc: bool = False


class RowsRequest(BaseModel):
    columns: list[str] = Field(default_factory=list)
    filters: dict[str, list[str]] = Field(default_factory=dict)
    q: str | None = None
    phase: str | None = None
    sort: RowsSort | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class ScanRow(BaseModel):
    scan_idx: str
    item_id: str
    phase: str
    modality: str | None = None
    values: dict[str, CellValue] = Field(default_factory=dict)


class CaseRow(BaseModel):
    case_id: str
    values: dict[str, CellValue] = Field(default_factory=dict)
    differs: list[str] = Field(default_factory=list)
    scans: list[ScanRow] = Field(default_factory=list)


class RowsResponse(BaseModel):
    n_cases: int
    n_scans: int
    rows: list[CaseRow] = Field(default_factory=list)


class SummaryRequest(BaseModel):
    column: str
    filters: dict[str, list[str]] = Field(default_factory=dict)


class SummaryBin(BaseModel):
    lo: str
    hi: str
    count: int


class SummaryResponse(BaseModel):
    """Categorical: the top 20 values plus `other` and `missing`; numeric/date:
    20 equal-width bins plus `missing`."""

    counts: dict[str, int] | None = None
    other: int = 0
    missing: int = 0
    bins: list[SummaryBin] | None = None


class CohortBalanceRequest(BaseModel):
    """Two categorical variables over the filtered rows; `test` forces χ² (`default`) or Fisher."""

    a: str
    b: str
    filters: dict[str, list[str]] = Field(default_factory=dict)
    test: TestOverride = "auto"


class CohortBalanceCell(BaseModel):
    row: str
    col: str
    n: int
    expected: float | None = None


class CohortBalanceResponse(BaseModel):
    """Counts of `a` (rows) by `b` (columns) with the test; levels under 5 are `excluded_*`."""

    unit: Literal["case", "scan"]
    rows: list[str] = Field(default_factory=list)
    cols: list[str] = Field(default_factory=list)
    cells: list[CohortBalanceCell] = Field(default_factory=list)
    excluded_rows: list[str] = Field(default_factory=list)
    excluded_cols: list[str] = Field(default_factory=list)
    test: Literal["chi2", "fisher"] | None = None
    reason: str = ""
    statistic: float | None = None
    p: float | None = None
    cramers_v: float | None = None
    n: int = 0
    missing: int = 0


class TimelineScan(BaseModel):
    scan_idx: str
    item_id: str
    phase: str
    day: int | None = None  # days from the anchor scan; None when the scan has no date


class TimelineEvent(BaseModel):
    table_id: str
    table: str
    target: str
    kind: str | None = None
    day: float | None = None
    values: dict[str, float | str | None] = Field(
        default_factory=dict
    )  # the other columns, by name


class Timeline(BaseModel):
    """One case on a day axis. Days count from `anchor_scan`, the earliest dated scan; no calendar
    date leaves the server. Without an anchor the scans cannot be placed."""

    case_id: str
    anchor_scan: str | None = None
    scans: list[TimelineScan] = Field(default_factory=list)
    events: list[TimelineEvent] = Field(default_factory=list)
    followup_days: float | None = None
