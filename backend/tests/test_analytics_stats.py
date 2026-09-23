"""TST-12: pure statistics helpers (ANA-04..07) on hand-built arrays."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats  # type: ignore[import-untyped]

from app.analytics import stats as st


def test_bh_keeps_nan_and_matches_scipy() -> None:
    p = [0.01, math.nan, 0.04, 0.03, 0.5]
    q = st.bh(p)
    ref = stats.false_discovery_control([0.01, 0.04, 0.03, 0.5], method="bh")
    assert math.isnan(q[1])
    assert [q[0], q[2], q[3], q[4]] == pytest.approx(list(ref), abs=1e-15)


def test_choice_rule_and_min_n() -> None:
    rng = np.random.default_rng(2)
    a, b = rng.normal(0, 1, 30), rng.normal(1, 1, 30)
    o = st.compare(["a", "b"], [a, b], "auto")
    assert o.test == "welch_t" and "Shapiro" in o.reason
    skew = rng.exponential(1, 30) ** 3
    assert st.compare(["a", "b"], [a, skew], "auto").test == "mann_whitney"
    assert st.compare(["a", "b"], [a[:14], b], "auto").reason == "smallest group n = 14 < 15"
    # ANA-06: a group of 4 is dropped; one group left -> no test.
    o = st.compare(["a", "b"], [a, b[:4]], "auto")
    assert o.test is None and o.groups == ["a"]
    three = st.compare(["a", "b", "c"], [a, b[:4], b], "auto")
    assert three.test == "welch_t" and three.groups == ["a", "c"]
    assert st.compare(["a", "b"], [np.ones(10), np.ones(10)], "auto").test is None


def test_effect_sizes_by_hand() -> None:
    a = np.asarray([1.0, 2, 3, 4, 5])
    b = np.asarray([2.0, 4, 6, 8, 10])
    sp = math.sqrt((4 * a.var(ddof=1) + 4 * b.var(ddof=1)) / 8)
    assert st.cohens_d(a, b) == pytest.approx((a.mean() - b.mean()) / sp, rel=1e-15)
    assert st.rank_biserial(0, 5, 5) == -1 and st.rank_biserial(25, 5, 5) == 1
    assert st.epsilon_squared(9.0, 10) == 1.0
    t = np.asarray([[10, 0], [0, 10]])
    assert st.cramers_v(t) == pytest.approx(1.0)


def test_fisher_rxc_is_deterministic() -> None:
    t = np.asarray([[3, 4, 2], [4, 3, 4], [1, 0, 1]])
    p1 = st.contingency_test(t, "auto").p
    p2 = st.contingency_test(t, "auto").p
    assert p1 == p2 and st.contingency_test(t, "auto").test == "fisher"


def test_spearman_matrix_and_robust_z() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=(40, 4))
    x[:, 1] = x[:, 0] * 2 + 1e-3 * rng.normal(size=40)
    rho = st.spearman_matrix(x)
    assert rho[0, 2] == pytest.approx(stats.spearmanr(x[:, 0], x[:, 2]).statistic, abs=1e-12)
    assert st.threshold_clusters(rho, 0.9) == [[0, 1]]
    z = st.robust_z(np.asarray([[1.0], [2.0], [3.0], [100.0]]))
    assert z[3, 0] == pytest.approx((100 - 2.5) / (1.4826 * 1.0))
