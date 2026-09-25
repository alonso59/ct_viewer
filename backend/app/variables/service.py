"""Variable catalog service (VAR-01..11, API-16..18).

Stateless like the other services: routers build one per request. `rebuild` re-profiles
the index and rewrites `variables/catalog.json` (overrides + derived + external definitions,
VAR-11) and `index/variables.parquet` (PRJ-10: derived, rebuildable). Only this (API) process
writes, under the project lock (BE-05).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pyarrow as pa

from app.core.errors import NotFound, ValidationProblem
from app.core.fsio import atomic_write_bytes, atomic_write_json, read_json
from app.core.ids import new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.events.bus import EventBus
from app.ingest.models import Item
from app.ingest.store import IndexStore
from app.labeling import state as labeling_state
from app.projects.service import Workspace
from app.variables import build as builder
from app.variables import external as ext_mod
from app.variables import table as tbl
from app.variables.models import (
    Catalog,
    DerivedDef,
    ExternalReport,
    ExternalTable,
    VariableOverride,
    VarType,
)
from app.variables.schema import RESERVED_NAMES

CATALOG = Path("variables") / "catalog.json"
EXTERNAL_DIR = Path("variables") / "external"
TABLE = Path("index") / "variables.parquet"
LIST_CAP = 50


# LBL-02 column types → variable types (VAR-02)
LAYER_TYPES: dict[str, VarType] = {
    "bool": "categorical", "category": "categorical", "number": "continuous", "text": "text",
    "date": "date",
}  # fmt: skip


def _layer_text(v: object) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


class VariableService:
    def __init__(
        self, workspace: Workspace, store: IndexStore, locks: ProjectLocks, bus: EventBus
    ) -> None:
        self.workspace = workspace
        self.store = store
        self.locks = locks
        self.bus = bus

    # -- paths / persistence ----------------------------------------------------------------

    def _pdir(self, project_id: str) -> Path:
        return self.workspace.project_dir(project_id)

    def table_path(self, project_id: str) -> Path:
        return self._pdir(project_id) / TABLE

    def _stored(self, project_id: str) -> Catalog | None:
        p = self._pdir(project_id) / CATALOG
        return Catalog.model_validate(read_json(p)) if p.exists() else None

    def _external_data(self, project_id: str, cat: Catalog) -> list[builder.ExternalData]:
        out: list[builder.ExternalData] = []
        for t in cat.external:
            raw = (self._pdir(project_id) / EXTERNAL_DIR / t.filename).read_bytes()
            _, _, rows, _, _ = ext_mod.parse_table(raw, t.filename, t.key)
            out.append(builder.ExternalData(t, rows))
        return out

    def _build(
        self,
        project_id: str,
        base: Catalog,
        *,
        derived: Sequence[DerivedDef] | None = None,
        overrides: Mapping[str, VariableOverride] | None = None,
        external: Sequence[builder.ExternalData] | None = None,
        strict: bool = False,
    ) -> tuple[builder.Built, dict[str, list[str]]]:
        items = self.store.load(project_id).items
        return builder.build(
            items,
            overrides=base.overrides if overrides is None else overrides,
            derived=base.derived if derived is None else derived,
            external=self._external_data(project_id, base) if external is None else external,
            layers=self._layer_data(project_id, items),
            strict=strict,
        )

    def _layer_data(self, project_id: str, items: Sequence[Item]) -> list[builder.LayerData]:
        """LBL-06 / VAR-12: label columns as `lbl.{table}.{column}` at their table's level
        (scan and item tables share the scan unit; an item value lands on its scan)."""
        pdir = self._pdir(project_id)
        cells = labeling_state.cell_state(pdir)
        out: list[builder.LayerData] = []
        for t in labeling_state.active_tables(pdir):
            for c in t.columns:
                if c.hidden:
                    continue
                ld = builder.LayerData(
                    f"lbl.{t.slug}.{c.slug}", "case" if t.level == "case" else "scan",
                    LAYER_TYPES[c.type],
                )  # fmt: skip
                values = {tg: e.get("value") for (tid, cid, tg), e in cells.items()
                          if tid == t.table_id and cid == c.column_id}  # fmt: skip
                text = {k: _layer_text(v) for k, v in values.items()}
                for it in items:
                    if it.status == "excluded_upstream":
                        continue
                    if t.level == "case":
                        ld.by_case[it.case_id] = text.get(it.case_id)
                        continue
                    key = f"{it.case_id}.{it.scan_idx}" if t.level == "scan" else it.item_id
                    sk = (it.case_id, it.scan_idx)
                    if ld.by_scan.get(sk) is None:
                        ld.by_scan[sk] = text.get(key)
                out.append(ld)
        return out

    def _save(self, project_id: str, built: builder.Built) -> Catalog:
        cat = built.catalog.model_copy(
            update={"profiled_at": utc_now(), "import_id": self.store.status(project_id).import_id}
        )
        pdir = self._pdir(project_id)
        tbl.write_table(pdir / TABLE, tbl.to_arrow(built))
        atomic_write_json(pdir / CATALOG, cat.model_dump(mode="json"))
        return cat

    def _publish(self, project_id: str) -> None:
        self.bus.publish(project_id, "project.updated", {"fields": ["variables"]})

    # -- reads (API-16) ---------------------------------------------------------------------

    async def catalog(self, project_id: str) -> Catalog:
        """The stored catalog; profiles on first access when an index exists but no catalog."""
        cat = self._stored(project_id)
        if cat is not None and self.table_path(project_id).exists():
            return cat
        if not self.store.load(project_id).items:
            return cat or Catalog()
        return await self.rebuild(project_id)

    async def table(self, project_id: str, columns: Sequence[str] | None = None) -> pa.Table | None:
        """`index/variables.parquet` for analytics/radiomics joins (ANA-03, RAD-05)."""
        await self.catalog(project_id)
        return tbl.read_table(self.table_path(project_id), columns)

    def case_values(self, project_id: str) -> dict[str, dict[str, float | str | None]]:
        """Case-level visible variables per case (explorer columns/colour, VAR-10).

        Reads the stored catalog + table only (no profiling); empty before the first index.
        """
        cat = self._stored(project_id)
        if cat is None:
            return {}
        names = [v.name for v in cat.variables if v.level == "case" and v.visible]
        t = tbl.read_table(self.table_path(project_id), ["case_id", *names]) if names else None
        if t is None:
            return {}
        rows = t.to_pydict()
        out: dict[str, dict[str, float | str | None]] = {}
        for i, case_id in enumerate(rows["case_id"]):
            if case_id not in out:
                out[case_id] = {n: rows[n][i] for n in names}
        return out

    async def filter_ids(
        self, project_id: str, filters: Mapping[str, Sequence[str]]
    ) -> dict[str, set[str]]:
        """VAR-10 `var.{name}` filters → matching `items` and `cases`."""
        cat = await self.catalog(project_id)
        names = list(filters)
        for n in names:
            self.get_or_422(cat, n)
        t = tbl.read_table(self.table_path(project_id), ["item_id", "case_id", *names])
        return tbl.matching_ids(cat, t, filters)

    @staticmethod
    def get_or_422(cat: Catalog, name: str) -> None:
        if cat.get(name) is None:
            raise ValidationProblem(
                f"Unknown variable {name!r}",
                errors=[{"loc": ["query", f"var.{name}"], "msg": "unknown variable"}],
            )

    # -- writes -----------------------------------------------------------------------------

    async def rebuild(self, project_id: str) -> Catalog:
        """Re-profile after an index rebuild or a catalog change (VAR-01)."""
        async with self.locks(project_id):
            base = self._stored(project_id) or Catalog()
            built, _ = await asyncio.to_thread(self._build, project_id, base)
            cat = self._save(project_id, built)
        self._publish(project_id)
        return cat

    async def patch(self, project_id: str, name: str, patch: VariableOverride) -> Catalog:
        """API-16 PATCH: confirm/override type, visibility, tags (VAR-03/05)."""
        async with self.locks(project_id):
            base = self._stored(project_id) or Catalog()
            if base.get(name) is None:
                raise NotFound(f"Variable {name!r} not found")
            old = base.overrides.get(name, VariableOverride())
            merged = old.model_copy(update=patch.model_dump(exclude_unset=True, exclude_none=True))
            overrides = {**base.overrides, name: merged}
            built, _ = await asyncio.to_thread(self._build, project_id, base, overrides=overrides)
            cat = self._save(project_id, built)
        self._publish(project_id)
        return cat

    async def add_derived(self, project_id: str, d: DerivedDef) -> Catalog:
        """API-17 POST (VAR-06); the definition is validated against the current catalog."""
        async with self.locks(project_id):
            base = self._stored(project_id) or Catalog()
            if any(x.name == d.name for x in base.derived):
                raise ValidationProblem(
                    f"Variable {d.name!r} already exists",
                    errors=[{"loc": ["body", "name"], "msg": "taken"}],
                )
            derived = [*base.derived, d]
            built, _ = await asyncio.to_thread(
                self._build, project_id, base, derived=derived, strict=True
            )
            cat = self._save(project_id, built)
        self._publish(project_id)
        return cat

    async def delete_derived(self, project_id: str, name: str) -> Catalog:
        async with self.locks(project_id):
            base = self._stored(project_id) or Catalog()
            if not any(x.name == name for x in base.derived):
                raise NotFound(f"Derived variable {name!r} not found")
            users = [
                x.name
                for x in base.derived
                if x.name != name and name in (x.sources if x.op == "dominant" else [x.source])
            ]
            if users:
                raise ValidationProblem(
                    f"Variable {name!r} is used by {', '.join(users)}",
                    errors=[{"loc": ["path", "name"], "msg": "in use"}],
                )
            derived = [x for x in base.derived if x.name != name]
            overrides = {k: v for k, v in base.overrides.items() if k != name}
            built, _ = await asyncio.to_thread(
                self._build, project_id, base, derived=derived, overrides=overrides
            )
            cat = self._save(project_id, built)
        self._publish(project_id)
        return cat

    async def import_external(
        self,
        project_id: str,
        data: bytes,
        filename: str,
        key: ext_mod.KeyName | None = None,
    ) -> ExternalReport:
        """API-18 (VAR-07): snapshot the table, add its columns as case-level variables."""
        key_name, columns, rows, dups, n_rows = ext_mod.parse_table(data, filename, key)
        if not columns:
            raise ValidationProblem(
                "table has no value columns", errors=[{"loc": ["body", "file"], "msg": "empty"}]
            )
        table_id = new_ulid()
        suffix = ".tsv" if filename.lower().endswith(".tsv") else ".csv"
        table = ExternalTable(
            table_id=table_id,
            filename=f"{table_id}{suffix}",
            key=key_name,
            columns=columns,
            sha256=hashlib.sha256(data).hexdigest(),
            imported_at=utc_now(),
        )
        ext = builder.ExternalData(table, rows)
        async with self.locks(project_id):
            base = self._stored(project_id) or Catalog()
            items = self.store.load(project_id).items
            n_matched, unmatched = builder.match_report(ext, items)
            taken = {v.name for v in base.variables if v.source != "derived"}
            conflicts = [c for c in columns if c in taken or c in RESERVED_NAMES]
            externals = [*self._external_data(project_id, base), ext]
            built, _ = await asyncio.to_thread(self._build, project_id, base, external=externals)
            if len(conflicts) == len(columns):
                raise ValidationProblem(
                    "every column name is already taken",
                    errors=[{"loc": ["body", "file"], "msg": f"conflicts: {conflicts}"}],
                )
            atomic_write_bytes(self._pdir(project_id) / EXTERNAL_DIR / table.filename, data)
            self._save(project_id, built)
        self._publish(project_id)
        return ExternalReport(
            table=table,
            n_rows=n_rows,
            n_matched=n_matched,
            n_unmatched=len(unmatched),
            unmatched_keys=unmatched[:LIST_CAP],
            duplicate_keys=dups[:LIST_CAP],
            conflicts=conflicts,
        )
