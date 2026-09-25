"""Labeling table service (LBL-01..08, ADR-0022 §3).

Tables and column schemas live in `plugins/labeling/tables.json`; every cell change is an event
in the core event store namespace `labeling` (LBL-04). Rows are the project's cases, scans or
items (active ones, IMP-07). Columns become metadata layers and `lbl.{table}.{column}`
variables (LBL-06); the variable catalog is rebuilt shortly after writes.
"""

from __future__ import annotations

import builtins
import csv
import io
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any, Final

import pyarrow as pa
import pyarrow.parquet as pq

from app.core.errors import NotFound, ValidationProblem
from app.core.fsio import atomic_write_json
from app.core.ids import new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.events.bus import EventBus
from app.eventstore.store import EventStore, require_reviewer, stamp
from app.ingest.models import Item
from app.ingest.store import IndexStore
from app.labeling import state
from app.labeling.models import (
    CellEvent,
    CellIn,
    CellRow,
    CellsPage,
    CellsWritten,
    ColumnIn,
    ColumnProgress,
    ImportReport,
    LabelColumn,
    LabelTable,
    TableCreate,
    TableInfo,
    TablePatch,
    TablesFile,
)
from app.projects.service import Workspace
from app.variables.models import Catalog
from app.variables.service import VariableService

TEXT_MAX: Final = 2000
TRUE: Final = {"true", "yes", "y", "1", "si", "sí", "x"}
FALSE: Final = {"false", "no", "n", "0"}
IMPORT_KEYS: Final = ("case_id", "patient_id", "scan", "item_id", "target")


def slugify(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:36] or "col"
    if not base[0].isalpha():
        base = f"c_{base}"[:36]
    slug, n = base, 1
    while slug in taken:
        n += 1
        slug = f"{base}_{n}"
    return slug


def coerce(col: LabelColumn, raw: Any) -> Any:
    """A typed cell value (LBL-02), or ValueError with a reason. None / "" clear the cell."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if col.type == "bool":
        if isinstance(raw, bool):
            return raw
        t = str(raw).strip().lower()
        if t in TRUE:
            return True
        if t in FALSE:
            return False
        raise ValueError("expected yes/no")
    if col.type == "category":
        t = str(raw).strip()
        if col.levels and t not in col.levels:
            match = next((lv for lv in col.levels if lv.lower() == t.lower()), None)
            if match is None:
                raise ValueError(f"expected one of {col.levels}")
            t = match
        return t
    if col.type == "number":
        try:
            x = (
                float(str(raw).strip().replace(",", "."))
                if not isinstance(raw, (int, float))
                else float(raw)
            )
        except ValueError:
            raise ValueError("expected a number") from None
        if (col.min is not None and x < col.min) or (col.max is not None and x > col.max):
            raise ValueError(f"outside [{col.min}, {col.max}]")
        return int(x) if x.is_integer() else x
    if col.type == "date":
        try:
            return date.fromisoformat(str(raw).strip()[:10]).isoformat()
        except ValueError:
            raise ValueError("expected a date YYYY-MM-DD") from None
    t = str(raw)
    if len(t) > TEXT_MAX:
        raise ValueError(f"at most {TEXT_MAX} characters")
    return t


def targets(table: LabelTable, items: Sequence[Item]) -> list[tuple[str, str, str | None]]:
    """(target, case_id, item to open) for the table's level (LBL-01), in index order."""
    live = [i for i in items if i.status != "excluded_upstream"]
    out: dict[str, tuple[str, str, str | None]] = {}
    for i in live:
        if table.level == "case":
            key = i.case_id
        elif table.level == "scan":
            key = f"{i.case_id}.{i.scan_idx}"
        else:
            key = i.item_id
        cur = out.get(key)
        # prefer the complete-scope item to open in the viewer
        better = i.scope == "complete" and not ((cur and cur[2]) or "").endswith(".complete.-")
        if cur is None or (table.level != "item" and better):
            out[key] = (key, i.case_id, i.item_id)
    return list(out.values())


class LabelingService:
    def __init__(
        self, workspace: Workspace, store: IndexStore, locks: ProjectLocks, bus: EventBus
    ) -> None:
        self.workspace = workspace
        self.store = store
        self.locks = locks
        self.bus = bus
        self.events = EventStore(workspace, locks, bus)

    def _pdir(self, pid: str) -> Path:
        return self.workspace.project_dir(pid)

    def _save(self, pid: str, doc: TablesFile) -> None:
        atomic_write_json(self._pdir(pid) / state.TABLES, doc.model_dump(mode="json"))

    def table(self, pid: str, tid: str) -> LabelTable:
        """A table that is not deleted; a deleted one is 404 until restored (LBL-10)."""
        t = next((x for x in state.active_tables(self._pdir(pid)) if x.table_id == tid), None)
        if t is None:
            raise NotFound(f"Label table {tid!r} not found")
        return t

    # -- schemas (API-56, LBL-01/02) ------------------------------------------------------------

    def _column(
        self, t: LabelTable, c: ColumnIn, taken: set[str], catalog: Catalog | None = None
    ) -> LabelColumn:
        if c.ref is not None:
            return self._ref_column(t, c, taken, catalog)
        if c.type is None:
            raise ValidationProblem(
                f"Column {c.name!r} needs a type",
                errors=[{"loc": ["body", "columns", "type"], "msg": "required"}],
            )
        col = LabelColumn(
            column_id=new_ulid(), slug=slugify(c.name, taken), name=c.name.strip(), type=c.type,
            levels=[lv.strip() for lv in c.levels or [] if lv.strip()], unit=c.unit,
            min=c.min, max=c.max, description=c.description or "", hidden=bool(c.hidden),
        )  # fmt: skip
        if col.type == "category" and not col.levels:
            raise ValidationProblem(
                f"Category column {c.name!r} needs levels",
                errors=[{"loc": ["body", "columns", "levels"], "msg": "at least one level"}],
            )
        taken.add(col.slug)
        return col.model_copy(update={"default": self._default(col, c.default)})

    def _ref_column(
        self, t: LabelTable, c: ColumnIn, taken: set[str], catalog: Catalog | None
    ) -> LabelColumn:
        """LBL-09: the variable must be `comparable` (VAR-13) and at a level the table can show:
        a patient table mirrors case-level variables only."""
        var = next((v for v in (catalog.variables if catalog else []) if v.name == c.ref), None)
        why = (
            "unknown variable" if var is None
            else "not comparable (VAR-13)" if not var.comparable
            else "a scan-level variable cannot be shown per patient"
            if t.level == "case" and var.level != "case" else None
        )  # fmt: skip
        if why:
            raise ValidationProblem(
                f"Reference column {c.name!r}: {why}",
                errors=[{"loc": ["body", "columns", "ref"], "msg": why}],
            )
        col = LabelColumn(
            column_id=new_ulid(), slug=slugify(c.name, taken), name=c.name.strip(),
            type="category", description=c.description or "", hidden=bool(c.hidden), ref=c.ref,
        )  # fmt: skip
        taken.add(col.slug)
        return col

    async def _catalog(self, pid: str, columns: Sequence[ColumnIn] | None) -> Catalog | None:
        """The variable catalog, only when a new reference column needs it."""
        if not any(c.ref is not None and c.column_id is None for c in columns or []):
            return None
        return await VariableService(self.workspace, self.store, self.locks, self.bus).catalog(pid)

    async def ref_values(self, pid: str, tid: str) -> dict[str, dict[str, Any]]:
        """LBL-09: current values of the table's reference columns, `column_id → target → value`,
        read from the variables table (VAR-12), so they follow their source live."""
        t = self.table(pid, tid)
        refs = [c for c in t.columns if c.ref and not c.hidden]
        if not refs:
            return {}
        vs = VariableService(self.workspace, self.store, self.locks, self.bus)
        table = await vs.table(pid)
        out: dict[str, dict[str, Any]] = {c.column_id: {} for c in refs}
        if table is None:
            return out
        names = [n for n in {str(c.ref) for c in refs} if n in table.column_names]
        for row in table.select(["item_id", "case_id", "scan_idx", *names]).to_pylist():
            key = {"case": row["case_id"], "scan": f"{row['case_id']}.{row['scan_idx']}"}.get(
                t.level, row["item_id"]
            )
            for c in refs:
                v = row.get(str(c.ref))
                if v is not None:
                    out[c.column_id].setdefault(key, v)
        return out

    @staticmethod
    def _default(col: LabelColumn, raw: Any) -> Any:
        try:
            return coerce(col, raw)
        except ValueError as exc:
            raise ValidationProblem(f"Default of {col.name!r}: {exc}") from None

    def tables(self, pid: str, deleted: bool = False) -> builtins.list[TableInfo]:
        """LBL-08: progress = filled cells per column over the table's rows. `deleted` lists
        only the deleted tables instead (LBL-10)."""
        pdir = self._pdir(pid)
        items = self.store.load(pid).items
        cells = state.cell_state(pdir)
        out: list[TableInfo] = []
        for t in state.load_tables(pdir).tables:
            if t.hidden != deleted:
                continue
            rows = {r[0] for r in targets(t, items)}
            prog = [
                ColumnProgress(
                    column_id=c.column_id,
                    filled=sum(
                        1
                        for (tid, cid, tg) in cells
                        if tid == t.table_id and cid == c.column_id and tg in rows
                    ),
                )
                for c in t.columns
                if not c.hidden and not c.ref
            ]
            out.append(TableInfo(**t.model_dump(), n_rows=len(rows), progress=prog))
        return out

    async def create(self, pid: str, body: TableCreate) -> LabelTable:
        catalog = await self._catalog(pid, body.columns)
        async with self.locks(pid):
            doc = state.load_tables(self._pdir(pid))
            now = utc_now()
            t = LabelTable(
                table_id=new_ulid(), slug=slugify(body.name, {x.slug for x in doc.tables}),
                name=body.name.strip(), level=body.level, created_at=now, updated_at=now,
            )  # fmt: skip
            taken: set[str] = set()
            t.columns = [self._column(t, c, taken, catalog) for c in body.columns]
            doc.tables.append(t)
            self._save(pid, doc)
        self.bus.publish(pid, "project.updated", {"fields": ["labeling"]})
        return t

    async def patch(self, pid: str, tid: str, body: TablePatch) -> LabelTable:
        """A rename keeps ids and slugs; `hidden: true` hides a column, or the table (LBL-10), and
        keeps its events; `hidden: false` restores it."""
        catalog = await self._catalog(pid, body.columns)
        async with self.locks(pid):
            doc = state.load_tables(self._pdir(pid))
            t = next((x for x in doc.tables if x.table_id == tid), None)
            if t is None:
                raise NotFound(f"Label table {tid!r} not found")
            if body.name is not None:
                t.name = body.name.strip()
            if body.hidden is not None:
                t.hidden = body.hidden
            taken = {c.slug for c in t.columns}
            for c in body.columns or []:
                cur = next((x for x in t.columns if x.column_id == c.column_id), None)
                if cur is None:
                    if c.column_id is not None:
                        raise NotFound(f"Column {c.column_id!r} not found")
                    t.columns.append(self._column(t, c, taken, catalog))
                    continue
                retyped = c.type is not None and c.type != cur.type
                if retyped or (c.ref is not None and c.ref != cur.ref):
                    raise ValidationProblem(
                        "A column's type or reference cannot change; add a new column"
                    )
                upd: dict[str, Any] = {"name": c.name.strip()}
                for k in ("levels", "hidden"):
                    v = getattr(c, k)
                    if v is not None:
                        upd[k] = v
                # an explicit null clears these (an edit form sends what the user emptied)
                for k in ("unit", "min", "max", "description"):
                    if k in c.model_fields_set:
                        v = getattr(c, k)
                        upd[k] = (v or "") if k == "description" else v
                new = cur.model_copy(update=upd)
                if c.default is not None:
                    new.default = self._default(new, c.default)
                t.columns[t.columns.index(cur)] = new
            t.updated_at = utc_now()
            self._save(pid, doc)
        self.bus.publish(pid, "project.updated", {"fields": ["labeling"]})
        return t

    # -- cells (API-57, LBL-03..05) -------------------------------------------------------------

    def cells(
        self, pid: str, tid: str, cursor: int, limit: int, q: str | None,
        refs: dict[str, dict[str, Any]] | None = None,
    ) -> CellsPage:  # fmt: skip
        """`refs`: reference-column values from `ref_values` (LBL-09)."""
        t = self.table(pid, tid)
        rows = targets(t, self.store.load(pid).items)
        if q:
            rows = [r for r in rows if q.lower() in r[0].lower()]
        cells = state.cell_state(self._pdir(pid))
        cols = [c for c in t.columns if not c.hidden]
        page = rows[cursor : cursor + limit]
        out: list[CellRow] = []
        for target, case_id, item_id in page:
            row = CellRow(target=target, case_id=case_id, item_id=item_id)
            for c in cols:
                if c.ref:
                    v = (refs or {}).get(c.column_id, {}).get(target)
                    if v is not None:
                        row.values[c.column_id] = v
                    continue
                e = cells.get((t.table_id, c.column_id, target))
                if e is not None:
                    row.values[c.column_id] = e.get("value")
                    row.updated[c.column_id] = str(e.get("reviewer") or "")
                elif c.default is not None:
                    row.values[c.column_id] = c.default
            out.append(row)
        nxt = cursor + limit
        return CellsPage(items=out, next_cursor=str(nxt) if nxt < len(rows) else None,
                         total=len(rows))  # fmt: skip

    async def write(
        self, pid: str, tid: str, cells: Sequence[CellIn], reviewer: str | None,
        session_id: str | None,
    ) -> CellsWritten:  # fmt: skip
        """LBL-04: validate every cell first (all or nothing), then append one event each."""
        who = require_reviewer(reviewer)
        t = self.table(pid, tid)
        by_id = {c.column_id: c for c in t.columns}
        valid = {r[0] for r in targets(t, self.store.load(pid).items)}
        errors: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        for n, cell in enumerate(cells):
            col = by_id.get(cell.column_id)
            if col is None or col.hidden:
                errors.append({"loc": ["body", "cells", n, "column_id"], "msg": "unknown column"})
                continue
            if col.ref:
                errors.append({"loc": ["body", "cells", n, "column_id"],
                               "msg": f"read-only reference to {col.ref}"})  # fmt: skip
                continue
            if cell.target not in valid:
                errors.append({"loc": ["body", "cells", n, "target"], "msg": "not a row"})
                continue
            try:
                value = coerce(col, cell.value)
            except ValueError as exc:
                errors.append({"loc": ["body", "cells", n, "value"], "msg": str(exc)})
                continue
            body = {"table_id": tid, "column_id": col.column_id, "target": cell.target,
                    "value": value}  # fmt: skip
            records.append(stamp(who, session_id, body))
        if errors:
            raise ValidationProblem(f"{len(errors)} invalid cell(s)", errors=errors[:50])
        await self.events.append(pid, state.NAMESPACE, records)
        return CellsWritten(n_events=len(records), events=[CellEvent(**r) for r in records[:200]])

    def history(
        self, pid: str, tid: str, target: str | None, column_id: str | None
    ) -> list[CellEvent]:
        self.table(pid, tid)
        out = [
            CellEvent(**e)
            for e in state.events(self._pdir(pid))
            if e.get("table_id") == tid
            and (target is None or e.get("target") == target)
            and (column_id is None or e.get("column_id") == column_id)
        ]
        return out[::-1][:500]

    # -- import / export (API-58, LBL-07) -------------------------------------------------------

    async def import_csv(
        self, pid: str, tid: str, raw: bytes, reviewer: str | None, session_id: str | None
    ) -> ImportReport:
        who = require_reviewer(reviewer)
        t = self.table(pid, tid)
        text = raw.decode("utf-8-sig", errors="replace")
        dialect = csv.excel_tab if text.count("\t") > text.count(",") else csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        header = [h.strip() for h in reader.fieldnames or []]
        key = next((k for k in IMPORT_KEYS if k in header), None)
        if key is None:
            raise ValidationProblem(
                f"No key column: expected one of {list(IMPORT_KEYS)}",
                errors=[{"loc": ["body", "file"], "msg": "no key column"}],
            )
        items = self.store.load(pid).items
        rows = targets(t, items)
        index: dict[str, list[str]] = {}
        for target, _case, _ in rows:
            if key in ("case_id", "target", "scan", "item_id"):
                index.setdefault(target, []).append(target)
        if key == "patient_id":
            by_case = {i.case_id: i.patient_id for i in items if i.patient_id}
            for target, case_id, _ in rows:
                pat = by_case.get(case_id)
                if pat:
                    index.setdefault(pat, []).append(target)
        if key == "case_id" and t.level != "case":
            index = {}
            for target, case_id, _ in rows:
                index.setdefault(case_id, []).append(target)
        own = [c for c in t.columns if not c.hidden and not c.ref]  # LBL-09 refs are read-only
        cols = {c.name.lower(): c for c in own}
        cols.update({c.slug: c for c in own})
        matched_cols = [h for h in header if h != key and (h.lower() in cols or h in cols)]
        ignored = [h for h in header if h != key and h not in matched_cols]
        report = ImportReport(key=key, n_rows=0, matched=0, columns=matched_cols,
                              ignored_columns=ignored)  # fmt: skip
        records: list[dict[str, Any]] = []
        for line in reader:
            report.n_rows += 1
            k = (line.get(key) or "").strip()
            tgts = index.get(k)
            if not tgts:
                report.unmatched.append(k)
                continue
            report.matched += 1
            for h in matched_cols:
                col = cols.get(h.lower()) or cols[h]
                v = line.get(h)
                if v is None or not v.strip():
                    continue
                try:
                    value = coerce(col, v)
                except ValueError as exc:
                    report.errors.append(f"{k} · {h}: {exc}")
                    continue
                for tg in tgts:
                    records.append(stamp(who, session_id, {"table_id": tid, "column_id":
                                   col.column_id, "target": tg, "value": value}))  # fmt: skip
        report.unmatched = report.unmatched[:200]
        report.errors = report.errors[:200]
        if records:
            await self.events.append(pid, state.NAMESPACE, records)
        report.n_events = len(records)
        return report

    def export(
        self, pid: str, tid: str, fmt: str, refs: dict[str, dict[str, Any]] | None = None
    ) -> bytes:
        t = self.table(pid, tid)
        cols = [c for c in t.columns if not c.hidden]
        header = ["target", "case_id", *(c.name for c in cols)]
        page = self.cells(pid, tid, 0, 10**9, None, refs)
        data = [
            [r.target, r.case_id, *(r.values.get(c.column_id) for c in cols)] for r in page.items
        ]
        if fmt == "parquet":
            arrays = {h: pa.array([None if row[i] is None else str(row[i]) for row in data],
                                  type=pa.string()) for i, h in enumerate(header)}  # fmt: skip
            buf = io.BytesIO()
            pq.write_table(pa.table(arrays), buf)
            return buf.getvalue()
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(header)
        w.writerows(["" if v is None else v for v in row] for row in data)
        return out.getvalue().encode("utf-8")
