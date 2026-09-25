"""Label table files and the derived cell state (LBL-04), readable without the service (layers)."""

from __future__ import annotations

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
    """Tables that are not deleted (LBL-10): the only ones that are layers and variables."""
    return [t for t in load_tables(project_dir).tables if not t.hidden]


def events(project_dir: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(namespace_path(project_dir, NAMESPACE)))


def cell_state(project_dir: Path) -> dict[CellKey, dict[str, Any]]:
    """Latest event per `(table, column, target)` in append order (LBL-04/05); a null value
    clears the cell, so it is left out."""
    out: dict[CellKey, dict[str, Any]] = {}
    for e in events(project_dir):
        k = (str(e.get("table_id")), str(e.get("column_id")), str(e.get("target")))
        if e.get("value") is None:
            out.pop(k, None)
        else:
            out[k] = e
    return out
