"""Run inputs for analytics: `features.parquet` → wide observation matrix, DB-02 filters,
variable columns and the ANA-03 unit of analysis.

Reads files only (RADIOMICS.md §Output schema); never imports the radiomics service.
An observation is one `(item_id, label)` pair; a feature key is
`{image_type}_{feature_class}_{feature}` (PyRadiomics naming, e.g. `original_shape_MeshVolume`).
"""

from __future__ import annotations

import math
import re
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from numpy.typing import NDArray

from app.analytics.models import ColorBy, GlobalFilters, UnitSpec
from app.analytics.stats import F64, quiet
from app.core.errors import NotFound, ValidationProblem
from app.core.fsio import iter_jsonl, read_json
from app.curation import state as curation_state
from app.variables.models import Catalog, Variable

RUNS_DIR = Path("radiomics") / "runs"
FEATURES = "features.parquet"
RUN_JSON = "run.json"
ERRORS = "errors.jsonl"
VOLUME_KEY = "original_shape_MeshVolume"  # DASHBOARD.md Feature vs volume
NOT_REVIEWED = "not_reviewed"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Types usable as groups. `numeric-discrete` must be confirmed first (VAR-03), except as a
# color/confounder level where no test depends on the type.
GROUP_TYPES = frozenset({"categorical"})
LEVEL_TYPES = frozenset({"categorical", "numeric-discrete"})
CONTINUOUS_TYPES = frozenset({"continuous"})
MODALITY_VAR = "modality"  # converter field (VAR-05 default confounder), not a study field

Obj = NDArray[np.object_]
Bool = NDArray[np.bool_]
Idx = NDArray[np.intp]


def bad(loc: Sequence[str], msg: str) -> ValidationProblem:
    return ValidationProblem(msg, errors=[{"loc": list(loc), "msg": msg}])


# -- run files --------------------------------------------------------------------------------


def run_dir(project_dir: Path, run_id: str) -> Path:
    """`radiomics/runs/{rid}/` with `run.json` + `features.parquet`, else `not-found`."""
    if not RUN_ID_RE.match(run_id):
        raise NotFound(f"Run {run_id!r} not found")
    d = project_dir / RUNS_DIR / run_id
    if not (d / RUN_JSON).is_file() or not (d / FEATURES).is_file():
        raise NotFound(f"Run {run_id!r} not found (or has no features yet)")
    return d


def read_run(d: Path) -> dict[str, Any]:
    raw = read_json(d / RUN_JSON)
    return raw if isinstance(raw, dict) else {}


def read_errors(d: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(d / ERRORS))


@dataclass
class RunData:
    """Wide observation matrix. `x[i, j]` is NaN where the feature is absent (`present`)."""

    run_id: str
    features: list[str]
    feature_class: list[str]
    item_id: Obj
    case_id: Obj
    scan_idx: Obj
    scope: Obj
    side: Obj
    phase: Obj
    label: NDArray[np.int64]
    x: F64
    present: Bool

    @property
    def n(self) -> int:
        return int(self.item_id.size)

    def take(self, rows: Idx | Bool) -> RunData:
        return RunData(
            self.run_id,
            self.features,
            self.feature_class,
            self.item_id[rows],
            self.case_id[rows],
            self.scan_idx[rows],
            self.scope[rows],
            self.side[rows],
            self.phase[rows],
            self.label[rows],
            self.x[rows],
            self.present[rows],
        )

    def cols(self, keep: Sequence[int]) -> RunData:
        k = list(keep)
        return RunData(
            self.run_id,
            [self.features[i] for i in k],
            [self.feature_class[i] for i in k],
            self.item_id,
            self.case_id,
            self.scan_idx,
            self.scope,
            self.side,
            self.phase,
            self.label,
            self.x[:, k],
            self.present[:, k],
        )

    def col(self, feature: str, loc: Sequence[str] = ("body", "feature")) -> F64:
        try:
            j = self.features.index(feature)
        except ValueError:
            raise bad(loc, f"Unknown feature {feature!r} in run {self.run_id}") from None
        out: F64 = self.x[:, j]
        return out


_SQL = """
SELECT item_id, case_id, scan_idx, scope, side, phase, CAST(label AS BIGINT) AS label,
       image_type || '_' || feature_class || '_' || feature AS key, feature_class,
       CAST(value AS DOUBLE) AS value
FROM read_parquet(?)
"""

_cache: OrderedDict[tuple[str, int, int], RunData] = OrderedDict()
_cache_lock = threading.Lock()
CACHE_MAX = 4


def _obj(a: pa.Array | pa.ChunkedArray) -> Obj:
    return np.asarray(a.to_pylist(), dtype=object)


def load_run(d: Path, run_id: str) -> RunData:
    """Pivot `features.parquet` (long) into `RunData`; LRU-cached by file identity."""
    path = d / FEATURES
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    with duckdb.connect() as con:
        t: pa.Table = con.execute(_SQL, [str(path)]).to_arrow_table()
    rd = _pivot(t, run_id)
    with _cache_lock:
        _cache[key] = rd
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return rd


def _pivot(t: pa.Table, run_id: str) -> RunData:
    if t.num_rows == 0:
        e = np.asarray([], dtype=object)
        return RunData(
            run_id,
            [],
            [],
            e,
            e,
            e,
            e,
            e,
            e,
            np.asarray([], dtype=np.int64),
            np.zeros((0, 0)),
            np.zeros((0, 0), dtype=bool),
        )
    obs_key = pc.binary_join_element_wise(
        t["item_id"], pc.cast(t["label"], pa.string()), "\x1f"
    ).combine_chunks()
    obs_enc = pc.dictionary_encode(obs_key)
    obs_idx = np.asarray(obs_enc.indices.to_numpy(zero_copy_only=False), dtype=np.intp)
    keys = t["key"].combine_chunks()
    key_enc = pc.dictionary_encode(keys)
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
        return _obj(t[name].take(pa.array(first)))

    fclass = t["feature_class"].take(pa.array(first_f)).to_pylist()
    return RunData(
        run_id=run_id,
        features=[key_names[j] for j in order],
        feature_class=[str(c) for c in fclass],
        item_id=rows("item_id"),
        case_id=rows("case_id"),
        scan_idx=rows("scan_idx"),
        scope=rows("scope"),
        side=rows("side"),
        phase=rows("phase"),
        label=np.asarray(t["label"].take(pa.array(first)).to_pylist(), dtype=np.int64),
        x=x,
        present=present,
    )


def select_features(
    rd: RunData, features: Sequence[str] | None, feature_class: Sequence[str] | None
) -> RunData:
    if features is not None:
        known = set(rd.features)
        unknown = [f for f in features if f not in known]
        if unknown:
            raise bad(("body", "features"), f"Unknown features: {', '.join(unknown[:10])}")
        want = set(features)
        rd = rd.cols([j for j, f in enumerate(rd.features) if f in want])
    if feature_class is not None:
        cls = set(feature_class)
        rd = rd.cols([j for j, c in enumerate(rd.feature_class) if c in cls])
    return rd


# -- curation + variables -----------------------------------------------------------------------


def item_statuses(project_dir: Path) -> dict[str, str]:
    """CUR-08 status per item; `{}` until the curation reducer exists (lane contract)."""
    try:
        return curation_state.item_statuses(project_dir)
    except NotImplementedError:
        return {}


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
        col = self.columns.get(name)
        if col is None:
            return np.full(item_ids.size, None, dtype=object)
        out = np.full(item_ids.size, None, dtype=object)
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
        if not math.isfinite(v):
            return None
        return f"{v:g}"
    s = str(v)
    return s if s != "" else None


@dataclass
class Frame:
    """A filtered run joined with statuses and variables (one request's inputs)."""

    rd: RunData
    status: Obj
    vars: VarTable
    priority: list[str]
    n_total: int = 0

    def levels(self, color: ColorBy | None, loc: Sequence[str]) -> Obj:
        """DB-07 color/split levels per observation (None when no color)."""
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
    rd: RunData,
    f: GlobalFilters,
    statuses: dict[str, str],
    var_items: set[str] | None,
) -> tuple[RunData, Obj]:
    """DB-02: phase/scope/side/label on the run's own columns; `var` via VAR-10 item ids;
    curation `status`; DB-04 `item_ids`."""
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


# -- ANA-03 unit --------------------------------------------------------------------------------


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
        out: Obj = self.frame.rd.item_id[self.rep]
        return out

    def raw(self, name: str) -> Obj:
        """Variable values per unit row, from the representative item."""
        vals: Obj = self.frame.vars.values(name, self.rep_item_ids())
        return vals

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
        """Distinct values of `name` over every contributing item (REC-MODALITY)."""
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
        out: F64 = self.x[:, j]
        return out


def _most_frequent(values: NDArray[Any], prefer: Any = None) -> Any:
    uniq, counts = np.unique(values.astype(str), return_counts=True)
    if not uniq.size:
        return None
    best = counts.max()
    tied = [u for u, c in zip(uniq, counts, strict=True) if c == best]
    if prefer is not None and str(prefer) in tied:
        return str(prefer)
    return sorted(tied, key=lambda s: (len(s), s))[0]


def build_unit(frame: Frame, spec: UnitSpec) -> Unit:
    """ANA-03: filter to one label/scope (and phase), then one row per case."""
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
