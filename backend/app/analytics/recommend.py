"""ANA-08 recommendation rules (ANALYSIS.md §Recommendation rules).

Each rule returns at most one `Recommendation` whose `view` + `params` open the dashboard
view that shows the problem (DB-09).
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from app.analytics import stats as st
from app.analytics.analysis import Computed, contingency
from app.analytics.data import CONTINUOUS_TYPES, LEVEL_TYPES, MODALITY_VAR, VOLUME_KEY, Unit
from app.analytics.models import AnalysisSpec, Recommendation, ViewSlug
from app.variables.models import Catalog

SMALL_N = 10
IMBALANCE_RATIO = 4.0
MISSING_SHARE = 0.30
Q_SIG = 0.05
Q_SIGNAL = 0.10
VOLUME_RHO = 0.8
REDUNDANT_RHO = 0.9
CONFOUNDED_SHARE = 0.20
# REC-COMPOSITIONAL: ≥ 80 % of complete rows have a sum within 2 % of the median sum.
COMPOSITIONAL_TOL = 0.02
COMPOSITIONAL_SHARE = 0.80
COMPOSITIONAL_MAX_VARS = 40
MAX_REDUNDANT_FEATURES = 2000
LIST_CAP = 20

HOME: dict[str, ViewSlug] = {
    "explore": "run-overview",
    "compare": "group-comparison",
    "association": "association",
    "balance": "balance",
}


@dataclass
class Ctx:
    spec: AnalysisSpec
    unit: Unit
    catalog: Catalog
    computed: Computed

    @property
    def home(self) -> ViewSlug:
        return HOME[self.spec.question]

    @property
    def top_feature(self) -> str | None:
        rows = [r for r in self.computed.results if r.feature in self.unit.features]
        if rows:
            return rows[0].feature
        return self.unit.features[0] if self.unit.features else None

    def significant(self, q: float = Q_SIG) -> list[str]:
        return [
            r.feature
            for r in self.computed.results
            if r.q is not None and r.q < q and r.feature in self.unit.features
        ]


def _names(xs: Sequence[str]) -> str:
    head = ", ".join(xs[:5])
    return head + (f" (+{len(xs) - 5})" if len(xs) > 5 else "")


def rec(code: str, message: str, view: ViewSlug, **params: object) -> Recommendation:
    return Recommendation.model_validate(
        {"code": code, "message": message, "view": view, "params": params}
    )


# -- rules --------------------------------------------------------------------------------------


def small_n(c: Ctx) -> Recommendation | None:
    """REC-SMALL-N: any group n < 10 (the whole unit for Association/Explore)."""
    if c.computed.groups:
        small = [f"{g.level} (n = {g.n})" for g in c.computed.groups if g.n < SMALL_N]
    else:
        n = c.unit.n - c.computed.n_variable_missing
        small = [f"all (n = {n})"] if n < SMALL_N else []
    if not small:
        return None
    return rec(
        "REC-SMALL-N",
        f"Small groups: {_names(small)}; results unstable; treat as exploratory.",
        c.home,
        variable=c.spec.variable,
    )


def imbalance(c: Ctx) -> Recommendation | None:
    """REC-IMBALANCE: largest / smallest group > 4."""
    sizes = [g.n for g in c.computed.groups if g.n > 0]
    if len(sizes) < 2 or max(sizes) / min(sizes) <= IMBALANCE_RATIO:
        return None
    return rec(
        "REC-IMBALANCE",
        f"Groups are imbalanced (largest/smallest = {max(sizes)}/{min(sizes)}); prefer "
        "nonparametric tests and report n.",
        c.home,
        variable=c.spec.variable,
    )


def missing(c: Ctx) -> Recommendation | None:
    """REC-MISSING: the variable is missing for > 30 % of unit rows."""
    total = c.unit.n
    miss = c.computed.n_variable_missing
    if c.spec.variable is None or total == 0 or miss / total <= MISSING_SHARE:
        return None
    what = "cases" if c.spec.unit.aggregate != "none" else "rows"
    return rec(
        "REC-MISSING",
        f"Analysis uses only {total - miss} of {total} {what}; check whether missingness is "
        "random.",
        c.home,
        variable=c.spec.variable,
    )


def _confounders(c: Ctx) -> list[str]:
    names = [
        v.name
        for v in c.catalog.variables
        if "confounder" in v.tags and v.type in LEVEL_TYPES and v.name in c.unit.frame.vars.columns
    ]
    if c.spec.confounder and c.spec.confounder not in names:
        names.append(c.spec.confounder)
    return [n for n in names if n != c.spec.variable]


def confounder(c: Ctx) -> Recommendation | None:
    """REC-CONFOUNDER: a confounder is associated with the grouping (balance q < 0.05) or
    with > 20 % of the significant features."""
    q = c.spec.question
    if q == "balance":
        row = c.computed.results[0] if c.computed.results else None
        if row is None or row.q is None or row.q >= Q_SIG:
            return None
        return rec(
            "REC-CONFOUNDER",
            f"Possible scanner/protocol effect: {c.spec.variable} is associated with "
            f"{c.spec.confounder} (q = {row.q:.3g}); stratify, or harmonize outside the app "
            "(e.g. ComBat).",
            "balance",
            variable=c.spec.variable,
            other=c.spec.confounder,
        )
    if q not in ("compare", "association"):
        return None
    names = _confounders(c)
    ps: list[float] = []
    tested: list[str] = []
    for name in names:
        lv = c.unit.levels(name)
        if q == "compare" and c.computed.row_levels is not None:
            *_, out = contingency(c.unit, c.computed.row_levels, lv, "auto")
        elif c.computed.row_x is not None:
            order = sorted({str(x) for x in lv if x is not None})
            x = c.computed.row_x
            out = st.compare(order, [st.finite(x[lv == o]) for o in order], "auto")
        else:
            continue
        if out.test is not None:
            ps.append(out.p)
            tested.append(name)
    qs = st.bh(ps)
    hit = [n for n, qq in zip(tested, qs, strict=True) if qq < Q_SIG]
    if hit:
        return rec(
            "REC-CONFOUNDER",
            f"Possible scanner/protocol effect: {_names(hit)} associated with "
            f"{c.spec.variable}; stratify, or harmonize outside the app (e.g. ComBat).",
            "balance",
            variable=c.spec.variable,
            other=hit[0],
        )
    sig = c.significant()
    if not sig:
        return None
    for name in names:
        lv = c.unit.levels(name)
        order = sorted({str(x) for x in lv if x is not None})
        n_assoc = 0
        for f in sig:
            col = c.unit.col(f)
            out = st.compare(order, [st.finite(col[lv == o]) for o in order], "auto")
            n_assoc += out.test is not None and out.p < Q_SIG
        if n_assoc / len(sig) > CONFOUNDED_SHARE:
            return rec(
                "REC-CONFOUNDER",
                f"Possible scanner/protocol effect: {name} is associated with {n_assoc} of "
                f"{len(sig)} significant features; stratify, or harmonize outside the app "
                "(e.g. ComBat).",
                "feature-distribution",
                feature=sig[0],
                split=name,
            )
    return None


def volume(c: Ctx) -> Recommendation | None:
    """REC-VOLUME: a significant feature has |rho| > 0.8 with shape MeshVolume."""
    if VOLUME_KEY not in c.unit.features:
        return None
    vol = c.unit.col(VOLUME_KEY)
    flagged: list[str] = []
    for f in c.significant():
        if f == VOLUME_KEY:
            continue
        o = st.associate(vol, c.unit.col(f), "auto")
        if o.test is not None and abs(o.effect) > VOLUME_RHO:
            flagged.append(f)
    if not flagged:
        return None
    return rec(
        "REC-VOLUME",
        f"{len(flagged)} significant feature(s) may just reflect size (|rho| > {VOLUME_RHO} with "
        f"MeshVolume): {_names(flagged)}; check them against volume.",
        "feature-vs-volume",
        feature=flagged[0],
        features=flagged[:LIST_CAP],
    )


def redundant(c: Ctx) -> Recommendation | None:
    """REC-REDUNDANT: clusters of features with |rho| > 0.9."""
    k = min(len(c.unit.features), MAX_REDUNDANT_FEATURES)
    if k < 2 or c.unit.n < 3:
        return None
    rho = st.spearman_matrix(c.unit.x[:, :k])
    clusters = st.threshold_clusters(rho, REDUNDANT_RHO)
    if not clusters:
        return None
    n_feat = sum(len(g) for g in clusters)
    return rec(
        "REC-REDUNDANT",
        f"Many redundant features: {len(clusters)} cluster(s) covering {n_feat} features with "
        f"|rho| > {REDUNDANT_RHO}; keep one per cluster for modeling.",
        "correlation",
        threshold=REDUNDANT_RHO,
    )


def nonindep(c: Ctx) -> Recommendation | None:
    """REC-NONINDEP: more than one item per case in the unit."""
    n_cases = len(set(c.unit.case_id.tolist()))
    if n_cases == c.unit.n:
        return None
    return rec(
        "REC-NONINDEP",
        f"Rows are not independent: {c.unit.n} rows from {n_cases} cases; aggregate per case.",
        "phase-side-consistency",
        feature=c.top_feature,
    )


def no_signal(c: Ctx) -> Recommendation | None:
    """REC-NO-SIGNAL: no feature with q < 0.1."""
    if c.spec.question not in ("compare", "association"):
        return None
    if not any(r.q is not None for r in c.computed.results) or c.significant(Q_SIGNAL):
        return None
    return rec(
        "REC-NO-SIGNAL",
        "No robust differences (no feature with q < 0.1); consider effect sizes and power "
        "before concluding.",
        c.home,
        variable=c.spec.variable,
    )


def modality(c: Ctx) -> Recommendation | None:
    """REC-MODALITY: mixed modalities among the items in the unit."""
    if MODALITY_VAR not in c.unit.frame.vars.columns:
        return None
    found = c.unit.member_values(MODALITY_VAR)
    if len(found) < 2:
        return None
    return rec(
        "REC-MODALITY",
        f"Mixed modalities in the unit ({', '.join(found)}): intensity features are not "
        "comparable across modalities; filter to one.",
        "feature-distribution",
        feature=c.top_feature,
        split=MODALITY_VAR,
    )


def _sources(catalog: Catalog, name: str) -> set[str]:
    """The variable plus everything it is derived from (VAR-06)."""
    out = {name}
    todo = [name]
    while todo:
        n = todo.pop()
        for d in catalog.derived:
            if d.name == n:
                srcs = d.sources if d.op == "dominant" else [d.source]
                todo += [s for s in srcs if s not in out]
                out.update(srcs)
    return out


def compositional_sets(c: Ctx) -> list[tuple[str, ...]]:
    """Pairs/triples of continuous variables whose sum is ≈ constant over the unit rows."""
    names = [
        v.name
        for v in sorted(c.catalog.variables, key=lambda v: v.group != "study")
        if v.type in CONTINUOUS_TYPES and v.name in c.unit.frame.vars.columns
    ][:COMPOSITIONAL_MAX_VARS]
    cols = {n: c.unit.numeric(n) for n in names}
    found: list[tuple[str, ...]] = []
    for k in (2, 3):
        for combo in itertools.combinations(names, k):
            if any(set(f) <= set(combo) for f in found):
                continue
            s = np.sum([cols[n] for n in combo], axis=0)
            s = s[np.isfinite(s)]
            if s.size < st.MIN_N:
                continue
            med = float(np.median(s))
            if med == 0:
                continue
            share = float((np.abs(s - med) <= COMPOSITIONAL_TOL * abs(med)).mean())
            parts_vary = all(np.ptp(st.finite(cols[n])) > 0 for n in combo)
            if share >= COMPOSITIONAL_SHARE and parts_vary:
                found.append(combo)
    return found


def compositional(c: Ctx) -> Recommendation | None:
    """REC-COMPOSITIONAL: ≥ 2 continuous variables summing to ≈ constant, when the analysis
    variable is one of them or derived from one (any set for Explore)."""
    sets = compositional_sets(c)
    if c.spec.variable is not None:
        srcs = _sources(c.catalog, c.spec.variable) | (
            _sources(c.catalog, c.spec.confounder) if c.spec.confounder else set()
        )
        sets = [s for s in sets if srcs & set(s)]
    if not sets:
        return None
    first = sets[0]
    return rec(
        "REC-COMPOSITIONAL",
        f"Variables are compositional ({' + '.join(first)} ≈ constant); analyze one, or use a "
        "derived dominant/bin variable.",
        "association",
        variable=first[0],
        variables=list(first),
    )


RULES = (
    small_n,
    imbalance,
    missing,
    confounder,
    volume,
    redundant,
    nonindep,
    no_signal,
    modality,
    compositional,
)


def recommend(
    spec: AnalysisSpec, unit: Unit, catalog: Catalog, computed: Computed
) -> list[Recommendation]:
    c = Ctx(spec, unit, catalog, computed)
    return [r for rule in RULES if (r := rule(c)) is not None]
