"""Analysis tables: the long numeric tables the dashboard and analyses read.

An observation is `(item_id, label, instance)`; `instance` is empty unless the table has one row
per instance of a label (e.g. per lesion). Each value belongs to a named column of a group.
"""

from __future__ import annotations

import re
from typing import Final, Literal

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field

TABLE_SCHEMA: Final = pa.schema(
    [
        ("item_id", pa.string()),
        ("case_id", pa.string()),
        ("scan_idx", pa.string()),
        ("scope", pa.string()),
        ("side", pa.string()),
        ("phase", pa.string()),
        ("label", pa.int64()),
        ("instance", pa.string()),
        ("group", pa.string()),
        ("name", pa.string()),
        ("value", pa.float64()),
    ]
)
TABLE_ID_RE: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# No `-`: a task table's id is `{run_id}-{name}` and must split back unambiguously.
TABLE_NAME_RE: Final = re.compile(r"^[a-z0-9][a-z0-9_]{0,31}$")
VOLUME: Final = "volume"

Grain = Literal["label", "instance"]


class TableColumn(BaseModel):
    name: str
    group: str = ""
    unit: str = ""
    description: str = ""


class TableSpec(BaseModel):
    """What a task declares about a table it wrote."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    title: str = Field(min_length=1, max_length=200)
    grain: Grain = "label"
    instance_name: str | None = Field(default=None, max_length=64)
    columns: list[TableColumn] = Field(default_factory=list)
    roles: dict[Literal["volume"], str] = Field(default_factory=dict)


class TableProducer(BaseModel):
    task: str
    run_id: str


class TableCounts(BaseModel):
    items: int = 0
    columns: int = 0
    observations: int | None = None  # unknown for radiomics runs until read


class TableSummary(BaseModel):
    table_id: str
    kind: str  # `radiomics`, or the producing task's table kind
    title: str
    status: str  # the producer run's status
    created_at: str
    producer: TableProducer
    grain: Grain = "label"
    instance_name: str | None = None
    roles: dict[str, str] = Field(default_factory=dict)
    labels: list[int] = Field(default_factory=list)  # project label values in the table
    counts: TableCounts = Field(default_factory=TableCounts)


class TableManifest(TableSummary):
    """`table.json` of a task table; built from `run.json` for a radiomics run."""

    columns: list[TableColumn] = Field(default_factory=list)
