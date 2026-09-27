"""Dashboard view computations (DASHBOARD.md §Views; API-38, DB-02/03/05/07).

Pure functions over a filtered `Frame`: server-side aggregates only; point lists are capped
at `MAX_POINTS` (DB-05) and carry `item_id`/`case_id`/status (DB-03).
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from typing import Any, Literal

import numpy as np

from app.analytics import analysis as an
from app.analytics import stats as st
from app.analytics.data import (
    VOLUME_KEY,
    Frame,
    Obj,
    Unit,
    bad,
    build_unit,
    select_features,
)
from app.analytics.models import (
    AssociationRequest,
    AssociationResponse,
    BalanceRequest,
    BalanceResponse,
    BoxStats,
    Cluster,
    ConsistencyRequest,
    ConsistencyResponse,
    CorrelationRequest,
    CorrelationResponse,
    DistGroup,
    DistPoint,
    EmbeddingPoint,
    EmbeddingRequest,
    EmbeddingResponse,
    FeatureDistributionRequest,
    FeatureDistributionResponse,
    FeatureVsVolumeRequest,
    FeatureVsVolumeResponse,
    GroupComparisonRequest,
    GroupComparisonResponse,
    LabelCount,
    LevelCount,
    Loading,
    MissingCell,
    MissingFeature,
    MissingItem,
    MissingMatrixRequest,
    MissingMatrixResponse,
    OutlierFeature,
    OutlierFeatureCount,
    OutlierItem,
    OutliersRequest,
    OutliersResponse,
    PairPoint,
    PhaseChange,
    RankedFeature,
    RunError,
    RunOverviewRequest,
    RunOverviewResponse,
    ScatterPoint,
    UnitPoint,
    UnitSummary,
)
from app.analytics.stats import F64, num

MAX_POINTS = 50_000  # DB-05
TOP_LOADINGS = 10
SIZE_RHO = 0.8


def ordered_levels(levels: Obj) -> list[str]:
    return an.level_order([str(x) for x in levels if x is not None])


def box(values: F64) -> BoxStats:
    d = st.describe(values)
    lo, hi = st.whiskers(values, d)
    return BoxStats(
        n=d.n,
        min=num(d.min),
        q1=num(d.q1),
        median=num(d.median),
        q3=num(d.q3),
        max=num(d.max),
        whisker_low=num(lo),
        whisker_high=num(hi),
        mean=num(d.mean),
        sd=num(d.sd),
    )


def _ref(frame: Frame, i: int, color: Obj | None = None) -> dict[str, Any]:
    rd = frame.rd
    return {
        "item_id": str(rd.item_id[i]),
        "case_id": str(rd.case_id[i]),
        "label": int(rd.label[i]),
        "status": str(frame.status[i]),
        "color": None if color is None else color[i],
    }


def unit_summary(unit: Unit, n_missing: int = 0) -> UnitSummary:
    return UnitSummary(
        label=unit.label,
        scope=unit.scope,
        phase=unit.phase,
        aggregate=unit.aggregate,  # type: ignore[arg-type]
        n_rows=unit.n,
        n_cases=len(set(unit.case_id.tolist())),
        n_items=int(sum(m.size for m in unit.members)),
        max_items_per_case=max(Counter(unit.case_id.tolist()).values(), default=0)
        if unit.aggregate == "none"
        else max((m.size for m in unit.members), default=0),
        n_variable_missing=n_missing,
    )


def _unit_points(
    unit: Unit, values: F64, group: Obj | None = None, x: F64 | None = None
) -> list[UnitPoint]:
    ids = unit.item_ids
    status = unit.frame.status
    out: list[UnitPoint] = []
    for r in range(min(unit.n, MAX_POINTS)):
        out.append(
            UnitPoint(
                item_id=ids[r][0],
                case_id=str(unit.case_id[r]),
                item_ids=ids[r],
                status=str(status[unit.rep[r]]),
                group=None if group is None else group[r],
                x=None if x is None else num(x[r]),
                value=num(values[r]),
            )
        )
    return out


# -- Run overview ---------------------------------------------------------------------------


def _ts(s: Any) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def run_overview(
    frame: Frame,
    run: dict[str, Any],
    errors: list[dict[str, Any]],
    selected: set[str] | None,
    req: RunOverviewRequest,
) -> RunOverviewResponse:
    """Items ok/failed, per-label counts, runtime, error list → item."""
    rd = frame.rd
    ok_items = set(rd.item_id.tolist())
    rows = [e for e in errors if selected is None or str(e.get("item_id")) in selected]
    failed = [e for e in rows if e.get("kind") != "skipped"]
    failed_items = {str(e.get("item_id")) for e in failed if e.get("item_id")} - ok_items
    skipped_items = {str(e.get("item_id")) for e in rows if e.get("kind") == "skipped"}
    skipped_items -= ok_items | failed_items
    inputs = run.get("inputs") or []
    sel_items = {str(i.get("item_id")) for i in inputs if isinstance(i, dict)}
    sel_items |= {str(i) for i in (run.get("selection") or {}).get("item_ids") or []}
    if selected is not None:
        sel_items &= selected
    per_label: list[LabelCount] = []
    for lab in sorted(set(rd.label.tolist())):
        m = rd.label == lab
        per_label.append(
            LabelCount(
                label=int(lab),
                n_items=len(set(rd.item_id[m].tolist())),
                n_values=int(rd.present[m].sum()),
            )
        )
    first: dict[str, int] = {}
    for i, iid in enumerate(rd.item_id.tolist()):
        first.setdefault(iid, i)
    phases = Counter(str(rd.phase[i]) for i in first.values())
    curation = Counter(str(frame.status[i]) for i in first.values())
    start, end = _ts(run.get("started_at")), _ts(run.get("finished_at"))
    # failures first, then skips (AUD-A2-05)
    listed = sorted(rows, key=lambda e: e.get("kind") == "skipped")
    run_errors = [
        RunError(
            item_id=e.get("item_id"),
            case_id=e.get("case_id") or str(e.get("item_id") or "").split(".")[0] or None,
            label=e.get("label") if isinstance(e.get("label"), int) else None,
            message=str(e.get("message") or e.get("error") or e.get("detail") or ""),
            kind="skipped" if e.get("kind") == "skipped" else "failed",
            code=e.get("code"),
            detail=e.get("detail"),
        )
        for e in listed[: req.errors_limit]
    ]
    changed = [
        PhaseChange(
            item_id=str(rd.item_id[i]),
            case_id=str(rd.case_id[i]),
            phase=str(rd.phase[i]),
            phase_at_run=str(rd.phase_at_run[i]),
        )
        for i in first.values()
        if rd.phase_at_run[i] != rd.phase[i]
    ]
    return RunOverviewResponse(
        run_id=rd.run_id,
        name=str(run.get("name") or ""),
        status=str(run.get("status") or ""),
        created_at=run.get("created_at"),
        runtime_s=(end - start).total_seconds() if start and end else None,
        n_items_selected=max(len(sel_items), len(ok_items | failed_items | skipped_items)),
        n_items_ok=len(ok_items),
        n_items_failed=len(failed_items),
        n_items_skipped=len(skipped_items),
        n_features=len(rd.features),
        per_label=per_label,
        per_phase=[LevelCount(level=k, n=v) for k, v in sorted(phases.items())],
        curation=[LevelCount(level=k, n=v) for k, v in sorted(curation.items())],
        n_errors=len(rows),
        errors=run_errors,
        phase_changed=changed,
    )


# -- Feature distribution -------------------------------------------------------------------


def feature_distribution(
    frame: Frame, req: FeatureDistributionRequest
) -> FeatureDistributionResponse:
    """Histogram + box per split level for one feature (log scale optional)."""
    raw = frame.rd.col(req.feature)
    vals = raw.copy()
    ok = np.isfinite(vals)
    if req.log_scale:
        ok &= vals > 0
        with st.quiet():
            vals = np.where(ok, np.log10(np.where(ok, vals, 1.0)), np.nan)
    levels = frame.levels(req.split, ("body", "split"))
    fin = vals[ok]
    if fin.size:
        lo, hi = float(fin.min()), float(fin.max())
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        edges = np.linspace(lo, hi, req.bins + 1)
    else:
        edges = np.linspace(0.0, 1.0, req.bins + 1)
    bins = np.full(vals.size, -1)
    bins[ok] = np.clip(np.searchsorted(edges, vals[ok], side="right") - 1, 0, req.bins - 1)
    split_levels: list[str | None] = [None] if req.split is None else [*ordered_levels(levels)]
    if req.split is not None and any(x is None for x in levels):
        split_levels.append(None)
    groups: list[DistGroup] = []
    for lv in split_levels:
        m = np.asarray([x == lv for x in levels], dtype=bool)
        counts = np.bincount(bins[m & ok], minlength=req.bins)
        groups.append(
            DistGroup(
                level=lv,
                n=int((m & ok).sum()),
                n_missing=int((m & ~ok).sum()),
                counts=[int(c) for c in counts],
                box=box(raw[m & ok]),
            )
        )
    idx = np.flatnonzero(ok)
    points = [
        DistPoint(**_ref(frame, int(i), levels), value=float(raw[i]), bin=int(bins[i]))
        for i in idx[:MAX_POINTS]
    ]
    return FeatureDistributionResponse(
        feature=req.feature,
        split=req.split,
        log_scale=req.log_scale,
        edges=[float(e) for e in edges],
        groups=groups,
        points=points,
        truncated=idx.size > MAX_POINTS,
    )


# -- Missing / invalid matrix ---------------------------------------------------------------


def missing_matrix(frame: Frame, req: MissingMatrixRequest) -> MissingMatrixResponse:
    """Feature x item NaN/inf/absent cells (sparse), worst items first."""
    rd = select_features(frame.rd, None, req.feature_class)
    nan = rd.present & np.isnan(rd.x)
    inf = rd.present & np.isinf(rd.x)
    absent = ~rd.present
    bad_cells = nan | inf | absent
    per_item = bad_cells.sum(axis=1)
    rows = [int(i) for i in np.argsort(-per_item, kind="stable") if per_item[i] > 0]
    features = [
        MissingFeature(
            feature=f,
            feature_class=rd.feature_class[j],
            n_nan=int(nan[:, j].sum()),
            n_inf=int(inf[:, j].sum()),
            n_absent=int(absent[:, j].sum()),
        )
        for j, f in enumerate(rd.features)
    ]
    items: list[MissingItem] = []
    cells: list[MissingCell] = []
    truncated = False
    status = frame.status
    for k, i in enumerate(rows):
        items.append(
            MissingItem(
                item_id=str(rd.item_id[i]),
                case_id=str(rd.case_id[i]),
                label=int(rd.label[i]),
                status=str(status[i]),
                n_invalid=int(per_item[i]),
            )
        )
        for j in np.flatnonzero(bad_cells[i]):
            if len(cells) >= req.max_cells:
                truncated = True
                break
            kind: Literal["nan", "inf", "absent"] = (
                "nan" if nan[i, j] else "inf" if inf[i, j] else "absent"
            )
            cells.append(MissingCell(item=k, feature=int(j), kind=kind))
    return MissingMatrixResponse(
        features=features, items=items, cells=cells, n_items_total=rd.n, truncated=truncated
    )


# -- Correlation ----------------------------------------------------------------------------


def _usable(x: F64, min_n: int = 3) -> list[int]:
    fin = np.isfinite(x)
    out = []
    for j in range(x.shape[1]):
        v = x[fin[:, j], j]
        if v.size >= min_n and np.ptp(v) > 0:
            out.append(j)
    return out


def correlation(frame: Frame, req: CorrelationRequest) -> CorrelationResponse:
    """Spearman rho between features in clustered order + |rho| > threshold clusters."""
    rd = select_features(frame.rd, None, req.feature_class)
    keep = _usable(rd.x)
    truncated = len(keep) > req.max_features
    if truncated:  # keep the most complete, then most variable (robust spread) features
        fin = np.isfinite(rd.x)
        with st.quiet():
            spread = np.nan_to_num(np.abs(st.robust_z(rd.x)).mean(axis=0))
        keep = sorted(keep, key=lambda j: (-int(fin[:, j].sum()), -float(spread[j]), j))
        keep = sorted(keep[: req.max_features])
    x = rd.x[:, keep]
    names = [rd.features[j] for j in keep]
    rho = st.spearman_matrix(x) if keep else np.zeros((0, 0))
    order = st.cluster_order(rho)
    rho_o = rho[np.ix_(order, order)] if keep else rho
    clusters = [
        Cluster(features=[names[j] for j in g]) for g in st.threshold_clusters(rho, req.threshold)
    ]
    return CorrelationResponse(
        features=[names[j] for j in order],
        matrix=[
            [None if not math.isfinite(v) else round(float(v), 4) for v in row] for row in rho_o
        ],
        threshold=req.threshold,
        clusters=clusters,
        n_rows=rd.n,
        truncated=truncated,
    )


# -- Embedding ------------------------------------------------------------------------------


def embedding(frame: Frame, req: EmbeddingRequest) -> EmbeddingResponse:
    """PCA (default) or UMAP (optional extra) on z-scored features."""
    rd = select_features(frame.rd, req.features, req.feature_class)
    keep = _usable(rd.x)
    if len(keep) < 2 or rd.n < 3:
        raise bad(("body", "features"), "Embedding needs ≥ 2 varying features and ≥ 3 items")
    z = st.zscore_impute(rd.x[:, keep])
    names = [rd.features[j] for j in keep]
    k = min(req.n_components, len(keep), rd.n)
    levels = frame.levels(req.color_by, ("body", "color_by"))
    if req.method == "umap":
        try:
            import umap  # type: ignore[import-not-found]  # optional extra (DASHBOARD.md)
        except ImportError:
            raise bad(("body", "method"), "UMAP is not installed (optional extra `umap`)") from None
        coords = np.asarray(umap.UMAP(n_components=k, random_state=0).fit_transform(z))
        evr: list[float] = []
        loadings: list[list[Loading]] = []
    else:
        from sklearn.decomposition import PCA

        pca = PCA(n_components=k, random_state=0)
        coords = pca.fit_transform(z)
        evr = [float(v) for v in pca.explained_variance_ratio_]
        loadings = []
        for comp in pca.components_:
            top = np.argsort(-np.abs(comp))[:TOP_LOADINGS]
            loadings.append([Loading(feature=names[t], weight=float(comp[t])) for t in top])
    points = [
        EmbeddingPoint(**_ref(frame, i, levels), coords=[float(c) for c in coords[i]])
        for i in range(min(rd.n, MAX_POINTS))
    ]
    return EmbeddingResponse(
        method=req.method,
        n_components=k,
        explained_variance_ratio=evr,
        features_used=names,
        top_loadings=loadings,
        color_levels=ordered_levels(levels),
        points=points,
    )


# -- Outliers -------------------------------------------------------------------------------


def outliers(frame: Frame, req: OutliersRequest) -> OutliersResponse:
    """Robust z = (x - median) / (1.4826 · MAD) per feature; flagged items and top features.

    An item is flagged when at least `min_feature_pct` % of its features (and at least one) have
    |z| over the threshold (owner decision 2026-09-27, DB-10). Flagged items rank by the number of
    features over the threshold, then by max |z| (owner decision 2026-09-25, AUD-A2-06): one wild
    feature does not outrank a broadly abnormal item. Per-feature counts cover every item."""
    rd = select_features(frame.rd, None, req.feature_class)
    z = st.robust_z(rd.x)
    az = np.abs(np.nan_to_num(z, nan=0.0))
    over = az > req.threshold
    max_z = az.max(axis=1) if rd.features else np.zeros(rd.n)
    n_over = over.sum(axis=1)
    n_feat = len(rd.features)
    need = max(1, math.ceil(req.min_feature_pct / 100 * n_feat - 1e-9))
    flagged = [i for i in range(rd.n) if n_feat and int(n_over[i]) >= need]
    order = sorted(flagged, key=lambda i: (-int(n_over[i]), -float(max_z[i])))
    items: list[OutlierItem] = []
    for i in order[: req.top_n]:
        top = np.argsort(-az[i])[: req.top_features]
        items.append(
            OutlierItem(
                **_ref(frame, i),
                max_abs_z=float(max_z[i]),
                n_outlier_features=int(n_over[i]),
                top_features=[
                    OutlierFeature(feature=rd.features[j], value=num(rd.x[i, j]), z=float(z[i, j]))
                    for j in top
                    if az[i, j] > 0
                ],
            )
        )
    per_feature = over.sum(axis=0)
    fo = [int(j) for j in np.argsort(-per_feature, kind="stable") if per_feature[j] > 0]
    return OutliersResponse(
        threshold=req.threshold,
        min_feature_pct=req.min_feature_pct,
        min_features=need,
        n_features=n_feat,
        n_items=rd.n,
        n_flagged=len(flagged),
        items=items,
        features=[
            OutlierFeatureCount(feature=rd.features[j], n_outlier_items=int(per_feature[j]))
            for j in fo[: req.top_n]
        ],
    )


# -- Feature vs volume ----------------------------------------------------------------------


def feature_vs_volume(frame: Frame, req: FeatureVsVolumeRequest) -> FeatureVsVolumeResponse:
    """Scatter of a feature against shape MeshVolume, rho, and all features ranked by |rho|."""
    rd = frame.rd
    if VOLUME_KEY not in rd.features:
        raise bad(("path", "view"), f"Run has no {VOLUME_KEY} (enable the shape class)")
    vol = rd.col(VOLUME_KEY, ("path", "view"))
    y = rd.col(req.feature)
    o = st.associate(vol, y, "auto")
    levels = frame.levels(req.color_by, ("body", "color_by"))
    m = np.isfinite(vol) & np.isfinite(y)
    idx = np.flatnonzero(m)
    points = [
        ScatterPoint(**_ref(frame, int(i), levels), x=float(vol[i]), y=float(y[i]))
        for i in idx[:MAX_POINTS]
    ]
    rho = st.spearman_matrix(np.column_stack([vol, rd.x]))[0, 1:] if rd.n else np.zeros(0)
    n_pair = (np.isfinite(rd.x) & np.isfinite(vol)[:, None]).sum(axis=0)
    ranked = sorted(
        (
            RankedFeature(feature=f, rho=num(rho[j]), n=int(n_pair[j]))
            for j, f in enumerate(rd.features)
            if f != VOLUME_KEY
        ),
        key=lambda r: -abs(r.rho) if r.rho is not None else 1.0,
    )
    return FeatureVsVolumeResponse(
        feature=req.feature,
        volume_feature=VOLUME_KEY,
        rho=num(o.effect),
        p=num(o.p),
        n=o.n,
        size_driven=o.test is not None and abs(o.effect) > SIZE_RHO,
        color_levels=ordered_levels(levels),
        points=points,
        ranked=ranked[: req.top_n],
    )


# -- Group comparison / association / balance -----------------------------------------------


def _unit(frame: Frame, req: GroupComparisonRequest | AssociationRequest | BalanceRequest) -> Unit:
    feats = getattr(req, "features", None)
    fclass = getattr(req, "feature_class", None)
    frame = Frame(
        select_features(frame.rd, feats, fclass), frame.status, frame.vars, frame.priority
    )
    return build_unit(frame, req.unit)


def group_comparison(frame: Frame, req: GroupComparisonRequest) -> GroupComparisonResponse:
    """Box per group for the selected feature + test; results table for all features."""
    unit = _unit(frame, req)
    v = frame.vars.var(req.variable, ("body", "variable"))
    c = an.compare(unit, v, req.test)
    feature = req.feature or next((r.feature for r in c.results if r.feature), None)
    selected = None
    boxes: list[DistGroup] = []
    points: list[UnitPoint] = []
    descriptives = []
    if feature is not None:
        col = unit.col(feature)
        selected = next(r for r in c.results if r.feature == feature)
        levels = c.row_levels if c.row_levels is not None else np.full(unit.n, None, dtype=object)
        for g in c.groups:
            m = levels == g.level
            vals = col[m]
            boxes.append(
                DistGroup(
                    level=g.level,
                    n=int(np.isfinite(vals).sum()),
                    n_missing=int((~np.isfinite(vals)).sum()),
                    counts=[],
                    box=box(vals),
                )
            )
        points = _unit_points(unit, col, group=levels)
        descriptives = [d for d in c.descriptives if d.feature == feature]
    return GroupComparisonResponse(
        variable=req.variable,
        feature=feature,
        unit=unit_summary(unit, c.n_variable_missing),
        groups=c.groups,
        choice=c.choice,
        selected=selected,
        boxes=boxes,
        points=points,
        results=c.results,
        descriptives=descriptives,
    )


def association(frame: Frame, req: AssociationRequest) -> AssociationResponse:
    """Scatter feature x continuous variable with rho; ranked table of all features."""
    unit = _unit(frame, req)
    v = frame.vars.var(req.variable, ("body", "variable"))
    c = an.associate(unit, v, req.test)
    feature = req.feature or next((r.feature for r in c.results if r.feature), None)
    selected = None
    points: list[UnitPoint] = []
    if feature is not None:
        selected = next(r for r in c.results if r.feature == feature)
        points = _unit_points(unit, unit.col(feature), x=c.row_x)
    return AssociationResponse(
        variable=req.variable,
        feature=feature,
        unit=unit_summary(unit, c.n_variable_missing),
        choice=c.choice,
        selected=selected,
        points=points,
        results=c.results,
    )


def balance(frame: Frame, req: BalanceRequest) -> BalanceResponse:
    """Contingency heat map (variable x other) with χ² / Fisher and Cramér's V."""
    unit = build_unit(frame, req.unit)
    v = frame.vars.var(req.variable, ("body", "variable"))
    o = frame.vars.var(req.other, ("body", "other"))
    c = an.balance(unit, v, o, req.test)
    assert c.balance is not None
    return BalanceResponse(
        unit=unit_summary(unit, c.n_variable_missing), choice=c.choice, table=c.balance
    )


# -- Phase / side consistency ---------------------------------------------------------------


def _pair_key(frame: Frame, i: int, kind: str) -> tuple[Any, ...]:
    rd = frame.rd
    if kind == "phase":
        return (rd.case_id[i], rd.scope[i], rd.side[i], int(rd.label[i]))
    return (rd.case_id[i], rd.scan_idx[i], int(rd.label[i]))


def consistency(frame: Frame, req: ConsistencyRequest) -> ConsistencyResponse:
    """Paired values of the same case across two phases or sides (Bland-Altman)."""
    rd = frame.rd
    y = rd.col(req.feature)
    kind = req.pair.kind
    attr: Obj = rd.phase if kind == "phase" else rd.side
    if kind == "phase":
        present = {str(p) for p in rd.phase}
        ranked = [p for p in frame.priority if p in present] + sorted(present - set(frame.priority))
        a = req.pair.a or (ranked[0] if ranked else "")
        b = req.pair.b or next((p for p in ranked if p != a), "")
    else:
        a, b = req.pair.a or "L", req.pair.b or "R"
    if not a or not b or a == b:
        raise bad(("body", "pair"), "Pair needs two different phases/sides present in the run")
    first: dict[tuple[Any, ...], dict[str, int]] = {}
    order = sorted(range(rd.n), key=lambda i: (str(rd.scan_idx[i]), str(rd.item_id[i])))
    for i in order:
        s = str(attr[i])
        if s in (a, b) and math.isfinite(y[i]):
            first.setdefault(_pair_key(frame, i, kind), {}).setdefault(s, i)
    points: list[PairPoint] = []
    for d in first.values():
        if a in d and b in d:
            ia, ib = d[a], d[b]
            va, vb = float(y[ia]), float(y[ib])
            points.append(
                PairPoint(
                    case_id=str(rd.case_id[ia]),
                    item_id_a=str(rd.item_id[ia]),
                    item_id_b=str(rd.item_id[ib]),
                    label=int(rd.label[ia]),
                    status_a=str(frame.status[ia]),
                    status_b=str(frame.status[ib]),
                    a=va,
                    b=vb,
                    mean=(va + vb) / 2,
                    diff=vb - va,
                )
            )
    points.sort(key=lambda p: (p.case_id, p.label))
    diffs = np.asarray([p.diff for p in points], dtype=np.float64)
    bias = float(diffs.mean()) if diffs.size else math.nan
    sd = float(diffs.std(ddof=1)) if diffs.size > 1 else math.nan
    rho = math.nan
    if len(points) >= st.MIN_N:
        o = st.associate(
            np.asarray([p.a for p in points]), np.asarray([p.b for p in points]), "auto"
        )
        rho = o.effect
    return ConsistencyResponse(
        feature=req.feature,
        kind=kind,
        a=a,
        b=b,
        n_pairs=len(points),
        bias=num(bias),
        sd_diff=num(sd),
        loa_low=num(bias - 1.96 * sd),
        loa_high=num(bias + 1.96 * sd),
        rho=num(rho),
        points=points[:MAX_POINTS],
    )
