"""Label table files and the derived cell state, readable without the service (layers)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

from app.core.fsio import iter_jsonl, read_json
from app.eventstore.store import namespace_path
from app.labeling.models import LabelTable, TablesFile

NAMESPACE: Final = "labeling"
TABLES: Final = Path("plugins") / "labeling" / "tables.json"

CellKey = tuple[str, str, str]  # (table_id, column_id, target)


def load_tables(project_dir: Path) -> TablesFile:
    p = project_dir / TABLES
    return TablesFile.model_validate(read_json(p)) if p.is_file() else TablesFile()


def active_tables(project_dir: Path) -> list[LabelTable]:
    """Tables that are not deleted: the only ones that are layers and variables."""
    return [t for t in load_tables(project_dir).tables if not t.hidden]


def events(project_dir: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(namespace_path(project_dir, NAMESPACE)))


def kind_slug(level: str) -> str:
    """The name part of an event kind's variables: `Follow-up` → `follow_up`."""
    slug = re.sub(r"[^a-z0-9]+", "_", level.lower()).strip("_")
    return slug if slug[:1].isalpha() else f"k_{slug}"


def row_state(project_dir: Path) -> dict[str, list[tuple[str, str]]]:
    """Rows of the event tables, `table_id → [(target, case_id)]` in creation order; a removed
    row is left out and its number is not reused."""
    out: dict[str, dict[str, str]] = {}
    for e in events(project_dir):
        if e.get("kind") != "row":
            continue
        rows = out.setdefault(str(e.get("table_id")), {})
        if e.get("removed"):
            rows.pop(str(e.get("target")), None)
        else:
            rows[str(e.get("target"))] = str(e.get("case_id"))
    return {tid: list(rows.items()) for tid, rows in out.items()}


def row_count(project_dir: Path, table_id: str) -> int:
    """Row numbers handed out so far (removed rows included)."""
    return sum(
        1
        for e in events(project_dir)
        if e.get("kind") == "row" and e.get("table_id") == table_id and not e.get("removed")
    )


def cell_state(project_dir: Path) -> dict[CellKey, dict[str, Any]]:
    """Latest event per `(table, column, target)` in append order; a null value clears the
    cell, so it is left out."""
    out: dict[CellKey, dict[str, Any]] = {}
    for e in events(project_dir):
        if e.get("kind") == "row":
            continue
        k = (str(e.get("table_id")), str(e.get("column_id")), str(e.get("target")))
        if e.get("value") is None:
            out.pop(k, None)
        else:
            out[k] = e
    return out
