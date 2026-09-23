# ruff: noqa: F811  (module-scoped fixtures imported from test_analytics_support)
"""TST-12: API-39 guided statistics vs SciPy on the same unit rows (ANA-01..10, REC-*).

Unit rows come from the ANA-09 tidy export, so every check re-computes the statistic
directly with SciPy on exactly what the analysis used.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import stats  # type: ignore[import-untyped]

from tests.test_analytics_support import (  # noqa: F401  (fixtures)
    API,
    CONTRAST,
    MEAN,
    NOISE,
    OUTLIER,
    SKEW,
    Synthetic,
    analyze,
    mod_client,
    ok,
    syn,
)
from tests.test_contract import assert_problem

TOL = 1e-12


def tidy(c: TestClient, s: Synthetic, aid: str) -> list[dict[str, str]]:
    r = c.get(f"{API}/projects/{s.pid}/analyses/{aid}/export", params={"file": "tidy"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    return list(csv.DictReader(io.StringIO(r.text)))


def fl(v: str) -> float:
    return float(v) if v != "" else math.nan


def groups_of(rows: list[dict[str, str]], var: str, feature: str) -> dict[str, np.ndarray]:
    out: dict[str, list[float]] = {}
    for r in rows:
        x = fl(r[feature])
        if r[var] != "" and math.isfinite(x):
            out.setdefault(r[var], []).append(x)
    return {k: np.asarray(v) for k, v in sorted(out.items())}


def codes(a: dict[str, Any]) -> set[str]:
    return {r["code"] for r in a["recommendations"]}


def close(a: float | None, b: float) -> None:
    assert a is not None
    assert a == pytest.approx(b, rel=TOL, abs=TOL)


def check_bh(a: dict[str, Any]) -> None:
    rows = [r for r in a["results"] if r["p"] is not None]
    q = stats.false_discovery_control([r["p"] for r in rows], method="bh")
    for r, qq in zip(rows, q, strict=True):
        close(r["q"], float(qq))
    keys = [(r["q"] if r["q"] is not None else math.inf) for r in a["results"]]
    assert keys == sorted(keys)  # ANA-05 sort by q


@pytest.fixture(scope="module")
def derived(mod_client: TestClient, syn: Synthetic) -> None:
    """VAR-06 derived variables via API-17: bin marker_a at 50, score by tertiles."""
    url = f"{API}/projects/{syn.pid}/variables/derived"
    for d in (
        {"op": "bin", "name": "marker_hi", "source": "marker_a", "thresholds": [50],
         "labels": ["low", "high"]},
        {"op": "bin", "name": "score_t", "source": "score", "quantiles": [1 / 3, 2 / 3],
         "labels": ["t1", "t2", "t3"]},
    ):  # fmt: skip
        ok(mod_client.post(url, json=d), 201)


# -- test choice paths vs SciPy -------------------------------------------------------------


def test_two_groups_welch_and_mann_whitney(mod_client: TestClient, syn: Synthetic) -> None:
    a = ok(analyze(mod_client, syn, question="compare", variable="arm", name="arm"), 201)
    assert a["unit"]["n_rows"] == 33 and a["unit"]["n_variable_missing"] == 1
    assert [(g["level"], g["n"]) for g in a["groups"]] == [("A", 16), ("B", 16)]
    assert a["choice"]["default_test"] == "welch_t"
    rows = tidy(mod_client, syn, a["analysis_id"])
    seen = set()
    for r in a["results"]:
        g = groups_of(rows, "arm", r["feature"])
        x, y = g["A"], g["B"]
        normal = all(stats.shapiro(v).pvalue >= 0.05 for v in (x, y))
        assert r["test"] == ("welch_t" if normal else "mann_whitney"), r
        seen.add(r["test"])
        if r["test"] == "welch_t":
            t = stats.ttest_ind(x, y, equal_var=False)
            sp = math.sqrt(((x.size - 1) * x.var(ddof=1) + (y.size - 1) * y.var(ddof=1))
                           / (x.size + y.size - 2))  # fmt: skip
            close(r["statistic"], t.statistic)
            close(r["p"], t.pvalue)
            close(r["effect"], (x.mean() - y.mean()) / sp)
            assert r["effect_name"] == "cohens_d"
        else:
            u = stats.mannwhitneyu(x, y, alternative="two-sided")
            close(r["statistic"], u.statistic)
            close(r["p"], u.pvalue)
            close(r["effect"], 2 * u.statistic / (x.size * y.size) - 1)
        assert r["n"] == x.size + y.size
    assert "welch_t" in seen
    check_bh(a)
    top = a["results"][0]["feature"]
    assert top in (MEAN, "original_firstorder_Median", "original_shape_MeshVolume",
                   "original_shape_SurfaceArea", "original_firstorder_Energy")  # fmt: skip
    # ANA-04: the user forces the alternative.
    alt = ok(analyze(mod_client, syn, question="compare", variable="arm", test="alternative"), 201)
    assert {r["test"] for r in alt["results"]} == {"mann_whitney"}
    assert "forced" in alt["choice"]["reason"]
    # REC-VOLUME, REC-REDUNDANT on the arm comparison.
    assert {"REC-VOLUME", "REC-REDUNDANT"} <= codes(a)
    vol = next(x for x in a["recommendations"] if x["code"] == "REC-VOLUME")
    assert vol["view"] == "feature-vs-volume" and vol["params"]["feature"]
    assert "REC-NO-SIGNAL" not in codes(a) and "REC-NONINDEP" not in codes(a)


def test_three_groups_kruskal_and_welch_anova(mod_client: TestClient, syn: Synthetic) -> None:
    # ANA-03 default unit: 11 cases per group < 15 -> Kruskal-Wallis for every feature.
    a = ok(analyze(mod_client, syn, question="compare", variable="arm3"), 201)
    assert a["choice"]["default_test"] == "welch_anova"
    assert a["choice"]["reason"] == "smallest group n = 11 < 15"
    rows = tidy(mod_client, syn, a["analysis_id"])
    for r in a["results"]:
        g = list(groups_of(rows, "arm3", r["feature"]).values())
        k = stats.kruskal(*g)
        n = sum(v.size for v in g)
        assert r["test"] == "kruskal_wallis"
        close(r["statistic"], k.statistic)
        close(r["p"], k.pvalue)
        close(r["effect"], k.statistic / (n - 1))
    assert a["results"][0]["feature"] == CONTRAST
    check_bh(a)
    # Every item as a row (~22 per group): Welch ANOVA where normal; REC-NONINDEP.
    b = ok(analyze(mod_client, syn, question="compare", variable="arm3",
                   unit={"aggregate": "none"}), 201)  # fmt: skip
    assert b["unit"]["n_rows"] == 65 and "REC-NONINDEP" in codes(b)
    rows = tidy(mod_client, syn, b["analysis_id"])
    assert len(rows) == 65
    seen = set()
    for r in b["results"]:
        g = list(groups_of(rows, "arm3", r["feature"]).values())
        normal = all(stats.shapiro(v).pvalue >= 0.05 for v in g)
        seen.add(r["test"])
        if not normal:
            assert r["test"] == "kruskal_wallis"
            continue
        assert r["test"] == "welch_anova"
        f = stats.f_oneway(*g, equal_var=False)
        allv = np.concatenate(g)
        eta = sum(v.size * (v.mean() - allv.mean()) ** 2 for v in g) / (
            ((allv - allv.mean()) ** 2).sum()
        )
        close(r["statistic"], f.statistic)
        close(r["p"], f.pvalue)
        close(r["effect"], eta)
    assert "welch_anova" in seen
    check_bh(b)


def test_association_spearman_and_pearson(mod_client: TestClient, syn: Synthetic) -> None:
    a = ok(analyze(mod_client, syn, question="association", variable="score"), 201)
    assert a["choice"]["default_test"] == "spearman"
    rows = tidy(mod_client, syn, a["analysis_id"])
    x = np.asarray([fl(r["score"]) for r in rows])
    for r in a["results"]:
        y = np.asarray([fl(row[r["feature"]]) for row in rows])
        m = np.isfinite(x) & np.isfinite(y)
        s = stats.spearmanr(x[m], y[m])
        assert r["test"] == "spearman" and r["n"] == int(m.sum())
        close(r["statistic"], s.statistic)
        close(r["p"], s.pvalue)
        close(r["effect"], s.statistic)
    check_bh(a)
    b = ok(analyze(mod_client, syn, question="association", variable="score",
                   test="alternative"), 201)  # fmt: skip
    for r in b["results"]:
        y = np.asarray([fl(row[r["feature"]]) for row in rows])
        m = np.isfinite(x) & np.isfinite(y)
        p = stats.pearsonr(x[m], y[m])
        assert r["test"] == "pearson" and r["effect_name"] == "pearson_r"
        close(r["statistic"], p.statistic)
        close(r["p"], p.pvalue)


def _table(rows: list[dict[str, str]], a: str, b: str) -> np.ndarray:
    ra = sorted({r[a] for r in rows if r[a] and r[b]})
    cb = sorted({r[b] for r in rows if r[a] and r[b]})
    return np.asarray([[sum(r[a] == x and r[b] == y for r in rows) for y in cb] for x in ra])


def cramers_v(t: np.ndarray) -> float:
    chi2 = stats.chi2_contingency(t, correction=False).statistic
    return math.sqrt(chi2 / (t.sum() * (min(t.shape) - 1)))


def test_balance_chi2_and_fisher(mod_client: TestClient, syn: Synthetic) -> None:
    # 2x2 with all expected >= 5 -> chi2 (SciPy default Yates correction).
    a = ok(analyze(mod_client, syn, question="balance", variable="arm", confounder="site"), 201)
    rows = tidy(mod_client, syn, a["analysis_id"])
    t = _table(rows, "arm", "site")
    chi = stats.chi2_contingency(t)
    assert (chi.expected_freq >= 5).all()
    r = a["results"][0]
    assert r["test"] == "chi2" and a["balance"]["result"]["test"] == "chi2"
    close(r["statistic"], chi.statistic)
    close(r["p"], chi.pvalue)
    close(r["effect"], cramers_v(t))
    assert sum(c["n"] for c in a["balance"]["cells"]) == t.sum()
    # Forced alternative on 2x2 -> exact Fisher.
    f = ok(analyze(mod_client, syn, question="balance", variable="arm", confounder="site",
                   test="alternative"), 201)  # fmt: skip
    fe = stats.fisher_exact(t)
    close(f["results"][0]["statistic"], fe.statistic)
    close(f["results"][0]["p"], fe.pvalue)
    # R x C with expected < 5 -> Fisher (seeded permutation) + REC-CONFOUNDER.
    b = ok(analyze(mod_client, syn, question="balance", variable="site",
                   confounder="manufacturer"), 201)  # fmt: skip
    rows = tidy(mod_client, syn, b["analysis_id"])
    t = _table(rows, "site", "manufacturer")
    m = stats.PermutationMethod(n_resamples=9999, rng=np.random.default_rng(0))
    ref = stats.fisher_exact(t, method=m)
    r = b["results"][0]
    assert r["test"] == "fisher" and "expected count" in r["reason"]
    close(r["statistic"], ref.statistic)
    close(r["p"], ref.pvalue)
    close(r["effect"], cramers_v(t))
    assert "REC-CONFOUNDER" in codes(b)


# -- unit, min n, derived variables ---------------------------------------------------------


def test_unit_first_by_priority_vs_mean(mod_client: TestClient, syn: Synthetic) -> None:
    first = ok(analyze(mod_client, syn, question="explore"), 201)
    rows = {r["case_id"]: r for r in tidy(mod_client, syn, first["analysis_id"])}
    expect = syn.unit_first(MEAN)
    assert set(rows) == set(expect) and len(rows) == 33
    for cid, v in expect.items():
        assert rows[cid]["phase"] == "NP"
        assert float(rows[cid][MEAN]) == v
    mean = ok(analyze(mod_client, syn, question="explore", unit={"aggregate": "mean"}), 201)
    rows = {r["case_id"]: r for r in tidy(mod_client, syn, mean["analysis_id"])}
    for cid, v in syn.unit_mean(MEAN).items():
        assert float(rows[cid][MEAN]) == pytest.approx(v, rel=TOL)
        assert len(rows[cid]["item_ids"].split(";")) == (1 if cid == OUTLIER else 2)
    assert mean["unit"]["max_items_per_case"] == 2
    # Explore: descriptives only (ANA-07), REC-MODALITY (the MR scan is averaged in).
    assert first["results"] == [] and first["choice"]["default_test"] is None
    d = next(x for x in first["descriptives"] if x["feature"] == SKEW)
    assert d["n"] + d["missing"] == 33 and d["missing"] >= 1
    assert "REC-MODALITY" not in codes(first) and "REC-MODALITY" in codes(mean)
    assert "REC-REDUNDANT" in codes(first)


def test_min_n_small_groups_and_imbalance(mod_client: TestClient, syn: Synthetic) -> None:
    a = ok(analyze(mod_client, syn, question="compare", variable="tiny"), 201)
    g = {x["level"]: x for x in a["groups"]}
    assert (g["small"]["n"], g["small"]["excluded"]) == (3, True)  # ANA-06
    assert g["mid"]["excluded"] is False and g["big"]["n"] == 24
    assert all("small" not in r["groups"] for r in a["results"])
    assert {d["group"] for d in a["descriptives"]} == {"small", "mid", "big"}
    small = next(d for d in a["descriptives"] if d["group"] == "small" and d["feature"] == MEAN)
    assert small["excluded"] is True and small["n"] == 3
    vals = np.asarray(sorted(syn.unit_first(MEAN)[f"case_{n:05d}"] for n in (30, 31, 32)))
    q1, med, q3 = np.percentile(vals, [25, 50, 75])
    close(small["median"], med)
    close(small["iqr"], q3 - q1)
    close(small["sd"], vals.std(ddof=1))
    assert a["results"][0]["test"] == "mann_whitney"  # 2 groups left, n < 15
    assert {"REC-SMALL-N", "REC-IMBALANCE"} <= codes(a)


def test_derived_two_group_comparison(
    mod_client: TestClient, syn: Synthetic, derived: None
) -> None:
    a = ok(analyze(mod_client, syn, question="compare", variable="marker_hi"), 201)
    assert [x["level"] for x in a["groups"]] == ["high", "low"]
    assert all(r["q"] is not None for r in a["results"] if r["p"] is not None)
    assert a["results"][0]["q"] is not None
    assert {"REC-MISSING", "REC-COMPOSITIONAL", "REC-SMALL-N"} <= codes(a)
    miss = next(x for x in a["recommendations"] if x["code"] == "REC-MISSING")
    assert "of 33 cases" in miss["message"]
    rows = tidy(mod_client, syn, a["analysis_id"])
    r = next(x for x in a["results"] if x["feature"] == MEAN)
    g = groups_of(rows, "marker_hi", MEAN)
    u = stats.mannwhitneyu(g["high"], g["low"], alternative="two-sided")
    close(r["p"], u.pvalue)
    check_bh(a)


def test_derived_three_group_comparison(
    mod_client: TestClient, syn: Synthetic, derived: None
) -> None:
    a = ok(analyze(mod_client, syn, question="compare", variable="score_t"), 201)
    assert [x["level"] for x in a["groups"]] == ["t1", "t2", "t3"]
    assert a["choice"]["alternative_test"] == "kruskal_wallis"
    assert all(r["test"] == "kruskal_wallis" for r in a["results"])
    assert all(r["q"] is not None for r in a["results"])
    assert len(a["recommendations"]) >= 1
    check_bh(a)


# -- remaining REC rules --------------------------------------------------------------------


def test_rec_confounder_on_grouping(mod_client: TestClient, syn: Synthetic) -> None:
    a = ok(analyze(mod_client, syn, question="compare", variable="site"), 201)
    rec = next(x for x in a["recommendations"] if x["code"] == "REC-CONFOUNDER")
    assert rec["view"] == "balance" and rec["params"]["other"] == "manufacturer"


def test_rec_no_signal(mod_client: TestClient, syn: Synthetic) -> None:
    a = ok(analyze(mod_client, syn, question="compare", variable="coin", features=list(NOISE)),
           201)  # fmt: skip
    assert len(a["results"]) == len(NOISE)
    assert all(r["q"] >= 0.1 for r in a["results"])
    assert "REC-NO-SIGNAL" in codes(a)


def test_rec_modality_in_cmp_unit(mod_client: TestClient, syn: Synthetic) -> None:
    a = ok(analyze(mod_client, syn, question="compare", variable="arm", unit={"phase": "CMP"}),
           201)  # fmt: skip
    assert a["unit"]["phase"] == "CMP" and a["unit"]["n_rows"] == 32
    rec = next(x for x in a["recommendations"] if x["code"] == "REC-MODALITY")
    assert "MR" in rec["message"] and rec["params"]["split"] == "modality"


# -- storage, list, export, problems --------------------------------------------------------


def test_storage_list_get_and_exports(mod_client: TestClient, syn: Synthetic) -> None:
    c = mod_client
    a = ok(
        c.post(f"{API}/projects/{syn.pid}/analyses", headers={"X-Reviewer": "Dr. T"},
               json={"run_id": syn.run_id, "question": "compare", "variable": "arm",
                     "name": "stored", "filters": {"var": {"site": ["S2"]}}}),
        201,
    )  # fmt: skip
    aid = a["analysis_id"]
    assert a["created_by"] == "Dr. T" and a["unit"]["n_rows"] < 33
    d = syn.pdir / "analyses" / aid
    for f in ("spec.json", "results.parquet", "descriptives.parquet", "recommendations.json",
              "exports/tidy.csv", "exports/results.csv", "exports/spec.json"):  # fmt: skip
        assert (d / f).is_file(), f
    got = ok(c.get(f"{API}/projects/{syn.pid}/analyses/{aid}"))
    assert got["results"] == a["results"] and got["recommendations"] == a["recommendations"]
    assert got["descriptives"] == a["descriptives"] and got["spec"]["name"] == "stored"
    lst = ok(c.get(f"{API}/projects/{syn.pid}/analyses", params={"run_id": syn.run_id}))
    row = next(x for x in lst["items"] if x["analysis_id"] == aid)
    assert row["n_tested"] == len(a["results"]) and lst["total"] == len(lst["items"])
    res = c.get(f"{API}/projects/{syn.pid}/analyses/{aid}/export", params={"file": "results"})
    table = list(csv.DictReader(io.StringIO(res.text)))
    assert [r["feature"] for r in table] == [r["feature"] for r in a["results"]]
    assert float(table[0]["q"]) == a["results"][0]["q"]
    spec = c.get(f"{API}/projects/{syn.pid}/analyses/{aid}/export", params={"file": "spec"})
    assert spec.headers["content-type"].startswith("application/json")
    body = json.loads(spec.text)
    assert body["spec"]["filters"]["var"] == {"site": ["S2"]} and body["analysis_id"] == aid
    rows = tidy(c, syn, aid)
    assert {r["site"] for r in rows} == {"S2"} and "patient_id" not in rows[0]  # VAR-09
    assert MEAN in rows[0] and "arm" in rows[0]


def test_analysis_problems(mod_client: TestClient, syn: Synthetic) -> None:
    c = mod_client
    base = f"{API}/projects/{syn.pid}/analyses"
    assert_problem(c.get(f"{base}/01JAAAAAAAAAAAAAAAAAAAAAAA"), "not-found")
    assert_problem(c.get(f"{base}/nope/export"), "not-found")
    assert_problem(
        c.post(base, json={"run_id": "01JAAAAAAAAAAAAAAAAAAAAAAA", "question": "explore"}),
        "not-found",
    )
    assert_problem(c.post(base, json={"run_id": "../x", "question": "explore"}), "not-found")
    for spec in (
        {"question": "paired", "variable": "arm"},  # ANA-10 is v3.1
        {"question": "compare", "variable": "grade"},  # unconfirmed numeric-discrete
        {"question": "compare"},
        {"question": "compare", "variable": "nope"},
        {"question": "compare", "variable": "score"},  # continuous
        {"question": "association", "variable": "arm"},
        {"question": "balance", "variable": "arm"},
        {"question": "compare", "variable": "arm", "features": ["nope"]},
        {"question": "compare", "variable": "arm", "filters": {"var": {"arm": ["A"]}}},
        {"question": "explore", "unit": {"label": 9}},
        {"question": "nonsense"},
    ):
        assert_problem(analyze(c, syn, **spec), "validation")
    r = analyze(c, syn, question="compare", variable="grade")
    assert "confirm" in r.json()["detail"]
    aid = ok(analyze(c, syn, question="explore"), 201)["analysis_id"]
    assert_problem(c.get(f"{base}/{aid}/export", params={"file": "zip"}), "validation")
