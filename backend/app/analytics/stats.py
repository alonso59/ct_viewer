"""Guided statistics (ANALYSIS.md §Tests; ANA-04..07) on plain NumPy arrays. SciPy only.

Every function is pure and deterministic (the RxC Fisher permutation test uses a fixed seed).
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import stats  # type: ignore[import-untyped]
from scipy.cluster import hierarchy  # type: ignore[import-untyped]
from scipy.sparse import csr_matrix  # type: ignore[import-untyped]
from scipy.sparse.csgraph import connected_components  # type: ignore[import-untyped]
from scipy.spatial.distance import squareform  # type: ignore[import-untyped]

from app.analytics.models import EffectName, TestName, TestOverride

F64 = NDArray[np.float64]

MIN_N = 5  # ANA-06
ALT_N = 15  # ANA-04: alternative test when any group n < 15
ALPHA = 0.05
FISHER_RESAMPLES = 9999
FISHER_SEED = 0
MAD_SCALE = 1.4826


@contextmanager
def quiet() -> Iterator[None]:
    """Degenerate inputs (constant groups, tiny n) warn in SciPy; results become NaN."""
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        yield


def num(x: Any) -> float | None:
    """JSON-safe float: NaN/inf → None."""
    if x is None:
        return None
    v = float(x)
    return v if math.isfinite(v) else None


def finite(a: F64) -> F64:
    return a[np.isfinite(a)]


@dataclass
class Outcome:
    test: TestName | None
    reason: str
    statistic: float = math.nan
    p: float = math.nan
    effect: float = math.nan
    effect_name: EffectName | None = None
    n: int = 0
    groups: list[str] = field(default_factory=list)
    alternative: bool = False


# -- ANA-04 choice ----------------------------------------------------------------------------


def shapiro_p(x: F64) -> float:
    if x.size < 3 or np.ptp(x) == 0:
        return math.nan
    with quiet():
        return float(stats.shapiro(x).pvalue)


def use_alternative(
    levels: Sequence[str], groups: Sequence[F64], override: TestOverride
) -> tuple[bool, str]:
    """ANA-04 rule: alternative when any group n < 15 or Shapiro-Wilk p < 0.05."""
    if override == "default":
        return False, "default test forced by the user"
    if override == "alternative":
        return True, "alternative test forced by the user"
    sizes = [g.size for g in groups]
    if min(sizes) < ALT_N:
        return True, f"smallest group n = {min(sizes)} < {ALT_N}"
    for level, g in zip(levels, groups, strict=True):
        p = shapiro_p(g)
        if p < ALPHA:
            return True, f"Shapiro-Wilk p = {p:.3g} < {ALPHA} in group {level!r}"
    return False, f"all groups n ≥ {ALT_N} and Shapiro-Wilk p ≥ {ALPHA}"


# -- effect sizes -----------------------------------------------------------------------------


def cohens_d(a: F64, b: F64) -> float:
    n1, n2 = a.size, b.size
    sp2 = ((n1 - 1) * np.var(a, ddof=1) + (n2 - 1) * np.var(b, ddof=1)) / (n1 + n2 - 2)
    if not sp2 > 0:
        return math.nan
    return float((np.mean(a) - np.mean(b)) / math.sqrt(sp2))


def rank_biserial(u: float, n1: int, n2: int) -> float:
    """r = 2·U₁/(n₁n₂) - 1 (positive when the first group tends to be larger)."""
    return 2.0 * u / (n1 * n2) - 1.0


def eta_squared(groups: Sequence[F64]) -> float:
    allv = np.concatenate(list(groups))
    grand = allv.mean()
    ss_t = float(((allv - grand) ** 2).sum())
    ss_b = float(sum(g.size * (g.mean() - grand) ** 2 for g in groups))
    return ss_b / ss_t if ss_t > 0 else math.nan


def epsilon_squared(h: float, n: int) -> float:
    """ε² = H / ((n² - 1)/(n + 1)) = H / (n - 1)."""
    return h / (n - 1) if n > 1 else math.nan


def cramers_v(table: NDArray[np.int64]) -> float:
    n = int(table.sum())
    k = min(table.shape) - 1
    if n == 0 or k < 1:
        return math.nan
    with quiet():
        chi2 = float(stats.chi2_contingency(table, correction=False).statistic)
    return math.sqrt(chi2 / (n * k))


# -- tests ------------------------------------------------------------------------------------


def compare(levels: Sequence[str], groups: Sequence[F64], override: TestOverride) -> Outcome:
    """Compare groups (2 → Welch t / Mann-Whitney; ≥ 3 → Welch ANOVA / Kruskal-Wallis).

    `groups` hold finite values only. Groups with n < 5 are dropped here (ANA-06).
    """
    kept = [(lv, g) for lv, g in zip(levels, groups, strict=True) if g.size >= MIN_N]
    names = [lv for lv, _ in kept]
    gs = [g for _, g in kept]
    n = int(sum(g.size for g in gs))
    if len(gs) < 2:
        return Outcome(None, f"fewer than two groups with n ≥ {MIN_N}", n=n, groups=names)
    if np.ptp(np.concatenate(gs)) == 0:
        return Outcome(None, "constant feature", n=n, groups=names)
    alt, reason = use_alternative(names, gs, override)
    out = Outcome(None, reason, n=n, groups=names, alternative=alt)
    with quiet():
        if len(gs) == 2:
            a, b = gs
            if alt:
                r = stats.mannwhitneyu(a, b, alternative="two-sided")
                out.test, out.effect_name = "mann_whitney", "rank_biserial_r"
                out.statistic, out.p = float(r.statistic), float(r.pvalue)
                out.effect = rank_biserial(out.statistic, a.size, b.size)
            else:
                t = stats.ttest_ind(a, b, equal_var=False)
                out.test, out.effect_name = "welch_t", "cohens_d"
                out.statistic, out.p = float(t.statistic), float(t.pvalue)
                out.effect = cohens_d(a, b)
        elif alt:
            k = stats.kruskal(*gs)
            out.test, out.effect_name = "kruskal_wallis", "epsilon_squared"
            out.statistic, out.p = float(k.statistic), float(k.pvalue)
            out.effect = epsilon_squared(out.statistic, n)
        else:
            f = stats.f_oneway(*gs, equal_var=False)
            out.test, out.effect_name = "welch_anova", "eta_squared"
            out.statistic, out.p = float(f.statistic), float(f.pvalue)
            out.effect = eta_squared(gs)
    return out


def associate(x: F64, y: F64, override: TestOverride) -> Outcome:
    """Association: Spearman rho (default) or Pearson r (user choice), pairwise complete."""
    m = np.isfinite(x) & np.isfinite(y)
    xs, ys = x[m], y[m]
    n = int(m.sum())
    if n < MIN_N:
        return Outcome(None, f"n = {n} < {MIN_N}", n=n)
    if np.ptp(xs) == 0 or np.ptp(ys) == 0:
        return Outcome(None, "constant feature or variable", n=n)
    with quiet():
        if override == "alternative":
            r = stats.pearsonr(xs, ys)
            rv = float(r.statistic)
            return Outcome(
                "pearson",
                "Pearson r chosen by the user",
                statistic=rv,
                p=float(r.pvalue),
                effect=rv,
                effect_name="pearson_r",
                n=n,
                alternative=True,
            )
        s = stats.spearmanr(xs, ys)
        rho = float(s.statistic)
        return Outcome(
            "spearman",
            "Spearman rho: rank-based, no normality assumption",
            statistic=rho,
            p=float(s.pvalue),
            effect=rho,
            effect_name="spearman_rho",
            n=n,
        )


def contingency_test(table: NDArray[np.int64], override: TestOverride) -> Outcome:
    """Balance check: χ² (default) or Fisher exact when any expected count < 5.

    2x2 Fisher is exact; RxC Fisher is SciPy's permutation test with a fixed seed.
    """
    n = int(table.sum())
    if min(table.shape) < 2 or n == 0:
        return Outcome(None, f"fewer than two levels with n ≥ {MIN_N} on each side", n=n)
    with quiet():
        chi = stats.chi2_contingency(table)
    expected = np.asarray(chi.expected_freq)
    v = cramers_v(table)
    if override == "alternative":
        alt, reason = True, "Fisher exact forced by the user"
    elif override == "default":
        alt, reason = False, "χ² forced by the user"
    elif (expected < 5).any():
        alt, reason = True, f"expected count {expected.min():.2g} < 5"
    else:
        alt, reason = False, "all expected counts ≥ 5"
    res: Any = chi
    if alt:
        with quiet():
            res = fisher(table)
    return Outcome(
        "fisher" if alt else "chi2",
        reason,
        statistic=float(res.statistic),
        p=float(res.pvalue),
        effect=v,
        effect_name="cramers_v",
        n=n,
        alternative=alt,
    )


def fisher(table: NDArray[np.int64]) -> Any:
    if table.shape == (2, 2):
        return stats.fisher_exact(table)
    method = stats.PermutationMethod(
        n_resamples=FISHER_RESAMPLES, rng=np.random.default_rng(FISHER_SEED)
    )
    return stats.fisher_exact(table, method=method)


def bh(p: Sequence[float]) -> list[float]:
    """ANA-05 Benjamini-Hochberg q over the finite p-values; NaN stays NaN."""
    arr = np.asarray(p, dtype=np.float64)
    q = np.full(arr.shape, np.nan)
    m = np.isfinite(arr)
    if m.any():
        q[m] = stats.false_discovery_control(arr[m], method="bh")
    return [float(x) for x in q]


# -- descriptives -----------------------------------------------------------------------------


@dataclass
class Desc:
    n: int
    missing: int
    median: float = math.nan
    q1: float = math.nan
    q3: float = math.nan
    mean: float = math.nan
    sd: float = math.nan
    min: float = math.nan
    max: float = math.nan


def describe(values: F64) -> Desc:
    """ANA-07: n, missing, median, IQR (linear quantiles), mean, SD (ddof = 1)."""
    v = finite(values)
    d = Desc(n=int(v.size), missing=int(values.size - v.size))
    if v.size:
        d.q1, d.median, d.q3 = (float(x) for x in np.percentile(v, [25, 50, 75]))
        d.mean = float(v.mean())
        d.sd = float(v.std(ddof=1)) if v.size > 1 else math.nan
        d.min, d.max = float(v.min()), float(v.max())
    return d


def whiskers(values: F64, d: Desc) -> tuple[float, float]:
    """Tukey whiskers: most extreme values within 1.5·IQR of the quartiles."""
    v = finite(values)
    if not v.size:
        return math.nan, math.nan
    iqr = d.q3 - d.q1
    lo = v[v >= d.q1 - 1.5 * iqr]
    hi = v[v <= d.q3 + 1.5 * iqr]
    return float(lo.min() if lo.size else d.min), float(hi.max() if hi.size else d.max)


# -- matrices ---------------------------------------------------------------------------------


def spearman_matrix(x: F64) -> F64:
    """Spearman rho between columns: ranks per column (NaN ignored), then pairwise-complete
    Pearson on the ranks. Exact when there are no missing values."""
    fin = np.isfinite(x)
    xr = np.where(fin, x, np.nan)
    with quiet():
        r = stats.rankdata(xr, axis=0, nan_policy="omit")
    m = fin.astype(np.float64)
    rz = np.where(fin, r, 0.0)
    n = m.T @ m
    sx = rz.T @ m  # sum of column i over rows where j is present
    sxx = (rz**2).T @ m
    sxy = rz.T @ rz
    with quiet():
        cov = sxy - sx * sx.T / n
        vx = sxx - sx**2 / n
        rho = cov / np.sqrt(vx * vx.T)
    rho[n < 3] = np.nan
    out: F64 = np.clip(rho, -1.0, 1.0)
    return out


def threshold_clusters(rho: F64, threshold: float) -> list[list[int]]:
    """Connected groups of features with |rho| > threshold (size ≥ 2)."""
    adj = np.nan_to_num(np.abs(rho)) > threshold
    np.fill_diagonal(adj, False)
    n_comp, lab = connected_components(csr_matrix(adj), directed=False)
    groups = [np.flatnonzero(lab == c).tolist() for c in range(n_comp)]
    return sorted((g for g in groups if len(g) > 1), key=lambda g: (-len(g), g[0]))


def cluster_order(rho: F64) -> list[int]:
    """Average-linkage leaf order on 1 - |rho| (NaN treated as rho = 0)."""
    k = rho.shape[0]
    if k < 3:
        return list(range(k))
    d = 1.0 - np.nan_to_num(np.abs(rho))
    d = (d + d.T) / 2
    np.fill_diagonal(d, 0.0)
    z = hierarchy.linkage(squareform(np.clip(d, 0, None), checks=False), method="average")
    return [int(i) for i in hierarchy.leaves_list(z)]


def robust_z(x: F64) -> F64:
    """(x - median) / (1.4826 · MAD) per column; NaN where MAD = 0 or x is not finite."""
    xf = np.where(np.isfinite(x), x, np.nan)
    with quiet():
        med = np.nanmedian(xf, axis=0)
        mad = np.nanmedian(np.abs(xf - med), axis=0) * MAD_SCALE
        z = (xf - med) / np.where(mad > 0, mad, np.nan)
    out: F64 = z
    return out


def zscore_impute(x: F64) -> F64:
    """Column z-scores (ddof = 0); non-finite cells imputed to 0 (the column mean)."""
    xf = np.where(np.isfinite(x), x, np.nan)
    with quiet():
        mu = np.nanmean(xf, axis=0)
        sd = np.nanstd(xf, axis=0)
        z = (xf - mu) / sd
    out: F64 = np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)
    return out
