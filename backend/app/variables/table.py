"""`index/variables.parquet` (derived, rebuildable) and `var.{name}` filters (VAR-10, API.md).

One row per item: the base columns (`schema.BASE_COLUMNS`) plus every catalog variable,
case-level values joined onto all items of the case. Numeric types are float64, all
others strings.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.core.errors import ValidationProblem
from app.core.fsio import atomic_write_bytes
from app.variables.build import Built
from app.variables.models import NUMERIC_TYPES, Catalog, Variable
from app.variables.profile import as_date, as_number
from app.variables.schema import BASE_COLUMNS

VAR_PREFIX = "var."
RANGE_SEP = ".."


def to_arrow(built: Built) -> pa.Table:
    items = built.items
    data: dict[str, Any] = {
        "item_id": [i.item_id for i in items],
        "case_id": [i.case_id for i in items],
        "scan_idx": [i.scan_idx for i in items],
        "scope": [i.scope for i in items],
        "side": [i.side for i in items],
        "phase": [i.phase.canonical for i in items],
    }
    fields = [pa.field(c, pa.string()) for c in BASE_COLUMNS]
    for col in built.columns:
        numeric = col.var.type in NUMERIC_TYPES
        data[col.var.name] = [col.typed(i.case_id, i.scan_idx) for i in items]
        fields.append(pa.field(col.var.name, pa.float64() if numeric else pa.string()))
    return pa.Table.from_pydict(data, schema=pa.schema(fields))


def write_table(path: Path, table: pa.Table) -> None:
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    atomic_write_bytes(path, buf.getvalue())


def read_table(path: Path, columns: Sequence[str] | None = None) -> pa.Table | None:
    if not path.exists():
        return None
    return pq.read_table(path, columns=list(columns) if columns is not None else None)


# -- filters -----------------------------------------------------------------------------------

Filters = dict[str, list[str]]


def parse_var_params(params: Sequence[tuple[str, str]]) -> Filters:
    """`var.{name}=value` (repeatable: OR) or `var.{name}=min..max` (either end optional)."""
    out: Filters = {}
    for key, value in params:
        if key.startswith(VAR_PREFIX) and len(key) > len(VAR_PREFIX):
            out.setdefault(key[len(VAR_PREFIX) :], []).append(value)
    return out


def _bad(name: str, msg: str) -> ValidationProblem:
    return ValidationProblem(
        f"Invalid filter var.{name}: {msg}", errors=[{"loc": ["query", f"var.{name}"], "msg": msg}]
    )


def _predicate(var: Variable, values: Sequence[str]) -> Any:
    numeric = var.type in NUMERIC_TYPES
    ranges: list[tuple[Any, Any]] = []
    exact: set[Any] = set()
    for raw in values:
        if RANGE_SEP in raw and (numeric or var.type == "date"):
            lo_s, hi_s = raw.split(RANGE_SEP, 1)
            conv = as_number if numeric else as_date
            lo = conv(lo_s.strip()) if lo_s.strip() else None
            hi = conv(hi_s.strip()) if hi_s.strip() else None
            if (lo_s.strip() and lo is None) or (hi_s.strip() and hi is None):
                raise _bad(var.name, f"bad range {raw!r}")
            ranges.append((lo, hi))
        elif numeric:
            x = as_number(raw.strip())
            if x is None:
                raise _bad(var.name, f"{raw!r} is not a number")
            exact.add(x)
        else:
            exact.add(raw)

    def ok(v: Any) -> bool:
        if v is None:
            return False
        if v in exact:
            return True
        return any((lo is None or v >= lo) and (hi is None or v <= hi) for lo, hi in ranges)

    return ok


def matching_ids(
    catalog: Catalog, table: pa.Table | None, filters: Mapping[str, Sequence[str]]
) -> dict[str, set[str]]:
    """Items passing every filter → `{"items": {...}, "cases": {...}}` (AND across names)."""
    for name in filters:
        if catalog.get(name) is None:
            raise _bad(name, "unknown variable")
    if table is None:
        return {"items": set(), "cases": set()}
    rows = table.select(["item_id", "case_id", *filters]).to_pydict()
    preds = {n: _predicate(catalog.get(n), vals) for n, vals in filters.items()}  # type: ignore[arg-type]
    items: set[str] = set()
    cases: set[str] = set()
    for i, item_id in enumerate(rows["item_id"]):
        if all(p(rows[n][i]) for n, p in preds.items()):
            items.add(item_id)
            cases.add(rows["case_id"][i])
    return {"items": items, "cases": cases}
