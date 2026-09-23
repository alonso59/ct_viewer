"""Analytics services: dashboard views (API-38) and saved analyses (API-39).

Stateless like the other services (routers build one per request). Inputs are read before
any lock is taken (the variable service may rebuild its catalog under the same lock); CPU
work runs in a thread. Analyses are written under the project lock with atomic writes
(BE-05): `analyses/{analysis_id}/spec.json, results.parquet, descriptives.parquet,
recommendations.json, exports/{tidy.csv, results.csv, descriptives.csv, spec.json}`.
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel

from app.analytics import analysis as an
from app.analytics import data as dt
from app.analytics import views as vw
from app.analytics.models import (
    Analysis,
    AnalysisList,
    AnalysisSpec,
    AnalysisSummary,
    Contingency,
    DescriptiveRow,
    GlobalFilters,
    GroupInfo,
    Recommendation,
    ResultRow,
    RunOverviewRequest,
    RunOverviewResponse,
    TestChoice,
    UnitSummary,
    ViewRequest,
)
from app.analytics.recommend import recommend
from app.core.errors import NotFound
from app.core.fsio import atomic_write_bytes, atomic_write_json, read_json
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.events.bus import EventBus
from app.ingest.store import IndexStore
from app.projects.service import Workspace
from app.variables.service import VariableService

ANALYSES = Path("analyses")
SPEC = "spec.json"
RESULTS = "results.parquet"
DESCRIPTIVES = "descriptives.parquet"
RECOMMENDATIONS = "recommendations.json"
EXPORTS = "exports"
ExportFile = Literal["tidy", "results", "descriptives", "spec"]
EXPORT_NAMES: dict[str, tuple[str, str]] = {
    "tidy": ("tidy.csv", "text/csv"),
    "results": ("results.csv", "text/csv"),
    "descriptives": ("descriptives.csv", "text/csv"),
    "spec": ("spec.json", "application/json"),
}
SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass
class Inputs:
    project_dir: Path
    run_dir: Path
    frame: dt.Frame
    selected: set[str] | None  # item ids passing the item-level filters (None = all)


class AnalyticsBase:
    def __init__(
        self, workspace: Workspace, store: IndexStore, locks: ProjectLocks, bus: EventBus
    ) -> None:
        self.workspace = workspace
        self.store = store
        self.locks = locks
        self.bus = bus
        self.variables = VariableService(workspace, store, locks, bus)

    async def inputs(self, pid: str, run_id: str, filters: GlobalFilters) -> Inputs:
        """Load the run, apply DB-02 filters, join statuses and variables."""
        pdir = self.workspace.project_dir(pid)
        rdir = dt.run_dir(pdir, run_id)
        priority = list(self.workspace.get(pid).phase_priority)
        catalog = await self.variables.catalog(pid)
        var_items = (
            (await self.variables.filter_ids(pid, filters.var))["items"] if filters.var else None
        )
        table = await self.variables.table(pid)

        def work() -> Inputs:
            rd = dt.load_run(rdir, run_id)
            statuses = dt.item_statuses(pdir)
            n_total = rd.n
            rd, status = dt.apply_filters(rd, filters, statuses, var_items)
            frame = dt.Frame(rd, status, dt.VarTable.build(catalog, table), priority, n_total)
            selected = _selected_items(self.store, pid, filters, statuses, var_items)
            return Inputs(pdir, rdir, frame, selected)

        return await asyncio.to_thread(work)


def _selected_items(
    store: IndexStore,
    pid: str,
    f: GlobalFilters,
    statuses: dict[str, str],
    var_items: set[str] | None,
) -> set[str] | None:
    """Index items passing the item-level filters (used for run errors without features)."""
    if not any([f.phase, f.scope, f.side, f.status, f.item_ids, var_items is not None]):
        return None
    out: set[str] = set()
    for it in store.load(pid).items:
        if f.phase is not None and it.phase.canonical not in f.phase:
            continue
        if f.scope is not None and it.scope not in f.scope:
            continue
        if f.side is not None and it.side not in f.side:
            continue
        if f.status is not None and statuses.get(it.item_id, dt.NOT_REVIEWED) not in f.status:
            continue
        if var_items is not None and it.item_id not in var_items:
            continue
        if f.item_ids is not None and it.item_id not in f.item_ids:
            continue
        out.add(it.item_id)
    return out


class DashboardService(AnalyticsBase):
    """API-38 view computations (DB-*)."""

    async def run_overview(
        self, pid: str, run_id: str, req: RunOverviewRequest
    ) -> RunOverviewResponse:
        inp = await self.inputs(pid, run_id, req.filters)

        def work() -> RunOverviewResponse:
            run = dt.read_run(inp.run_dir)
            errors = dt.read_errors(inp.run_dir)
            return vw.run_overview(inp.frame, run, errors, inp.selected, req)

        return await asyncio.to_thread(work)

    async def view[Req: ViewRequest, Resp: BaseModel](
        self, pid: str, run_id: str, req: Req, fn: Callable[[dt.Frame, Req], Resp]
    ) -> Resp:
        inp = await self.inputs(pid, run_id, req.filters)
        return await asyncio.to_thread(fn, inp.frame, req)


# -- analyses (API-39) ------------------------------------------------------------------------


@dataclass
class Outcome:
    analysis: Analysis
    tidy: bytes


def compute_analysis(
    frame: dt.Frame, spec: AnalysisSpec, aid: str, at: str, by: str | None
) -> Outcome:
    """ANA-01..09 for one spec over a filtered frame (pure; no I/O)."""
    if spec.question == "paired":
        raise dt.bad(
            ("body", "question"),
            "Paired comparison (ANA-10) is planned for v3.1; use the phase-side-consistency view",
        )
    loc_v = ("body", "variable")
    if spec.question == "explore":
        if spec.variable is not None:
            frame.vars.var(spec.variable, loc_v)
    elif spec.variable is None:
        raise dt.bad(loc_v, f"question {spec.question!r} needs a variable")
    if spec.question == "balance" and spec.confounder is None:
        raise dt.bad(("body", "confounder"), "Balance check needs a second variable (confounder)")
    if spec.confounder is not None:
        cv = frame.vars.var(spec.confounder, ("body", "confounder"))
        if spec.question != "balance":
            an.check_type(cv, dt.LEVEL_TYPES, ("body", "confounder"), "a confounder")
    frame = dt.Frame(
        dt.select_features(frame.rd, spec.features, spec.feature_class),
        frame.status,
        frame.vars,
        frame.priority,
        frame.n_total,
    )
    unit = dt.build_unit(frame, spec.unit)
    if spec.question == "explore":
        c = an.explore(unit)
    else:
        v = frame.vars.var(spec.variable or "", loc_v)
        if spec.question == "compare":
            c = an.compare(unit, v, spec.test)
        elif spec.question == "association":
            c = an.associate(unit, v, spec.test)
        else:
            other = frame.vars.var(spec.confounder or "", ("body", "confounder"))
            c = an.balance(unit, v, other, spec.test)
    recs = recommend(spec, unit, frame.vars.catalog, c)
    analysis = Analysis(
        analysis_id=aid,
        created_at=at,
        created_by=by,
        spec=spec,
        unit=vw.unit_summary(unit, c.n_variable_missing),
        groups=c.groups,
        choice=c.choice,
        results=c.results,
        descriptives=c.descriptives,
        recommendations=recs,
        balance=c.balance,
    )
    return Outcome(analysis, tidy_csv(unit, spec))


def tidy_csv(unit: dt.Unit, spec: AnalysisSpec) -> bytes:
    """ANA-09 tidy table: one row per unit row x (ids, variables, features).

    Variables tagged `sensitive` are left out (VAR-09)."""
    cat = unit.frame.vars.catalog
    names = [
        v.name
        for v in cat.variables
        if "sensitive" not in v.tags
        and v.name in unit.frame.vars.columns
        and v.type not in ("identifier", "constant")
    ]
    for extra in (spec.variable, spec.confounder):
        if extra and extra not in names and extra in unit.frame.vars.columns:
            names.insert(0, extra)
    rd = unit.frame.rd
    cols: dict[str, list[Any]] = {
        "case_id": [str(c) for c in unit.case_id],
        "item_id": [ids[0] for ids in unit.item_ids],
        "item_ids": [";".join(ids) for ids in unit.item_ids],
        "phase": [str(rd.phase[i]) for i in unit.rep],
        "scope": [unit.scope] * unit.n,
        "label": [unit.label] * unit.n,
    }
    for n in names:
        v = cat.get(n)
        if v is not None and v.type == "continuous":
            cols[n] = [None if x != x else x for x in unit.numeric(n).tolist()]
        else:
            cols[n] = [dt.level_str(x) for x in unit.raw(n)]
    for j, f in enumerate(unit.features):
        cols[f] = [None if x != x else x for x in unit.x[:, j].tolist()]
    return _csv(cols)


def _csv(cols: dict[str, list[Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    keys = list(cols)
    w.writerow(keys)
    n = len(cols[keys[0]]) if keys else 0
    for i in range(n):
        w.writerow(["" if cols[k][i] is None else _cell(cols[k][i]) for k in keys])
    return buf.getvalue().encode("utf-8")


def _cell(v: Any) -> str:
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, list):
        return ";".join(str(x) for x in v)
    return str(v)


def _rows_csv(rows: list[BaseModel]) -> bytes:
    if not rows:
        return b""
    dumped = [r.model_dump(mode="json") for r in rows]
    return _csv({k: [d[k] for d in dumped] for k in dumped[0]})


def _parquet(rows: list[BaseModel], model: type[BaseModel]) -> bytes:
    dumped = [r.model_dump(mode="json") for r in rows]
    cols = {k: [d[k] for d in dumped] for k in model.model_fields}
    fields = []
    for k, finfo in model.model_fields.items():
        ann = str(finfo.annotation)
        if k == "groups":
            fields.append(pa.field(k, pa.list_(pa.string())))
        elif "float" in ann:
            fields.append(pa.field(k, pa.float64()))
        elif "int" in ann and "str" not in ann:
            fields.append(pa.field(k, pa.int64()))
        elif ann == "<class 'bool'>" or ann == "bool":
            fields.append(pa.field(k, pa.bool_()))
        else:
            fields.append(pa.field(k, pa.string()))
    table = pa.Table.from_pydict(cols, schema=pa.schema(fields))
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def _read_parquet_rows[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    t = pq.read_table(path)
    return [model.model_validate(r) for r in t.to_pylist()]


class AnalysisService(AnalyticsBase):
    """API-39: create + run synchronously, list, read, export (ANA-01..09)."""

    def _dir(self, pid: str) -> Path:
        return self.workspace.project_dir(pid) / ANALYSES

    def _adir(self, pid: str, aid: str) -> Path:
        d = self._dir(pid) / aid
        if not is_ulid(aid) or not (d / SPEC).is_file():
            raise NotFound(f"Analysis {aid!r} not found")
        return d

    async def create(self, pid: str, spec: AnalysisSpec, reviewer: str | None) -> Analysis:
        inp = await self.inputs(pid, spec.run_id, spec.filters)
        aid, at = new_ulid(), utc_now()
        out = await asyncio.to_thread(compute_analysis, inp.frame, spec, aid, at, reviewer)
        a = out.analysis
        d = self._dir(pid) / aid
        head = {
            "analysis_id": aid,
            "created_at": at,
            "created_by": reviewer,
            "spec": spec.model_dump(mode="json"),
            "unit": a.unit.model_dump(mode="json"),
            "groups": [g.model_dump(mode="json") for g in a.groups],
            "choice": a.choice.model_dump(mode="json"),
            "balance": a.balance.model_dump(mode="json") if a.balance else None,
        }
        results_pq = _parquet(list(a.results), ResultRow)
        desc_pq = _parquet(list(a.descriptives), DescriptiveRow)
        async with self.locks(pid):
            atomic_write_bytes(d / RESULTS, results_pq)
            atomic_write_bytes(d / DESCRIPTIVES, desc_pq)
            atomic_write_json(
                d / RECOMMENDATIONS, [r.model_dump(mode="json") for r in a.recommendations]
            )
            ex = d / EXPORTS
            atomic_write_bytes(ex / "tidy.csv", out.tidy)
            atomic_write_bytes(ex / "results.csv", _rows_csv(list(a.results)))
            atomic_write_bytes(ex / "descriptives.csv", _rows_csv(list(a.descriptives)))
            atomic_write_json(ex / "spec.json", head)
            atomic_write_json(d / SPEC, head)  # last: its presence marks a complete analysis
        self.bus.publish(pid, "project.updated", {"fields": ["analyses"]})
        return a

    def _read(self, d: Path) -> Analysis:
        head = read_json(d / SPEC)
        return Analysis(
            analysis_id=head["analysis_id"],
            created_at=head["created_at"],
            created_by=head.get("created_by"),
            spec=AnalysisSpec.model_validate(head["spec"]),
            unit=UnitSummary.model_validate(head["unit"]),
            groups=[GroupInfo.model_validate(g) for g in head["groups"]],
            choice=TestChoice.model_validate(head["choice"]),
            results=_read_parquet_rows(d / RESULTS, ResultRow),
            descriptives=_read_parquet_rows(d / DESCRIPTIVES, DescriptiveRow),
            recommendations=[
                Recommendation.model_validate(r) for r in read_json(d / RECOMMENDATIONS)
            ],
            balance=Contingency.model_validate(head["balance"]) if head.get("balance") else None,
        )

    async def get(self, pid: str, aid: str) -> Analysis:
        d = self._adir(pid, aid)
        return await asyncio.to_thread(self._read, d)

    async def list(self, pid: str, run_id: str | None = None) -> AnalysisList:
        root = self._dir(pid)

        def work() -> list[AnalysisSummary]:
            out: list[AnalysisSummary] = []
            if not root.is_dir():
                return out
            for d in root.iterdir():
                if not (d / SPEC).is_file() or not is_ulid(d.name):
                    continue
                head = read_json(d / SPEC)
                spec = AnalysisSpec.model_validate(head["spec"])
                if run_id is not None and spec.run_id != run_id:
                    continue
                res = pq.read_table(d / RESULTS, columns=["q"]).column("q").to_pylist()
                recs = read_json(d / RECOMMENDATIONS)
                out.append(
                    AnalysisSummary(
                        analysis_id=head["analysis_id"],
                        name=spec.name,
                        created_at=head["created_at"],
                        created_by=head.get("created_by"),
                        run_id=spec.run_id,
                        question=spec.question,
                        variable=spec.variable,
                        confounder=spec.confounder,
                        n_rows=head["unit"]["n_rows"],
                        n_tested=sum(q is not None for q in res),
                        n_significant=sum(q is not None and q < 0.05 for q in res),
                        n_recommendations=len(recs),
                    )
                )
            out.sort(key=lambda s: s.analysis_id, reverse=True)
            return out

        items = await asyncio.to_thread(work)
        return AnalysisList(items=items, next_cursor=None, total=len(items))

    def export_path(self, pid: str, aid: str, file: ExportFile) -> tuple[Path, str, str]:
        """ANA-09 file → (path, media type, download name)."""
        d = self._adir(pid, aid)
        name, media = EXPORT_NAMES[file]
        p = d / EXPORTS / name
        if not p.is_file():
            raise NotFound(f"Export {file!r} of analysis {aid!r} not found")
        return p, media, f"analysis_{SAFE.sub('_', aid)}_{name}"
