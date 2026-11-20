"""Table inputs for analytics: an analysis table → wide observation matrix, global filters,
variable columns and the unit of analysis.

An observation is one `(item_id, label, instance)`; `instance` is empty in label-grain tables.
A column is a value name of the table (e.g. `original_shape_MeshVolume` in a radiomics run).
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from numpy.typing import NDArray

from app.analytics.models import ColorBy, GlobalFilters, UnitSpec
from app.analytics.stats import F64, quiet
from app.core.errors import ValidationProblem
from app.tables.models import VOLUME
from app.tables.service import Source, read_long
from app.variables.models import Catalog, Variable

NOT_REVIEWED = "not_reviewed"
# Types usable as groups. `numeric-discrete` must be confirmed first, except as a
# color/confounder level where no test depends on the type.
GROUP_TYPES = frozenset({"categorical"})
LEVEL_TYPES = frozenset({"categorical", "numeric-discrete"})
CONTINUOUS_TYPES = frozenset({"continuous"})
MODALITY_VAR = "modality"  # converter field, a default confounder

Obj = NDArray[np.object_]
Bool = NDArray[np.bool_]
Idx = NDArray[np.intp]


def bad(loc: Sequence[str], msg: str) -> ValidationProblem:
    return ValidationProblem(msg, errors=[{"loc": list(loc), "msg": msg}])


@dataclass
class TableData:
    """Wide observation matrix. `x[i, j]` is NaN where the column is absent (`present`).

    `phase` is the effective phase once `join_phase` ran; `phase_at_run` keeps the value the
    producer recorded. `roles` names the columns with a known meaning (`volume`).
    """

    table_id: str
    features: list[str]
    group: list[str]
    item_id: Obj
    case_id: Obj
    scan_idx: Obj
    scope: Obj
    side: Obj
    phase: Obj
    label: NDArray[np.int64]
    instance: Obj
    x: F64
    present: Bool
    phase_at_run: Obj
    roles: dict[str, str] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return int(self.item_id.size)

    @property
    def volume(self) -> str | None:
        """The volume column, when the table has one."""
        name = self.roles.get(VOLUME)
        return name if name in self.features else None

    def take(self, rows: Idx | Bool) -> TableData:
        return replace(
            self,
            item_id=self.item_id[rows],
            case_id=self.case_id[rows],
            scan_idx=self.scan_idx[rows],
            scope=self.scope[rows],
            side=self.side[rows],
            phase=self.phase[rows],
            label=self.label[rows],
            instance=self.instance[rows],
            x=self.x[rows],
            present=self.present[rows],
            phase_at_run=self.phase_at_run[rows],
        )

    def cols(self, keep: Sequence[int]) -> TableData:
        k = list(keep)
        return replace(
            self,
            features=[self.features[i] for i in k],
            group=[self.group[i] for i in k],
            x=self.x[:, k],
            present=self.present[:, k],
        )

    def col(self, feature: str, loc: Sequence[str] = ("body", "feature")) -> F64:
        try:
            j = self.features.index(feature)
        except ValueError:
            raise bad(loc, f"Unknown feature {feature!r} in table {self.table_id}") from None
        return self.x[:, j]


_cache: OrderedDict[tuple[str, int, int], TableData] = OrderedDict()
_cache_lock = threading.Lock()
CACHE_MAX = 4


def load_table(src: Source) -> TableData:
    """Pivot the table's long values into `TableData`; LRU-cached by file identity."""
    st = src.data.stat()
    key = (str(src.data), st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    td = _pivot(read_long(src), src.table_id, src.roles)
    with _cache_lock:
        _cache[key] = td
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return td


def _pivot(t: pa.Table, table_id: str, roles: dict[str, str]) -> TableData:
    if t.num_rows == 0:
        e = np.asarray([], dtype=object)
        return TableData(
            table_id,
            [],
            [],
            e,
            e,
            e,
            e,
            e,
            e,
            np.asarray([], dtype=np.int64),
            e,
            np.zeros((0, 0)),
            np.zeros((0, 0), dtype=bool),
            e,
            dict(roles),
        )
    obs_key = pc.binary_join_element_wise(
        t["item_id"], pc.cast(t["label"], pa.string()), t["instance"], "\x1f"
    ).combine_chunks()
    obs_enc = pc.dictionary_encode(obs_key)
    obs_idx = np.asarray(obs_enc.indices.to_numpy(zero_copy_only=False), dtype=np.intp)
    key_enc = pc.dictionary_encode(t["name"].combine_chunks())
    key_names = [str(k) for k in key_enc.dictionary.to_pylist()]
    order = sorted(range(len(key_names)), key=lambda j: key_names[j])
    remap = np.empty(len(key_names), dtype=np.intp)
    remap[order] = np.arange(len(order))
    feat_idx = remap[np.asarray(key_enc.indices.to_numpy(zero_copy_only=False), dtype=np.intp)]
    n_obs, n_feat = len(obs_enc.dictionary), len(key_names)
    values = np.asarray(
        t["value"].combine_chunks().to_numpy(zero_copy_only=False), dtype=np.float64
    )
    x = np.full((n_obs, n_feat), np.nan)
    present = np.zeros((n_obs, n_feat), dtype=bool)
    x[obs_idx, feat_idx] = values
    present[obs_idx, feat_idx] = True
    _, first = np.unique(obs_idx, return_index=True)
    _, first_f = np.unique(feat_idx, return_index=True)  # every feature index occurs

    def rows(name: str) -> Obj:
        return np.asarray(t[name].take(pa.array(first)).to_pylist(), dtype=object)

    groups = t["group"].take(pa.array(first_f)).to_pylist()
    phase = rows("phase")
    return TableData(
        table_id=table_id,
        features=[key_names[j] for j in order],
        group=[str(g) for g in groups],
        item_id=rows("item_id"),
        case_id=rows("case_id"),
        scan_idx=rows("scan_idx"),
        scope=rows("scope"),
        side=rows("side"),
        phase=phase,
        label=np.asarray(t["label"].take(pa.array(first)).to_pylist(), dtype=np.int64),
        instance=np.asarray(["" if v is None else str(v) for v in rows("instance")], dtype=object),
        x=x,
        present=present,
        phase_at_run=phase.copy(),
        roles=dict(roles),
    )


def join_phase(rd: TableData, effective: dict[str, str]) -> TableData:
    """Each item's effective phase replaces the producer's value, kept in `phase_at_run`.
    Items no longer in the index keep the producer's value."""
    phase = np.asarray(
        [effective.get(str(i), p) for i, p in zip(rd.item_id, rd.phase_at_run, strict=True)],
        dtype=object,
    )
    return replace(rd, phase=phase)


def select_features(
    rd: TableData, features: Sequence[str] | None, groups: Sequence[str] | None
) -> TableData:
    if features is not None:
        known = set(rd.features)
        unknown = [f for f in features if f not in known]
        if unknown:
            raise bad(("body", "features"), f"Unknown features: {', '.join(unknown[:10])}")
        want = set(features)
        rd = rd.cols([j for j, f in enumerate(rd.features) if f in want])
    if groups is not None:
        keep = set(groups)
        rd = rd.cols([j for j, g in enumerate(rd.group) if g in keep])
    return rd


@dataclass
class VarTable:
    """`index/variables.parquet` columns aligned to item ids."""

    catalog: Catalog
    row_of: dict[str, int]
    columns: dict[str, list[Any]]

    @classmethod
    def build(cls, catalog: Catalog, table: pa.Table | None) -> VarTable:
        if table is None:
            return cls(catalog, {}, {})
        cols = table.to_pydict()
        return cls(catalog, {iid: i for i, iid in enumerate(cols["item_id"])}, cols)

    def var(self, name: str, loc: Sequence[str]) -> Variable:
        v = self.catalog.get(name)
        if v is None or name not in self.columns:
            raise bad(loc, f"Unknown variable {name!r}")
        return v

    def values(self, name: str, item_ids: Obj) -> Obj:
        """Per-item values (float or str; None = missing)."""
        out = np.full(item_ids.size, None, dtype=object)
        col = self.columns.get(name)
        if col is None:
            return out
        for i, iid in enumerate(item_ids):
            r = self.row_of.get(str(iid))
            if r is not None:
                out[i] = col[r]
        return out


def as_float(values: Obj) -> F64:
    return np.asarray([math.nan if v is None else float(v) for v in values], dtype=np.float64)


def level_str(v: Any) -> str | None:
    """Categorical level text; numbers print without a trailing `.0`."""
    if v is None:
        return None
    if isinstance(v, float):
        return f"{v:g}" if math.isfinite(v) else None
    return str(v) or None


@dataclass
class Frame:
    """A filtered table joined with statuses and variables (one request's inputs)."""

    rd: TableData
    status: Obj
    vars: VarTable
    priority: list[str]
    n_total: int = 0

    def levels(self, color: ColorBy | None, loc: Sequence[str]) -> Obj:
        """Color/split levels per observation (None when no color)."""
        n = self.rd.n
        if color is None:
            return np.full(n, None, dtype=object)
        if color.kind == "variable":
            name = color.name or ""
            v = self.vars.var(name, (*loc, "name"))
            if v.type not in LEVEL_TYPES:
                raise bad((*loc, "name"), f"{name!r} is {v.type}; color by a categorical variable")
            return np.asarray([level_str(x) for x in self.vars.values(name, self.rd.item_id)])
        if color.kind == "curation_status":
            return self.status.copy()
        if color.kind == "label":
            return np.asarray([str(x) for x in self.rd.label], dtype=object)
        src: Obj = getattr(self.rd, color.kind)
        return np.asarray([level_str(x) for x in src], dtype=object)


def apply_filters(
    rd: TableData,
    f: GlobalFilters,
    statuses: dict[str, str],
    var_items: set[str] | None,
) -> tuple[TableData, Obj]:
    """Phase/scope/side/label filter the run's own columns; `var_items` are the item ids that
    match `f.var` (None: no variable filter)."""
    status = np.asarray([statuses.get(str(i), NOT_REVIEWED) for i in rd.item_id], dtype=object)
    m = np.ones(rd.n, dtype=bool)
    if f.phase is not None:
        m &= np.isin(rd.phase, f.phase)
    if f.scope is not None:
        m &= np.isin(rd.scope, f.scope)
    if f.side is not None:
        m &= np.isin(rd.side, f.side)
    if f.label is not None:
        m &= np.isin(rd.label, f.label)
    if f.status is not None:
        m &= np.isin(status, f.status)
    if var_items is not None:
        m &= np.isin(rd.item_id, list(var_items))
    if f.item_ids is not None:
        m &= np.isin(rd.item_id, f.item_ids)
    return rd.take(m), status[m]


@dataclass
class Unit:
    """Unit rows: one per case (or per item when `aggregate = none`)."""

    frame: Frame
    label: int
    scope: str
    phase: str | None
    aggregate: str
    case_id: Obj
    rep: Idx  # observation index of the representative (first-by-priority) item
    members: list[Idx]
    x: F64
    features: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return int(self.case_id.size)

    @property
    def item_ids(self) -> list[list[str]]:
        ids = self.frame.rd.item_id
        return [[str(ids[i]) for i in m] for m in self.members]

    def rep_item_ids(self) -> Obj:
        return self.frame.rd.item_id[self.rep]

    def raw(self, name: str) -> Obj:
        """Variable values per unit row, from the representative item."""
        return self.frame.vars.values(name, self.rep_item_ids())

    def numeric(self, name: str) -> F64:
        """Numeric variable per row; `mean` averages scan-level values over members."""
        if self.aggregate != "mean":
            return as_float(self.raw(name))
        per_obs = as_float(self.frame.vars.values(name, self.frame.rd.item_id))
        with quiet():
            return np.asarray([np.nanmean(per_obs[m]) for m in self.members], dtype=np.float64)

    def levels(self, name: str) -> Obj:
        return np.asarray([level_str(v) for v in self.raw(name)], dtype=object)

    def member_values(self, name: str) -> list[str]:
        """Distinct values of `name` over every contributing item."""
        obs = self.frame.vars.values(name, self.frame.rd.item_id)
        seen: set[str] = set()
        for m in self.members:
            for i in m:
                s = level_str(obs[i])
                if s is not None:
                    seen.add(s)
        return sorted(seen)

    def col(self, feature: str, loc: Sequence[str] = ("body", "feature")) -> F64:
        try:
            j = self.features.index(feature)
        except ValueError:
            raise bad(loc, f"Unknown feature {feature!r}") from None
        return self.x[:, j]


def _most_frequent(values: NDArray[Any], prefer: Any = None) -> Any:
    uniq, counts = np.unique(values.astype(str), return_counts=True)
    if not uniq.size:
        return None
    best = counts.max()
    tied = [u for u, c in zip(uniq, counts, strict=True) if c == best]
    if prefer is not None and str(prefer) in tied:
        return str(prefer)
    return sorted(tied, key=lambda s: (len(s), s))[0]


def _instance_rank(instance: Any) -> tuple[int, int, str]:
    """Producers number instances (1 = first, e.g. the largest lesion); numbers sort as numbers."""
    s = str(instance)
    return (0, int(s), "") if s.isdigit() else (1, 0, s)


def build_unit(frame: Frame, spec: UnitSpec) -> Unit:
    """Filter to one label/scope (and phase), then one row per case; within a case the first
    observation is by phase priority, scan, instance (a scan's lesions are numbered across its
    sides), then side."""
    rd = frame.rd
    if rd.n == 0:
        raise bad(("body", "filters"), "No feature rows match the filters")
    label = spec.label if spec.label is not None else int(_most_frequent(rd.label))
    scope = spec.scope or str(_most_frequent(rd.scope, prefer="complete"))
    m = (rd.label == label) & (rd.scope == scope)
    if spec.phase is not None:
        m &= rd.phase == spec.phase
    idx = np.flatnonzero(m)
    if idx.size == 0:
        raise bad(
            ("body", "unit"), f"No items for label {label}, scope {scope!r}, phase {spec.phase!r}"
        )
    prank = {p: i for i, p in enumerate(frame.priority)}
    order = sorted(
        idx.tolist(),
        key=lambda i: (
            str(rd.case_id[i]),
            prank.get(str(rd.phase[i]), len(prank)),
            str(rd.scan_idx[i]),
            _instance_rank(rd.instance[i]),
            str(rd.side[i]),
        ),
    )
    groups: list[list[int]] = []
    for i in order:
        if spec.aggregate != "none" and groups and rd.case_id[groups[-1][0]] == rd.case_id[i]:
            groups[-1].append(i)
        else:
            groups.append([i])
    keep = 1 if spec.aggregate == "first" else None  # `first`: only the chosen item counts
    members = [np.asarray(g[:keep], dtype=np.intp) for g in groups]
    rep = np.asarray([g[0] for g in groups], dtype=np.intp)
    xf = np.where(np.isfinite(rd.x), rd.x, np.nan)
    if spec.aggregate == "mean":
        with quiet():
            x = np.vstack([np.nanmean(xf[g], axis=0) for g in members])
    else:
        x = xf[rep]
    return Unit(
        frame=frame,
        label=label,
        scope=scope,
        phase=spec.phase,
        aggregate=spec.aggregate,
        case_id=rd.case_id[rep],
        rep=rep,
        members=members,
        x=x,
        features=list(rd.features),
    )
