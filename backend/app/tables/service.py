"""Where analysis tables live and how they are read, in place: radiomics runs
(`radiomics/runs/{rid}/features.parquet`) and task tables (`tasks/runs/{rid}/tables/{name}/`)."""

from __future__ import annotations

import asyncio
import hashlib
import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from app.core.errors import NotFound
from app.core.fsio import atomic_write_bytes, atomic_write_json, read_json
from app.core.ids import is_ulid, utc_now
from app.projects.service import Workspace
from app.tables.models import (
    TABLE_ID_RE,
    TABLE_NAME_RE,
    TABLE_SCHEMA,
    VOLUME,
    TableColumn,
    TableCounts,
    TableManifest,
    TableProducer,
    TableSpec,
    TableSummary,
)

RADIOMICS_RUNS: Final = Path("radiomics") / "runs"
TASK_RUNS: Final = Path("tasks") / "runs"
TABLES: Final = "tables"
DATA: Final = "table.parquet"
MANIFEST: Final = "table.json"
RUN_JSON: Final = "run.json"
FEATURES: Final = "features.parquet"
RADIOMICS_TASK: Final = "radiomics.pyradiomics"
RADIOMICS_VOLUME: Final = "original_shape_MeshVolume"
KEYS: Final = "item_id, case_id, scan_idx, scope, side, phase, label, instance"
_SELECT: Final = {
    # PyRadiomics names a value `{image_type}_{feature_class}_{feature}`
    "radiomics": """
SELECT item_id, case_id, scan_idx, scope, side, phase, CAST(label AS BIGINT) AS label,
       '' AS instance, feature_class AS "group",
       image_type || '_' || feature_class || '_' || feature AS name, CAST(value AS DOUBLE) AS value
FROM read_parquet(?)""",
    "task": f'SELECT {KEYS}, "group", name, value FROM read_parquet(?)',
}


@dataclass(frozen=True)
class Source:
    table_id: str
    store: Literal["radiomics", "task"]
    data: Path
    run_dir: Path  # the producer run's folder
    roles: dict[str, str]
    title: str


def source(project_dir: Path, table_id: str) -> Source:
    """The table's files, or `not-found`."""
    if TABLE_ID_RE.match(table_id):
        rdir = project_dir / RADIOMICS_RUNS / table_id
        if (rdir / RUN_JSON).is_file() and (rdir / FEATURES).is_file():
            name = str(read_json(rdir / RUN_JSON).get("name") or "")
            return Source(
                table_id, "radiomics", rdir / FEATURES, rdir, {VOLUME: RADIOMICS_VOLUME}, name
            )
        rid, _, name = table_id.partition("-")
        tdir = project_dir / TASK_RUNS / rid / TABLES / name
        if name and is_ulid(rid) and (tdir / MANIFEST).is_file() and (tdir / DATA).is_file():
            m = TableManifest.model_validate(read_json(tdir / MANIFEST))
            return Source(table_id, "task", tdir / DATA, tdir.parent.parent, m.roles, m.title)
    raise NotFound(f"Table {table_id!r} not found (or has no values yet)")


def read_long(src: Source) -> pa.Table:
    """The table in the canonical long shape (`TABLE_SCHEMA` columns)."""
    with duckdb.connect() as con:
        return con.execute(_SELECT[src.store], [str(src.data)]).to_arrow_table()


def _run_dirs(root: Path) -> Iterator[Path]:
    if root.is_dir():
        for d in root.iterdir():
            if is_ulid(d.name) and (d / RUN_JSON).is_file():
                yield d


def _radiomics_summary(run_dir: Path) -> TableSummary:
    """Read leniently: a run record written by an older release may lack newer fields."""
    raw = read_json(run_dir / RUN_JSON)
    rec: dict[str, Any] = raw if isinstance(raw, dict) else {}
    counts = rec.get("counts") or {}
    labels = (rec.get("selection") or {}).get("labels") or []
    return TableSummary(
        table_id=run_dir.name,
        kind="radiomics",
        title=str(rec.get("name") or ""),
        status=str(rec.get("status") or ""),
        created_at=str(rec.get("created_at") or ""),
        producer=TableProducer(task=RADIOMICS_TASK, run_id=run_dir.name),
        roles={VOLUME: RADIOMICS_VOLUME},
        labels=sorted(int(v) for v in labels),
        counts=TableCounts(
            items=int(counts.get("items") or 0), columns=int(counts.get("features") or 0)
        ),
    )


def summaries(project_dir: Path) -> list[TableSummary]:
    """Every table of the project, newest first."""
    out: list[TableSummary] = []
    for rdir in _run_dirs(project_dir / RADIOMICS_RUNS):
        if (rdir / FEATURES).is_file():
            out.append(_radiomics_summary(rdir))
    for rdir in _run_dirs(project_dir / TASK_RUNS):
        tables = rdir / TABLES
        if not tables.is_dir():
            continue
        for tdir in sorted(tables.iterdir()):
            if (tdir / MANIFEST).is_file() and (tdir / DATA).is_file():
                m = TableManifest.model_validate(read_json(tdir / MANIFEST))
                out.append(TableSummary.model_validate(m.model_dump(exclude={"columns"})))
    out.sort(key=lambda s: s.table_id, reverse=True)
    return out


def manifest(project_dir: Path, table_id: str) -> TableManifest:
    src = source(project_dir, table_id)
    if src.store == "task":
        return TableManifest.model_validate(read_json(src.data.parent / MANIFEST))
    summary = _radiomics_summary(src.run_dir)
    sql = f'SELECT DISTINCT name, "group" FROM ({_SELECT["radiomics"]}) ORDER BY name'
    with duckdb.connect() as con:
        rows = con.execute(sql, [str(src.data)]).fetchall()
    columns = [TableColumn(name=n, group=g) for n, g in rows]
    counts = summary.counts.model_copy(update={"columns": len(columns)})
    return TableManifest(**summary.model_dump(exclude={"counts"}), counts=counts, columns=columns)


def export(src: Source, fmt: Literal["csv", "parquet"], shape: Literal["long", "wide"]) -> bytes:
    """The table as CSV or Parquet; `wide` has one row per observation, one column per name."""
    t = read_long(src)
    if shape == "wide":
        with duckdb.connect() as con:
            con.register("long", t)  # PIVOT on values found in the data cannot take parameters
            pivot = f"PIVOT long ON name USING first(value) GROUP BY {KEYS} ORDER BY {KEYS}"
            t = con.sql(pivot).to_arrow_table()
    buf = io.BytesIO()
    if fmt == "csv":
        pacsv.write_csv(t, buf)
    else:
        pq.write_table(t, buf, compression="zstd")
    return buf.getvalue()


def store_task_table(
    run_dir: Path, task: str, status: str, entry: dict[str, Any], job_dir: Path
) -> TableManifest:
    """Check a table a task declared (a job-folder Parquet with the canonical columns, its hash
    and spec) and store it with its manifest under the run folder."""
    name = str(entry.get("name") or "")
    if not TABLE_NAME_RE.match(name):
        raise ValueError(f"table name {name!r} must be lower-case letters, digits or _")
    path = (job_dir / str(entry.get("path", ""))).resolve()
    if not path.is_file() or not path.is_relative_to(job_dir.resolve()):
        raise ValueError(f"table {name!r} is not a file in the job folder")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
        raise ValueError(f"table {name!r} changed after the task declared it")
    spec = TableSpec.model_validate(entry.get("spec") or {})
    t = pq.read_table(pa.BufferReader(data))
    if set(t.schema.names) != set(TABLE_SCHEMA.names) or any(
        not t.schema.field(f.name).type.equals(f.type) for f in TABLE_SCHEMA
    ):
        raise ValueError(f"table {name!r} does not have the analysis table columns")
    t = t.select(TABLE_SCHEMA.names)
    if t["item_id"].null_count or t["name"].null_count or t["label"].null_count:
        raise ValueError(f"table {name!r} has rows without item_id, label or name")
    if spec.grain == "label" and pc.any(pc.not_equal(pc.fill_null(t["instance"], ""), "")).as_py():
        raise ValueError(f"table {name!r} has instances but declares one row per label")
    names = {str(n) for n in pc.unique(t["name"]).to_pylist()}
    unknown = sorted(set(spec.roles.values()) - names)
    if unknown:
        raise ValueError(f"table {name!r} has no column {', '.join(unknown)} named in its roles")
    groups = {
        str(r["name"]): str(r["group"] or "")
        for r in t.select(["name", "group"]).group_by(["name", "group"]).aggregate([]).to_pylist()
    }
    columns = spec.columns or [TableColumn(name=n, group=groups[n]) for n in sorted(names)]
    obs = pc.binary_join_element_wise(
        t["item_id"], pc.cast(t["label"], pa.string()), pc.fill_null(t["instance"], ""), "\x1f"
    )
    manifest = TableManifest(
        table_id=f"{run_dir.name}-{name}",
        kind=spec.kind,
        title=spec.title,
        status=status,
        created_at=utc_now(),
        producer=TableProducer(task=task, run_id=run_dir.name),
        grain=spec.grain,
        instance_name=spec.instance_name,
        roles={str(k): v for k, v in spec.roles.items()},
        labels=sorted(int(v) for v in pc.unique(t["label"]).to_pylist()),
        counts=TableCounts(
            items=len(pc.unique(t["item_id"])),
            columns=len(names),
            observations=len(pc.unique(obs)),
        ),
        columns=columns,
    )
    dest = run_dir / TABLES / name
    atomic_write_bytes(dest / DATA, data)
    atomic_write_json(dest / MANIFEST, manifest.model_dump(mode="json"))  # last: marks it complete
    return manifest


class TablesService:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def list(self, pid: str) -> list[TableSummary]:
        return await asyncio.to_thread(summaries, self.workspace.project_dir(pid))

    async def get(self, pid: str, table_id: str) -> TableManifest:
        return await asyncio.to_thread(manifest, self.workspace.project_dir(pid), table_id)

    async def export(
        self,
        pid: str,
        table_id: str,
        fmt: Literal["csv", "parquet"],
        shape: Literal["long", "wide"],
    ) -> bytes:
        src = source(self.workspace.project_dir(pid), table_id)
        return await asyncio.to_thread(export, src, fmt, shape)
