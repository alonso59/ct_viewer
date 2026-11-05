"""Cohort read service: case → scan rows and column summaries over the variable table.

Reads only the derived variable state (catalog + `index/variables.parquet`). The scan
unit is the scan's `complete` item; a case row carries a column's value when all its
scans agree, else `None` with the column listed in `differs`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Literal, cast

import numpy as np
import pyarrow as pa

from app.analytics import analysis as an
from app.analytics import stats as st
from app.analytics.data import GROUP_TYPES
from app.cohort.models import (
    CaseRow,
    CohortBalanceCell,
    CohortBalanceRequest,
    CohortBalanceResponse,
    RowsRequest,
    RowsResponse,
    ScanRow,
    SummaryBin,
    SummaryRequest,
    SummaryResponse,
    Timeline,
    TimelineEvent,
    TimelineScan,
)
from app.core.errors import NotFound, ValidationProblem
from app.ingest.models import CaseSummary, Item
from app.ingest.store import IndexStore
from app.labeling import state as labeling_state
from app.variables import table as tbl
from app.variables.models import NUMERIC_TYPES, Catalog
from app.variables.profile import as_date
from app.variables.service import VariableService

# Always projected: the join keys, the scan unit and the scan's phase.
BASE = ("item_id", "case_id", "scan_idx", "scope", "phase")
BIN_COUNT = 20
TOP_VALUES = 20


def _unknown(name: str, loc: str) -> ValidationProblem:
    return ValidationProblem(
        f"Unknown variable {name!r}", errors=[{"loc": [loc, name], "msg": "unknown variable"}]
    )


def _validate(cat: Catalog, names: Sequence[str], loc: str) -> None:
    for name in names:
        if cat.get(name) is None:
            raise _unknown(name, loc)


class CohortService:
    def __init__(self, variables: VariableService, store: IndexStore) -> None:
        self.variables = variables
        self.store = store

    @staticmethod
    def _visible(items: Sequence[Item]) -> set[str]:
        """Cases with an item not excluded upstream, as the cases endpoint shows by default."""
        st: dict[str, set[str]] = {}
        for it in items:
            st.setdefault(it.case_id, set()).add(it.status)
        return {cid for cid, s in st.items() if s - {"excluded_upstream"}}

    def _check_phase(self, project_id: str, phase: str | None) -> None:
        if phase is None:
            return
        vocab = self.variables.workspace.get(project_id).phase_vocabulary
        if vocab and phase not in vocab:
            raise ValidationProblem(
                f"Unknown phase {phase!r}",
                errors=[{"loc": ["body", "phase"], "msg": f"allowed: {vocab}"}],
            )

    async def rows(self, project_id: str, req: RowsRequest) -> RowsResponse:
        """Case → scan rows over the requested columns, filtered, sorted and paged by case."""
        cat = await self.variables.catalog(project_id)
        _validate(cat, req.columns, "body.columns")
        _validate(cat, list(req.filters), "body.filters")
        if (
            req.sort is not None
            and req.sort.column != "case_id"
            and req.sort.column not in req.columns
        ):
            raise ValidationProblem(
                f"Sort column {req.sort.column!r} is not a requested column",
                errors=[{"loc": ["body", "sort", "column"], "msg": "not in columns"}],
            )
        self._check_phase(project_id, req.phase)
        cols = list(dict.fromkeys([*req.columns, *req.filters]))
        table = await self.variables.table(project_id, [*BASE, *cols])
        if table is None:
            return RowsResponse(n_cases=0, n_scans=0)
        idx = self.store.load(project_id)
        return build_rows(
            cat,
            table,
            idx.cases,
            {i.item_id: i.modality for i in idx.items},
            self._visible(idx.items),
            req,
        )

    async def summary(self, project_id: str, req: SummaryRequest) -> SummaryResponse:
        """The column's values over the filtered rows, at the variable's level."""
        cat = await self.variables.catalog(project_id)
        _validate(cat, [req.column], "body.column")
        _validate(cat, list(req.filters), "body.filters")
        cols = list(dict.fromkeys([req.column, *req.filters]))
        table = await self.variables.table(project_id, [*BASE, *cols])
        if table is None:
            return SummaryResponse()
        return build_summary(cat, table, self._visible(self.store.load(project_id).items), req)

    async def timeline(self, project_id: str, case_id: str) -> Timeline:
        """The case's scans and events as days from its earliest dated scan (the anchor)."""
        idx = self.store.load(project_id)
        if not any(i.case_id == case_id and i.status != "excluded_upstream" for i in idx.items):
            raise NotFound(f"Case {case_id!r} not found")
        cat = await self.variables.catalog(project_id)
        date_col = next((n for n in ("study_date", "scan_date") if cat.get(n) is not None), None)
        table = await self.variables.table(project_id, [*BASE, *([date_col] if date_col else [])])
        scans: list[tuple[str, str, str, int | None]] = []
        if table is not None:
            d = table.to_pydict()
            for i, scope in enumerate(d["scope"]):
                if scope != "complete" or d["case_id"][i] != case_id:
                    continue
                text = as_date(d[date_col][i]) if date_col and d[date_col][i] else None
                ordinal = date.fromisoformat(text[:10]).toordinal() if text else None
                scans.append((d["scan_idx"][i], d["item_id"][i], d["phase"][i], ordinal))
        dated = [o for *_, o in scans if o is not None]
        anchor = min(dated) if dated else None
        first = next((s for s in sorted(scans, key=lambda s: s[0]) if s[3] == anchor), None)
        out = Timeline(
            case_id=case_id,
            anchor_scan=first[0] if first and anchor is not None else None,
            scans=[
                TimelineScan(
                    scan_idx=s,
                    item_id=item,
                    phase=phase,
                    day=None if o is None or anchor is None else o - anchor,
                )
                for s, item, phase, o in sorted(scans)
            ],
        )
        out.events = self._events(project_id, case_id)
        known = [e.day for e in out.events if e.day is not None]
        out.followup_days = max(known) if known else None
        return out

    def _events(self, project_id: str, case_id: str) -> list[TimelineEvent]:
        pdir = self.variables.workspace.project_dir(project_id)
        rows = labeling_state.row_state(pdir)
        cells = labeling_state.cell_state(pdir)
        out: list[TimelineEvent] = []
        for t in labeling_state.active_tables(pdir):
            if t.level != "event":
                continue
            cols = {c.slug: c for c in t.columns if not c.hidden and not c.ref}
            for target, cid in rows.get(t.table_id, []):
                if cid != case_id:
                    continue
                got = {
                    slug: cells.get((t.table_id, c.column_id, target), {}).get("value")
                    for slug, c in cols.items()
                }
                day = got.get("day")
                out.append(
                    TimelineEvent(
                        table_id=t.table_id,
                        table=t.name,
                        target=target,
                        kind=got.get("kind"),
                        day=float(day) if day is not None else None,
                        values={
                            cols[s].name: v for s, v in got.items() if s not in ("kind", "day")
                        },
                    )
                )
        return sorted(out, key=lambda e: (e.day is None, e.day or 0.0, e.target))

    async def balance(self, project_id: str, req: CohortBalanceRequest) -> CohortBalanceResponse:
        """One categorical variable by another over the filtered rows, with χ² or Fisher exact."""
        cat = await self.variables.catalog(project_id)
        _validate(cat, [req.a, req.b], "body")
        _validate(cat, list(req.filters), "body.filters")
        if req.a == req.b:
            raise ValidationProblem(
                "Balance check needs two different variables",
                errors=[{"loc": ["body", "b"], "msg": "same as a"}],
            )
        for name in (req.a, req.b):
            var = cat.get(name)
            if var is not None and var.type not in GROUP_TYPES:
                raise ValidationProblem(
                    f"{name!r} is {var.type}; the balance check needs a categorical variable",
                    errors=[{"loc": ["body", name], "msg": f"{var.type} is not categorical"}],
                )
        cols = list(dict.fromkeys([req.a, req.b, *req.filters]))
        table = await self.variables.table(project_id, [*BASE, *cols])
        if table is None:
            return CohortBalanceResponse(unit="case")
        return build_balance(cat, table, self._visible(self.store.load(project_id).items), req)


def build_rows(
    cat: Catalog,
    table: pa.Table,
    cases: Sequence[CaseSummary],
    modality: Mapping[str, str | None],
    visible: set[str],
    req: RowsRequest,
) -> RowsResponse:
    cols = list(req.columns)
    kept = tbl.matching_ids(cat, table, req.filters)["cases"] if req.filters else None
    needle = (req.q or "").strip().lower()
    case_ids = [
        c.case_id
        for c in cases
        if c.case_id in visible
        and (kept is None or c.case_id in kept)
        and (not needle or needle in f"{c.case_id}\n{c.patient_id or ''}".lower())
        and (req.phase is None or req.phase in c.phases)
    ]
    if not case_ids:
        return RowsResponse(n_cases=0, n_scans=0)
    d = table.to_pydict()
    want = set(case_ids)
    complete: dict[str, list[int]] = {}
    for i, scope in enumerate(d["scope"]):
        if scope == "complete" and d["case_id"][i] in want:
            complete.setdefault(d["case_id"][i], []).append(i)
    out: list[CaseRow] = []
    for cid in sorted(case_ids):
        idxs = sorted(complete.get(cid, []), key=lambda i: d["scan_idx"][i])
        if not idxs:  # no complete item: nothing to show for the case
            continue
        scans = [
            ScanRow(
                scan_idx=d["scan_idx"][i],
                item_id=d["item_id"][i],
                phase=d["phase"][i],
                modality=modality.get(d["item_id"][i]),
                values={c: d[c][i] for c in cols},
            )
            for i in idxs
        ]
        values: dict[str, float | str | None] = {}
        differs: list[str] = []
        for c in cols:
            first = scans[0].values[c]
            if all(s.values[c] == first for s in scans):
                values[c] = first
            else:
                values[c] = None
                differs.append(c)
        out.append(CaseRow(case_id=cid, values=values, differs=differs, scans=scans))
    if req.sort is not None:
        _sort_by(out, req.sort.column, req.sort.desc)
    return RowsResponse(
        n_cases=len(out),
        n_scans=sum(len(r.scans) for r in out),
        rows=out[req.offset : req.offset + req.limit],
    )


def _sort_by(rows: list[CaseRow], column: str, desc: bool) -> None:
    if column == "case_id":
        rows.sort(key=lambda r: r.case_id, reverse=desc)
        return
    present = [r for r in rows if r.values.get(column) is not None]
    missing = [r for r in rows if r.values.get(column) is None]
    present.sort(key=lambda r: r.case_id)
    # one parquet type per column, so the values compare; stable: ties keep case order
    present.sort(key=lambda r: cast(Any, r.values[column]), reverse=desc)
    missing.sort(key=lambda r: r.case_id)
    rows[:] = [*present, *missing]


def build_summary(
    cat: Catalog, table: pa.Table, visible: set[str], req: SummaryRequest
) -> SummaryResponse:
    var = cat.get(req.column)
    if var is None:  # the service validates; this keeps the type narrowing honest
        raise _unknown(req.column, "body.column")
    kept = tbl.matching_ids(cat, table, req.filters)["cases"] if req.filters else None
    d = table.to_pydict()
    first_by_case: dict[str, int] = {}
    complete_by_case: dict[str, list[int]] = {}
    for i, scope in enumerate(d["scope"]):
        cid = d["case_id"][i]
        if cid not in visible or (kept is not None and cid not in kept):
            continue
        first_by_case.setdefault(cid, i)
        if scope == "complete":
            complete_by_case.setdefault(cid, []).append(i)
    name = req.column
    if var.level == "case":
        values: list[float | str | None] = [d[name][first_by_case[cid]] for cid in complete_by_case]
    else:
        values = [d[name][i] for idxs in complete_by_case.values() for i in idxs]
    missing = sum(1 for v in values if v is None)
    present = [v for v in values if v is not None]
    if var.type in NUMERIC_TYPES or var.type == "date":
        return SummaryResponse(bins=_bins(var.type, present), missing=missing)
    counts: dict[str, int] = {}
    for v in present:
        key = str(v)
        counts[key] = counts.get(key, 0) + 1
    top = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_VALUES])
    return SummaryResponse(
        counts=top, other=sum(counts.values()) - sum(top.values()), missing=missing
    )


def _bins(var_type: str, values: Sequence[float | str]) -> list[SummaryBin]:
    if var_type == "date":
        xs = [
            float(date.fromisoformat(d[:10]).toordinal())
            for v in values
            if (d := as_date(str(v))) is not None
        ]

        def edge(x: float) -> str:
            return date.fromordinal(round(x)).isoformat()
    else:
        xs = [float(v) for v in values]

        def edge(x: float) -> str:
            return f"{x:.6g}"

    if not xs:
        return []
    lo, hi = min(xs), max(xs)
    if hi == lo:
        return [SummaryBin(lo=edge(lo), hi=edge(hi), count=len(xs))]
    width = (hi - lo) / BIN_COUNT
    buckets = [0] * BIN_COUNT
    for x in xs:
        buckets[min(int((x - lo) // width), BIN_COUNT - 1)] += 1
    return [
        SummaryBin(lo=edge(lo + i * width), hi=edge(lo + (i + 1) * width), count=buckets[i])
        for i in range(BIN_COUNT)
    ]


def build_balance(
    cat: Catalog, table: pa.Table, visible: set[str], req: CohortBalanceRequest
) -> CohortBalanceResponse:
    """One unit per case when both variables are case-level, else one per complete scan."""
    kept = tbl.matching_ids(cat, table, req.filters)["cases"] if req.filters else None
    levels = {v.name: v.level for v in (cat.get(req.a), cat.get(req.b)) if v is not None}
    unit: Literal["case", "scan"] = "case" if set(levels.values()) == {"case"} else "scan"
    d = table.to_pydict()
    seen: set[str] = set()
    a: list[Any] = []
    b: list[Any] = []
    for i, scope in enumerate(d["scope"]):
        cid = d["case_id"][i]
        if scope != "complete" or cid not in visible or (kept is not None and cid not in kept):
            continue
        if unit == "case":
            if cid in seen:
                continue
            seen.add(cid)
        a.append(d[req.a][i])
        b.append(d[req.b][i])
    row_levels = np.asarray([None if v is None else str(v) for v in a], dtype=object)
    col_levels = np.asarray([None if v is None else str(v) for v in b], dtype=object)
    rows, cols, ex_r, ex_c, counts, out = an.contingency(row_levels, col_levels, req.test)
    missing = sum(1 for x, y in zip(a, b, strict=True) if x is None or y is None)
    with st.quiet():
        expected = (
            np.outer(counts.sum(1), counts.sum(0)) / counts.sum()
            if counts.size and counts.sum()
            else counts
        )
    cells = [
        CohortBalanceCell(row=r, col=c, n=int(counts[i, j]), expected=st.num(expected[i, j]))
        for i, r in enumerate(rows)
        for j, c in enumerate(cols)
    ]
    return CohortBalanceResponse(
        unit=unit,
        rows=rows,
        cols=cols,
        cells=cells,
        excluded_rows=ex_r,
        excluded_cols=ex_c,
        test=out.test if out.test in ("chi2", "fisher") else None,
        reason=out.reason,
        statistic=st.num(out.statistic),
        p=st.num(out.p),
        cramers_v=st.num(out.effect),
        n=out.n,
        missing=missing,
    )
