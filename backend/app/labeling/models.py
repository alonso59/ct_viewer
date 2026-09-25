"""Label tables and cell events (LBL-01..08; API-56..58)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TableLevel = Literal["case", "scan", "item"]
ColumnType = Literal["bool", "category", "number", "text", "date"]
SLUG_RE = r"^[a-z][a-z0-9_]{0,39}$"


class LabelColumn(BaseModel):
    """LBL-02: a rename keeps `column_id` and `slug` (the variable name); delete = hidden."""

    column_id: str
    slug: str = Field(pattern=SLUG_RE)
    name: str = Field(min_length=1, max_length=120)
    type: ColumnType
    levels: list[str] = Field(default_factory=list)  # category
    unit: str | None = None  # number
    min: float | None = None
    max: float | None = None
    description: str = ""
    default: Any = None
    hidden: bool = False
    # LBL-09: a read-only mirror of a `comparable` variable (VAR-13); no cell events of its own
    ref: str | None = None


class LabelTable(BaseModel):
    table_id: str
    slug: str = Field(pattern=SLUG_RE)
    name: str = Field(min_length=1, max_length=120)
    level: TableLevel
    columns: list[LabelColumn] = Field(default_factory=list)
    hidden: bool = False  # LBL-10: deleted; events and slug kept, restorable
    created_at: str
    updated_at: str


class TablesFile(BaseModel):
    """`{project}/plugins/labeling/tables.json` (the API process is the only writer)."""

    tables: list[LabelTable] = Field(default_factory=list)


class ColumnIn(BaseModel):
    """A new column (no `column_id`) or an edit of an existing one (with it)."""

    column_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    type: ColumnType | None = None  # required for a new column; fixed afterwards
    levels: list[str] | None = None
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    description: str | None = None
    default: Any = None
    hidden: bool | None = None
    ref: str | None = Field(
        default=None, description="LBL-09: mirror this comparable variable (new columns only)"
    )


class TableCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    level: TableLevel
    columns: list[ColumnIn] = Field(default_factory=list)


class TablePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    hidden: bool | None = None  # LBL-10: delete (true) or restore (false)
    columns: list[ColumnIn] | None = None  # upsert by column_id; others unchanged


class ColumnProgress(BaseModel):
    column_id: str
    filled: int


class TableInfo(LabelTable):
    """API-56 row with LBL-08 progress."""

    n_rows: int
    progress: list[ColumnProgress] = Field(default_factory=list)


class CellIn(BaseModel):
    column_id: str
    target: str
    value: Any = None  # null clears the cell


class CellsWrite(BaseModel):
    cells: list[CellIn] = Field(min_length=1, max_length=20000)


class CellEvent(BaseModel):
    """LBL-04: one line of `events/labeling.jsonl`."""

    event_id: str
    at: str
    reviewer: str
    session_id: str | None = None
    table_id: str
    column_id: str
    target: str
    value: Any = None


class CellRow(BaseModel):
    """API-57 row: a target of the table's level with its current values."""

    target: str
    case_id: str
    item_id: str | None = None  # the item to open in the viewer
    values: dict[str, Any] = Field(default_factory=dict)  # column_id → value
    updated: dict[str, str] = Field(default_factory=dict)  # column_id → reviewer of the value


class CellsPage(BaseModel):
    items: list[CellRow]
    next_cursor: str | None
    total: int


class CellsWritten(BaseModel):
    n_events: int
    events: list[CellEvent]


class ImportReport(BaseModel):
    """LBL-07 match report (as VAR-07)."""

    key: str
    n_rows: int
    matched: int
    unmatched: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)  # matched column names
    ignored_columns: list[str] = Field(default_factory=list)
    n_events: int = 0
    errors: list[str] = Field(default_factory=list)
