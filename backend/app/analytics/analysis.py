"""Guided analyses on a unit of analysis (ANA-02..07). Shared by API-39 and the
group-comparison / association / balance views (API-38)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from app.analytics import stats as st
from app.analytics.data import (
    CONTINUOUS_TYPES,
    GROUP_TYPES,
    Obj,
    Unit,
    bad,
)
from app.analytics.models import (
    Contingency,
    ContingencyCell,
    DescriptiveRow,
    GroupInfo,
    ResultRow,
    TestChoice,
    TestName,
    TestOverride,
)
from app.analytics.stats import F64, Outcome, num
from app.variables.models import Variable

ALL = "all"
MAX_CELL_IDS = 200

# Question → (default test, alternative) per variable shape (ANALYSIS.md §Tests).
TESTS: dict[str, tuple[TestName, TestName]] = {
    "compare2": ("welch_t", "mann_whitney"),
    "compare3": ("welch_anova", "kruskal_wallis"),
    "association": ("spearman", "pearson"),
    "balance": ("chi2", "fisher"),
}


def check_type(v: Variable, allowed: frozenset[str], loc: Sequence[str], what: str) -> None:
    """ANA-02: only question types valid for the variable type. Unconfirmed
    numeric-discrete variables must be confirmed first (VAR-03)."""
    if v.type in allowed:
        return
    if v.type == "numeric-discrete":
        raise bad(
            loc,
            f"{v.name!r} is numeric-discrete (unconfirmed); confirm it as categorical or "
            f"continuous first (PATCH /projects/{{pid}}/variables/{v.name})",
        )
    raise bad(
        loc, f"{v.name!r} is {v.type}; {what} needs a {' or '.join(sorted(allowed))} variable"
    )


def level_order(levels: Sequence[str]) -> list[str]:
    """Numeric-looking levels sort numerically, others alphabetically."""
    uniq = sorted(set(levels))
    try:
        return sorted(uniq, key=float)
    except ValueError:
        return uniq


def result_row(feature: str | None, o: Outcome, q: float = math.nan) -> ResultRow:
    return ResultRow(
        feature=feature,
        test=o.test,
        reason=o.reason,
        statistic=num(o.statistic),
        p=num(o.p),
        q=num(q),
        effect=num(o.effect),
        effect_name=o.effect_name,
        n=o.n,
        groups=o.groups,
    )


def sort_rows(rows: list[ResultRow]) -> list[ResultRow]:
    """ANA-05: by q, then |effect| (descending); untested rows last."""
    return sorted(
        rows,
        key=lambda r: (
            math.inf if r.q is None else r.q,
            -abs(r.effect) if r.effect is not None else 0.0,
            r.feature or "",
        ),
    )


def desc_row(feature: str, group: str, values: F64, excluded: bool = False) -> DescriptiveRow:
    d = st.describe(values)
    return DescriptiveRow(
        feature=feature,
        group=group,
        n=d.n,
        missing=d.missing,
        median=num(d.median),
        q1=num(d.q1),
        q3=num(d.q3),
        iqr=num(d.q3 - d.q1),
        mean=num(d.mean),
        sd=num(d.sd),
        excluded=excluded,
    )


@dataclass
class Computed:
    """One question's outcome over a unit (not yet persisted)."""

    choice: TestChoice
    groups: list[GroupInfo] = field(default_factory=list)
    results: list[ResultRow] = field(default_factory=list)
    descriptives: list[DescriptiveRow] = field(default_factory=list)
    outcomes: dict[str, Outcome] = field(default_factory=dict)
    row_levels: Obj | None = None  # per unit row: group level (compare/balance)
    row_x: F64 | None = None  # per unit row: variable value (association)
    n_variable_missing: int = 0
    balance: Contingency | None = None


def _choice(
    kind: str, outcomes: Sequence[Outcome], override: TestOverride, global_reason: str | None
) -> TestChoice:
    default, alt = TESTS[kind]
    tested = [o for o in outcomes if o.test is not None]
    n_alt = sum(o.alternative for o in tested)
    n_def = len(tested) - n_alt
    if override != "auto":
        reason = f"{alt if override == 'alternative' else default} forced by the user"
    elif global_reason is not None:
        reason = global_reason
    elif n_alt == 0:
        reason = f"{default} for all features ({tested[0].reason})" if tested else "no test"
    else:
        reason = (
            f"{alt} for {n_alt} of {len(tested)} features (Shapiro-Wilk p < 0.05), "
            f"{default} for the rest"
        )
    return TestChoice(
        default_test=default,
        alternative_test=alt,
        override=override,
        n_default=n_def,
        n_alternative=n_alt,
        reason=reason,
    )


def _finalize(features: Sequence[str], outcomes: list[Outcome]) -> list[ResultRow]:
    q = st.bh([o.p for o in outcomes])
    rows = [result_row(f, o, qq) for f, o, qq in zip(features, outcomes, q, strict=True)]
    return sort_rows(rows)


def compare(unit: Unit, v: Variable, override: TestOverride) -> Computed:
    """Compare groups (ANA-04..07). Groups with n < 5 stay in descriptives only (ANA-06)."""
    check_type(v, GROUP_TYPES, ("body", "variable"), "Compare groups")
    levels = unit.levels(v.name)
    valid = np.asarray([lv is not None for lv in levels], dtype=bool)
    order = level_order([str(lv) for lv in levels[valid]])
    counts = {lv: int((levels == lv).sum()) for lv in order}
    groups = [GroupInfo(level=lv, n=counts[lv], excluded=counts[lv] < st.MIN_N) for lv in order]
    eligible = [g.level for g in groups if not g.excluded]
    if len(eligible) < 2:
        raise bad(
            ("body", "variable"),
            f"{v.name!r} has fewer than two groups with n ≥ {st.MIN_N} in the unit "
            f"({', '.join(f'{g.level}: {g.n}' for g in groups) or 'no values'})",
        )
    kind = "compare2" if len(eligible) == 2 else "compare3"
    masks = [levels == lv for lv in order]
    outcomes: list[Outcome] = []
    descriptives: list[DescriptiveRow] = []
    for j, f in enumerate(unit.features):
        col = unit.x[:, j]
        arrays = [st.finite(col[m]) for m in masks]
        outcomes.append(st.compare(order, arrays, override))
        descriptives += [
            desc_row(f, g.level, col[m], g.excluded) for g, m in zip(groups, masks, strict=True)
        ]
    sizes = [counts[lv] for lv in eligible]
    global_reason = (
        f"smallest group n = {min(sizes)} < {st.ALT_N}"
        if override == "auto" and min(sizes) < st.ALT_N
        else None
    )
    return Computed(
        choice=_choice(kind, outcomes, override, global_reason),
        groups=groups,
        results=_finalize(unit.features, outcomes),
        descriptives=descriptives,
        outcomes=dict(zip(unit.features, outcomes, strict=True)),
        row_levels=levels,
        n_variable_missing=int((~valid).sum()),
    )


def associate(unit: Unit, v: Variable, override: TestOverride) -> Computed:
    """Association with a continuous variable: Spearman rho (default) / Pearson r."""
    check_type(v, CONTINUOUS_TYPES, ("body", "variable"), "Association")
    x = unit.numeric(v.name)
    outcomes = [st.associate(x, unit.x[:, j], override) for j in range(len(unit.features))]
    descriptives = [desc_row(f, ALL, unit.x[:, j]) for j, f in enumerate(unit.features)]
    descriptives.append(desc_row(v.name, ALL, x))
    return Computed(
        choice=_choice("association", outcomes, override, None),
        results=_finalize(unit.features, outcomes),
        descriptives=descriptives,
        outcomes=dict(zip(unit.features, outcomes, strict=True)),
        row_x=x,
        n_variable_missing=int((~np.isfinite(x)).sum()),
    )


def explore(unit: Unit) -> Computed:
    """Explore: no test (ANALYSIS.md §Tests); descriptives per feature."""
    return Computed(
        choice=TestChoice(
            default_test=None,
            alternative_test=None,
            override="auto",
            n_default=0,
            n_alternative=0,
            reason="Explore: no test; use the distribution, correlation, "
            "embedding and outlier views",
        ),
        descriptives=[desc_row(f, ALL, unit.x[:, j]) for j, f in enumerate(unit.features)],
    )


def contingency(
    unit: Unit, row_levels: Obj, col_levels: Obj, override: TestOverride
) -> tuple[list[str], list[str], list[str], list[str], np.ndarray, Outcome]:
    """Rows/cols with n ≥ 5 (ANA-06) → table + test; excluded levels listed separately."""
    ok = np.asarray(
        [a is not None and b is not None for a, b in zip(row_levels, col_levels, strict=True)]
    )
    rl, cl = row_levels[ok], col_levels[ok]
    rows_all = level_order([str(x) for x in rl])
    cols_all = level_order([str(x) for x in cl])
    rows = [r for r in rows_all if (rl == r).sum() >= st.MIN_N]
    cols = [c for c in cols_all if (cl == c).sum() >= st.MIN_N]
    table = np.asarray(
        [[int(((rl == r) & (cl == c)).sum()) for c in cols] for r in rows], dtype=np.int64
    ).reshape(len(rows), len(cols))
    out = st.contingency_test(table, override)
    ex_r = [r for r in rows_all if r not in rows]
    ex_c = [c for c in cols_all if c not in cols]
    return rows, cols, ex_r, ex_c, table, out


def balance(unit: Unit, v: Variable, other: Variable, override: TestOverride) -> Computed:
    """Balance check: variable x other (both categorical), χ² / Fisher, Cramér's V."""
    check_type(v, GROUP_TYPES, ("body", "variable"), "Balance check")
    check_type(other, GROUP_TYPES, ("body", "confounder"), "Balance check")
    if v.name == other.name:
        raise bad(("body", "confounder"), "Balance check needs two different variables")
    a, b = unit.levels(v.name), unit.levels(other.name)
    rows, cols, ex_r, ex_c, table, out = contingency(unit, a, b, override)
    if len(rows) < 2 or len(cols) < 2:
        raise bad(
            ("body", "variable"),
            f"Balance check needs ≥ 2 levels with n ≥ {st.MIN_N} on each side "
            f"({v.name}: {len(rows)}, {other.name}: {len(cols)})",
        )
    expected = None
    if table.size:
        with st.quiet():
            expected = np.outer(table.sum(1), table.sum(0)) / table.sum()
    rep = unit.rep_item_ids()
    cells: list[ContingencyCell] = []
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            m = (a == r) & (b == c)
            cells.append(
                ContingencyCell(
                    row=r,
                    col=c,
                    n=int(table[i, j]),
                    expected=num(expected[i, j]) if expected is not None else None,
                    item_ids=[str(x) for x in rep[m][:MAX_CELL_IDS]],
                    case_ids=[str(x) for x in unit.case_id[m][:MAX_CELL_IDS]],
                )
            )
    row = result_row(f"{v.name} x {other.name}", out, out.p)
    groups = [
        GroupInfo(level=str(lv), n=int((a == lv).sum()), excluded=str(lv) in ex_r)
        for lv in level_order([str(x) for x in a if x is not None])
    ]
    missing = int(sum(1 for x, y in zip(a, b, strict=True) if x is None or y is None))
    table_model = Contingency(
        variable=v.name,
        other=other.name,
        rows=rows,
        cols=cols,
        cells=cells,
        excluded_rows=ex_r,
        excluded_cols=ex_c,
        result=row,
    )
    return Computed(
        choice=_choice("balance", [out], override, out.reason if override == "auto" else None),
        groups=groups,
        results=[row],
        row_levels=a,
        n_variable_missing=missing,
        balance=table_model,
    )
