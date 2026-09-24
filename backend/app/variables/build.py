"""Catalog builder: index items (+ derived defs, external tables, overrides) → catalog + table.

Pure and deterministic (no I/O). One unit per case for case-level variables and one per scan
for scan-level ones (VAR-02); `Column.get` joins either level onto any item of the scan.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np

from app.core.errors import ValidationProblem
from app.ingest.models import Item
from app.variables import schema
from app.variables.models import (
    NUMERIC_TYPES,
    BinDef,
    Catalog,
    DerivedDef,
    DominantDef,
    Excluded,
    ExcludeReason,
    ExternalTable,
    Level,
    RecodeDef,
    Tag,
    VarGroup,
    Variable,
    VariableOverride,
    VarSource,
    VarType,
)
from app.variables.profile import (
    Inference,
    as_date,
    as_number,
    as_text,
    infer_type,
    parse_age_years,
    profile,
)

ScanKey = tuple[str, str]
HIDDEN_TYPES: frozenset[str] = frozenset({"constant", "identifier", "text", "date"})
TIE = "tie"
PATH_SHARE = UID_SHARE = 0.5


@dataclass
class Column:
    """One variable's values as canonical text per unit (case_id or (case_id, scan_idx))."""

    var: Variable
    by_case: dict[str, str | None] = field(default_factory=dict)
    by_scan: dict[ScanKey, str | None] = field(default_factory=dict)

    def get(self, case_id: str, scan_idx: str) -> str | None:
        if self.var.level == "case":
            return self.by_case.get(case_id)
        return self.by_scan.get((case_id, scan_idx))

    def units(self) -> list[str | None]:
        return list(self.by_case.values() if self.var.level == "case" else self.by_scan.values())

    def typed(self, case_id: str, scan_idx: str) -> float | str | None:
        return cast(self.var.type, self.get(case_id, scan_idx))


def cast(vtype: VarType, text: str | None) -> float | str | None:
    """Typed value for the table: numbers for numeric types, ISO strings for dates."""
    if vtype in NUMERIC_TYPES:
        return as_number(text)
    if vtype == "date":
        return as_date(text)
    return text


@dataclass
class ExternalData:
    """A parsed external table: key value → {column: text}."""

    table: ExternalTable
    rows: dict[str, dict[str, str | None]]


@dataclass
class LayerData:
    """A plugin layer as a typed variable (ADR-0020, VAR-12), e.g. `lbl.{table}.{column}`."""

    name: str
    level: Level
    type: VarType
    by_case: dict[str, str | None] = field(default_factory=dict)
    by_scan: dict[ScanKey, str | None] = field(default_factory=dict)


@dataclass
class Built:
    catalog: Catalog
    columns: list[Column]
    # Items in index order with their (case_id, scan_idx) join key.
    items: list[Item]


# -- raw metadata columns ----------------------------------------------------------------------


def _scan_fields(items: Sequence[Item]) -> tuple[dict[ScanKey, dict[str, Any]], list[str]]:
    """One field dict per indexed scan (complete, not excluded upstream) + names in order."""
    scans: dict[ScanKey, dict[str, Any]] = {}
    names: dict[str, None] = {}
    for it in items:
        if it.scope != "complete" or it.status == "excluded_upstream":
            continue
        key = (it.case_id, it.scan_idx)
        if key in scans:
            continue
        fields: dict[str, Any] = {"patient_id": it.patient_id, **it.extra}
        raw = it.extra.get("raw_metadata")
        if isinstance(raw, dict):
            for tag, name in schema.RAW_ALLOWLIST.items():
                if tag in raw:
                    fields[f"raw:{name}"] = raw[tag]
        scans[key] = fields
        names.update(dict.fromkeys(fields))
    return scans, list(names)


def _value_exclusion(texts: Iterable[str | None], blobs: bool) -> ExcludeReason | None:
    if blobs:
        return "blob"
    present = [t for t in texts if t is not None]
    if not present:
        return None
    if sum(bool(schema.UID_VALUE.match(t)) for t in present) >= UID_SHARE * len(present):
        return "uid"
    if sum(bool(schema.ABS_PATH_VALUE.match(t)) for t in present) >= PATH_SHARE * len(present):
        return "path"
    return None


def _level(by_scan: Mapping[ScanKey, str | None]) -> Level:
    seen: dict[str, str | None] = {}
    for (case_id, _), text in by_scan.items():
        if case_id in seen and seen[case_id] != text:
            return "scan"
        seen.setdefault(case_id, text)
    return "case"


def _default_tags(name: str, vtype: VarType) -> list[Tag]:
    tags: list[Tag] = []
    if name in schema.DEFAULT_CONFOUNDERS:
        tags.append("confounder")
    if name in schema.SENSITIVE_FIELDS or vtype == "date":
        tags.append("sensitive")
    return tags


def _make_variable(
    name: str,
    source: VarSource,
    group: VarGroup,
    level: Level,
    units: Sequence[str | None],
    inference: Inference,
    override: VariableOverride | None,
) -> Variable:
    tags = _default_tags(name, inference.type)
    visible = group == "study" and inference.type not in HIDDEN_TYPES and "sensitive" not in tags
    var = Variable(
        name=name,
        source=source,
        type=inference.type,
        inferred_type=inference.type,
        level=level,
        group=group,
        tags=tags,
        visible=visible,
        confidence=round(inference.confidence, 3),
        review=inference.review,
        profile=profile(units),
    )
    return apply_override(var, override)


def apply_override(var: Variable, ov: VariableOverride | None) -> Variable:
    """VAR-03/05: a confirmed type clears the Review badge; tags/visibility replace defaults."""
    if ov is None:
        return var
    upd: dict[str, Any] = {}
    if ov.type is not None:
        upd |= {"type": ov.type, "review": False, "overridden": True}
    if ov.visible is not None:
        upd |= {"visible": ov.visible, "overridden": True}
    if ov.tags is not None:
        upd |= {"tags": list(dict.fromkeys(ov.tags)), "overridden": True}
    return var.model_copy(update=upd)


def _metadata_columns(
    items: Sequence[Item], overrides: Mapping[str, VariableOverride]
) -> tuple[list[Column], list[Excluded]]:
    scans, names = _scan_fields(items)
    columns: list[Column] = []
    excluded: list[Excluded] = []
    for key in names:
        is_raw = key.startswith("raw:")
        name = key.removeprefix("raw:")
        raw_values = [f.get(key) for f in scans.values()]
        blobs = any(isinstance(v, (dict, list)) for v in raw_values)
        texts = [as_text(v) for v in raw_values]
        reason: ExcludeReason | None = None
        if name in schema.CORE_FIELDS:
            reason = "core"
        elif not is_raw:
            reason = schema.name_exclusion(name) or _value_exclusion(texts, blobs)  # type: ignore[assignment]
        if reason is not None:
            excluded.append(Excluded(name=name, reason=reason))
            continue
        if is_raw and any(c.var.name == name for c in columns):
            continue  # a metadata column with the same name wins
        if is_raw and name == "patient_age":
            texts = [as_text(parse_age_years(t)) for t in texts]
        by_scan = dict(zip(scans, texts, strict=True))
        level = _level(by_scan)
        by_case: dict[str, str | None] = {}
        if level == "case":
            for (case_id, _), text in by_scan.items():
                by_case.setdefault(case_id, text)
            by_scan = {}
        units = list(by_case.values()) if level == "case" else texts
        inference = infer_type(units)
        if is_raw and inference.type != "constant":
            forced: VarType = "continuous" if name == "patient_age" else "categorical"
            inference = Inference(forced, 1.0, False)
        group: VarGroup = (
            "acquisition" if schema.is_converter_field(name) and not is_raw else "study"
        )
        source: VarSource = "raw" if is_raw else "metadata"
        var = _make_variable(name, source, group, level, units, inference, overrides.get(name))
        columns.append(Column(var, by_case, by_scan))
    return columns, excluded


# -- derived (VAR-06) --------------------------------------------------------------------------


def _need(columns: Mapping[str, Column], name: str, what: str) -> Column:
    col = columns.get(name)
    if col is None:
        raise ValidationProblem(
            f"Unknown source variable {name!r}", errors=[{"loc": [what], "msg": "unknown variable"}]
        )
    return col


def _bin_thresholds(d: BinDef, col: Column) -> list[float]:
    if (d.thresholds is None) == (d.quantiles is None):
        raise ValidationProblem(
            "Give thresholds or quantiles", errors=[{"loc": ["thresholds"], "msg": "one required"}]
        )
    if d.thresholds is not None:
        t = list(d.thresholds)
    else:
        qs = d.quantiles or []
        if not qs or any(not 0 < q < 1 for q in qs):
            raise ValidationProblem(
                "Quantiles must lie in (0, 1)", errors=[{"loc": ["quantiles"], "msg": "range"}]
            )
        nums = [x for x in (as_number(u) for u in col.units()) if x is not None]
        if not nums:
            raise ValidationProblem(
                "Source has no numeric values", errors=[{"loc": ["source"], "msg": "empty"}]
            )
        t = [float(v) for v in np.quantile(np.asarray(nums, dtype=float), sorted(qs))]
        t = sorted(set(t))
    if not t or any(b <= a for a, b in pairwise(t)):
        raise ValidationProblem(
            "Thresholds must be strictly increasing",
            errors=[{"loc": ["thresholds"], "msg": "not increasing"}],
        )
    return t


def _fmt(x: float) -> str:
    return f"{x:g}"


def bin_labels(d: BinDef, thresholds: Sequence[float]) -> list[str]:
    if d.labels is not None:
        if len(d.labels) != len(thresholds) + 1 or len(set(d.labels)) != len(d.labels):
            raise ValidationProblem(
                f"Need {len(thresholds) + 1} distinct labels",
                errors=[{"loc": ["labels"], "msg": "wrong count or duplicates"}],
            )
        return list(d.labels)
    edges = [_fmt(t) for t in thresholds]
    mids = [f"{a}-{b}" for a, b in pairwise(edges)]
    return [f"<{edges[0]}", *mids, f">={edges[-1]}"]


def _bin_value(x: float | None, thresholds: Sequence[float], labels: Sequence[str]) -> str | None:
    if x is None:
        return None
    return labels[int(np.searchsorted(np.asarray(thresholds), x, side="right"))]


def _derive(d: DerivedDef, columns: Mapping[str, Column]) -> Column:
    if d.name in columns or d.name in schema.RESERVED_NAMES:
        raise ValidationProblem(
            f"Variable {d.name!r} already exists", errors=[{"loc": ["name"], "msg": "taken"}]
        )
    if isinstance(d, BinDef):
        src = _need(columns, d.source, "source")
        if src.var.type not in NUMERIC_TYPES:
            raise ValidationProblem(
                "bin needs a numeric source", errors=[{"loc": ["source"], "msg": "not numeric"}]
            )
        th = _bin_thresholds(d, src)
        labels = bin_labels(d, th)
        level: Level = src.var.level

        def fn(case_id: str, scan_idx: str) -> str | None:
            return _bin_value(as_number(src.get(case_id, scan_idx)), th, labels)

        srcs = [src]
    elif isinstance(d, RecodeDef):
        src = _need(columns, d.source, "source")
        if src.var.type == "continuous":
            raise ValidationProblem(
                "recode needs a categorical source; use bin for continuous variables",
                errors=[{"loc": ["source"], "msg": "continuous"}],
            )
        mapping = dict(d.map)
        level = src.var.level

        def fn(case_id: str, scan_idx: str) -> str | None:
            v = src.get(case_id, scan_idx)
            return None if v is None else mapping.get(v, v)

        srcs = [src]
    else:
        assert isinstance(d, DominantDef)
        srcs = [_need(columns, s, "sources") for s in d.sources]
        if len({s.var.name for s in srcs}) != len(srcs):
            raise ValidationProblem(
                "Sources must be distinct", errors=[{"loc": ["sources"], "msg": "duplicates"}]
            )
        if any(s.var.type not in NUMERIC_TYPES for s in srcs):
            raise ValidationProblem(
                "dominant needs numeric sources",
                errors=[{"loc": ["sources"], "msg": "not numeric"}],
            )
        level = "case" if all(s.var.level == "case" for s in srcs) else "scan"

        def fn(case_id: str, scan_idx: str) -> str | None:
            vals = [as_number(s.get(case_id, scan_idx)) for s in srcs]
            if any(v is None for v in vals):
                return None
            top = max(v for v in vals if v is not None)
            winners = [s.var.name for s, v in zip(srcs, vals, strict=True) if v == top]
            return winners[0] if len(winners) == 1 else TIE

    scan_keys = _scan_keys(srcs)
    by_case: dict[str, str | None] = {}
    by_scan: dict[ScanKey, str | None] = {}
    if level == "case":
        first_scan: dict[str, str] = {}
        for c, si in scan_keys:
            first_scan.setdefault(c, si)
        for s in srcs:
            for c in s.by_case:
                first_scan.setdefault(c, "")
        by_case = {c: fn(c, si) for c, si in first_scan.items()}
    else:
        by_scan = {k: fn(*k) for k in scan_keys}
    units = list(by_case.values()) if level == "case" else list(by_scan.values())
    inference = infer_type(units)
    vtype: VarType = "constant" if inference.type == "constant" else "categorical"
    var = Variable(
        name=d.name,
        source="derived",
        type=vtype,
        inferred_type=vtype,
        level=level,
        group="study",
        tags=[],
        visible=True,
        confidence=1.0,
        review=False,
        profile=profile(units),
    )
    return Column(var, by_case, by_scan)


def _scan_keys(cols: Sequence[Column]) -> list[ScanKey]:
    keys: dict[ScanKey, None] = {}
    for c in cols:
        keys.update(dict.fromkeys(c.by_scan))
    if not keys:
        for c in cols:
            keys.update(dict.fromkeys((case_id, "") for case_id in c.by_case))
    return list(keys)


# -- external (VAR-07) -------------------------------------------------------------------------


def _external_columns(
    ext: ExternalData,
    items: Sequence[Item],
    taken: set[str],
    overrides: Mapping[str, VariableOverride],
) -> tuple[list[Column], list[str]]:
    by_key: dict[str, list[str]] = {}
    for it in items:
        if it.status == "excluded_upstream":
            continue
        k = it.case_id if ext.table.key == "case_id" else it.patient_id
        if k:
            by_key.setdefault(k, [])
            if it.case_id not in by_key[k]:
                by_key[k].append(it.case_id)
    cases = list(dict.fromkeys(c for cs in by_key.values() for c in cs))
    out: list[Column] = []
    conflicts: list[str] = []
    for name in ext.table.columns:
        if name in taken or name in schema.RESERVED_NAMES:
            conflicts.append(name)
            continue
        by_case: dict[str, str | None] = dict.fromkeys(cases)
        for key, row in ext.rows.items():
            for case_id in by_key.get(key, []):
                by_case[case_id] = row.get(name)
        units = list(by_case.values())
        var = _make_variable(
            name, "external", "study", "case", units, infer_type(units), overrides.get(name)
        )
        out.append(Column(var, by_case))
        taken.add(name)
    return out, conflicts


def match_report(ext: ExternalData, items: Sequence[Item]) -> tuple[int, list[str]]:
    """(matched key count, unmatched keys) for an external table against the index."""
    keys: set[str] = set()
    for it in items:
        k = it.case_id if ext.table.key == "case_id" else it.patient_id
        if k:
            keys.add(k)
    matched = [k for k in ext.rows if k in keys]
    return len(matched), [k for k in ext.rows if k not in keys]


# -- entry point -------------------------------------------------------------------------------


def build(
    items: Sequence[Item],
    *,
    overrides: Mapping[str, VariableOverride] | None = None,
    derived: Sequence[DerivedDef] = (),
    external: Sequence[ExternalData] = (),
    layers: Sequence[LayerData] = (),
    strict: bool = False,
) -> tuple[Built, dict[str, list[str]]]:
    """Build the catalog. Returns it with `{"conflicts": [...], "derived_errors": [...]}`.

    `strict=True` (API writes) raises ValidationProblem on the first invalid derived definition;
    otherwise it is skipped and reported (a later re-import may drop its source).
    """
    ov = dict(overrides or {})
    cols, excluded = _metadata_columns(items, ov)
    by_name: dict[str, Column] = {c.var.name: c for c in cols}
    conflicts: list[str] = []
    for ext in external:
        new, conf = _external_columns(ext, items, set(by_name), ov)
        conflicts += conf
        for c in new:
            by_name[c.var.name] = c
            cols.append(c)
    for ld in layers:  # VAR-12: the layer's own type, no inference
        units = list(ld.by_case.values() if ld.level == "case" else ld.by_scan.values())
        var = _make_variable(ld.name, "layer", "study", ld.level, units,
                             Inference(ld.type, 1.0, False), ov.get(ld.name))  # fmt: skip
        col = Column(var, dict(ld.by_case), dict(ld.by_scan))
        by_name[ld.name] = col
        cols.append(col)
    derived_errors: list[str] = []
    for d in derived:
        try:
            c = _derive(d, by_name)
        except ValidationProblem as exc:
            if strict:
                raise
            derived_errors.append(f"{d.name}: {exc.detail}")
            continue
        c.var = apply_override(c.var, ov.get(d.name))
        by_name[c.var.name] = c
        cols.append(c)
    live_cases = {i.case_id for i in items if i.status != "excluded_upstream"}
    catalog = Catalog(
        n_items=len(items),
        n_cases=len(live_cases),
        variables=[c.var for c in cols],
        excluded=excluded,
        derived=list(derived),
        external=[e.table for e in external],
        overrides=ov,
    )
    return Built(catalog, cols, list(items)), {
        "conflicts": conflicts,
        "derived_errors": derived_errors,
    }
