# ruff: noqa: F811  (module-scoped fixtures imported from test_analytics_support)
"""TST-12: API-38 dashboard views over a synthetic run (DB-02/03/05/07)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import stats  # type: ignore[import-untyped]

from app.curation import state as curation_state
from tests.test_analytics_support import (  # noqa: F401  (fixtures)
    CONTRAST,
    ENERGY,
    FAILED_ITEM,
    IDM,
    MEAN,
    MEDIAN,
    OUTLIER,
    SKEW,
    SURFACE,
    VOLUME,
    Synthetic,
    mod_client,
    ok,
    syn,
    view,
)
from tests.test_contract import assert_problem

OUTLIER_ITEM = f"{OUTLIER}.01.complete.-"


@pytest.fixture
def rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Curation status badge: the outlier is `rejected` (CUR-08 reader monkeypatched)."""
    monkeypatch.setattr(curation_state, "item_statuses", lambda _p: {OUTLIER_ITEM: "rejected"})


def test_run_overview(mod_client: TestClient, syn: Synthetic) -> None:
    body = ok(view(mod_client, syn, "run-overview"))
    n_items = len(syn.items)
    assert body["n_items_ok"] == n_items and body["n_items_failed"] == 1
    assert body["n_items_selected"] == n_items + 1 and body["runtime_s"] == 150
    assert [x["label"] for x in body["per_label"]] == [1, 2]
    assert body["per_label"][1]["n_items"] == n_items
    assert body["per_label"][0]["n_items"] == n_items - 1
    assert body["n_features"] == 13
    assert body["errors"][0]["item_id"] == FAILED_ITEM
    assert {p["level"] for p in body["per_phase"]} == {"NP", "CMP"}
    # DB-02: phase filter narrows every count.
    np_only = ok(view(mod_client, syn, "run-overview", {"filters": {"phase": ["NP"]}}))
    assert np_only["n_items_ok"] == sum(a["phase"] == "NP" for a in syn.items.values())


@pytest.mark.usefixtures("rejected")
def test_feature_distribution_split_and_log(mod_client: TestClient, syn: Synthetic) -> None:
    body = ok(
        view(
            mod_client, syn, "feature-distribution",
            {"feature": MEAN, "split": {"kind": "variable", "name": "arm"}, "bins": 20,
             "filters": {"label": [2]}},
        )
    )  # fmt: skip
    assert len(body["edges"]) == 21
    levels = [g["level"] for g in body["groups"]]
    assert levels == ["A", "B", None]  # outlier case has no arm
    assert sum(sum(g["counts"]) for g in body["groups"]) == len(body["points"])
    p = next(p for p in body["points"] if p["item_id"] == OUTLIER_ITEM)
    assert p["status"] == "rejected" and p["color"] is None and p["case_id"] == OUTLIER
    assert 0 <= p["bin"] < 20
    a = next(g for g in body["groups"] if g["level"] == "A")
    vals = [syn.values[(i, 2)][MEAN] for i, x in syn.items.items()
            if syn.groups[x["case_id"]]["arm"] == "A"]  # fmt: skip
    assert a["box"]["median"] == pytest.approx(float(np.median(vals)), abs=1e-12)
    log = ok(view(mod_client, syn, "feature-distribution", {"feature": VOLUME, "log_scale": True}))
    assert log["edges"][-1] < 10  # log10 units
    # DB-07: color by curation status; DB-02 status filter.
    st = ok(view(mod_client, syn, "feature-distribution",
                 {"feature": MEAN, "split": {"kind": "curation_status"},
                  "filters": {"status": ["rejected"]}}))  # fmt: skip
    assert {p["item_id"] for p in st["points"]} == {OUTLIER_ITEM}
    assert [g["level"] for g in st["groups"]] == ["rejected"]


def test_missing_matrix(mod_client: TestClient, syn: Synthetic) -> None:
    body = ok(view(mod_client, syn, "missing-matrix", {"filters": {"label": [2]}}))
    feats = {f["feature"]: f for f in body["features"]}
    assert (feats[SKEW]["n_nan"], feats[SKEW]["n_inf"]) == (3, 1)
    assert feats[IDM]["n_absent"] == 1
    kinds = sorted(c["kind"] for c in body["cells"])
    assert kinds == ["absent", "inf", "nan", "nan", "nan"]
    assert len(body["items"]) == 5 and all(i["n_invalid"] == 1 for i in body["items"])
    only_glcm = ok(view(mod_client, syn, "missing-matrix", {"feature_class": ["glcm"]}))
    assert {f["feature_class"] for f in only_glcm["features"]} == {"glcm"}


def test_correlation(mod_client: TestClient, syn: Synthetic) -> None:
    body = ok(view(mod_client, syn, "correlation", {"filters": {"label": [2], "phase": ["NP"]}}))
    names = body["features"]
    assert len(names) == len(body["matrix"]) == len(body["matrix"][0])
    i, j = names.index(MEAN), names.index(MEDIAN)
    np_items = sorted(k for k, a in syn.items.items() if a["phase"] == "NP")
    x = [syn.values[(k, 2)][MEAN] for k in np_items]
    y = [syn.values[(k, 2)][MEDIAN] for k in np_items]
    assert body["matrix"][i][j] == pytest.approx(stats.spearmanr(x, y).statistic, abs=1e-4)
    clusters = [set(c["features"]) for c in body["clusters"]]
    assert any({MEAN, MEDIAN} <= c for c in clusters)
    assert any({VOLUME, SURFACE} <= c for c in clusters)
    assert abs(names.index(MEAN) - names.index(MEDIAN)) <= 3  # clustered order


def test_embedding(mod_client: TestClient, syn: Synthetic) -> None:
    body = ok(
        view(mod_client, syn, "embedding",
             {"n_components": 3, "color_by": {"kind": "phase"}, "filters": {"label": [2]}})
    )  # fmt: skip
    assert body["method"] == "pca" and body["n_components"] == 3
    assert len(body["explained_variance_ratio"]) == 3
    assert body["explained_variance_ratio"][0] >= body["explained_variance_ratio"][1]
    assert body["color_levels"] == ["CMP", "NP"]
    assert len(body["points"]) == len(syn.items)
    assert all(len(p["coords"]) == 3 and p["color"] in ("NP", "CMP") for p in body["points"])
    r = view(mod_client, syn, "embedding", {"method": "umap"})
    assert_problem(r, "validation")  # optional extra not installed


@pytest.mark.usefixtures("rejected")
def test_outliers_flag_the_injected_case(mod_client: TestClient, syn: Synthetic) -> None:
    body = ok(view(mod_client, syn, "outliers", {"filters": {"label": [2]}, "top_n": 5}))
    assert body["threshold"] == 3.5 and body["min_feature_pct"] == 5
    # DB-10: only flagged items are listed (≥ 5 % of the features over the threshold)
    assert 1 <= len(body["items"]) == min(5, body["n_flagged"])
    assert all(i["n_outlier_features"] >= body["min_features"] for i in body["items"])
    top = body["items"][0]
    assert top["case_id"] == OUTLIER and top["status"] == "rejected"
    assert top["max_abs_z"] > 10 and top["n_outlier_features"] >= 3
    assert {f["feature"] for f in top["top_features"]} >= {VOLUME, MEAN}
    # robust z by hand for the top feature.
    f0 = top["top_features"][0]
    col = np.asarray([syn.values[(k, 2)][f0["feature"]] for k in syn.items])
    med = np.median(col)
    mad = np.median(np.abs(col - med)) * 1.4826
    assert f0["z"] == pytest.approx((f0["value"] - med) / mad, rel=1e-9)
    assert body["features"][0]["n_outlier_items"] >= 1


def test_outliers_flag_rule_share_of_features(mod_client: TestClient, syn: Synthetic) -> None:
    """DB-10 (owner 2026-09-27): an item is flagged when ≥ min_feature_pct % of its features
    (and ≥ 1) exceed the threshold; ranking by that count, then max |z| (AUD-A2-06)."""
    req = {"filters": {"label": [2]}, "top_n": 5000, "threshold": 2.0}
    by_pct = {
        p: ok(view(mod_client, syn, "outliers", {**req, "min_feature_pct": p}))
        for p in (0, 5, 20, 100)
    }
    n_feat = by_pct[5]["n_features"]
    assert n_feat > 1
    for p, b in by_pct.items():
        assert b["min_features"] == max(1, math.ceil(p / 100 * n_feat - 1e-9))
        assert b["n_flagged"] == len(b["items"])
        assert all(i["n_outlier_features"] >= b["min_features"] for i in b["items"])
        keys = [(-i["n_outlier_features"], -i["max_abs_z"]) for i in b["items"]]
        assert keys == sorted(keys)
    flagged = [by_pct[p]["n_flagged"] for p in (0, 5, 20, 100)]
    assert flagged == sorted(flagged, reverse=True)  # a stricter share flags fewer items
    # 13 features: 5 % needs 1 (same as 0 %), 20 % needs 3, 100 % all of them
    assert [by_pct[p]["min_features"] for p in (0, 5, 20, 100)] == [1, 1, 3, n_feat]
    assert flagged[0] == flagged[1] > flagged[2] > 0 == flagged[3]
    assert by_pct[5]["items"][0]["case_id"] == by_pct[20]["items"][0]["case_id"] == OUTLIER
    assert by_pct[100]["features"] == by_pct[0]["features"]  # per-feature counts cover every item
    assert_problem(view(mod_client, syn, "outliers", {"min_feature_pct": 101}), "validation")


def test_feature_vs_volume(mod_client: TestClient, syn: Synthetic) -> None:
    body = ok(view(mod_client, syn, "feature-vs-volume",
                   {"feature": SURFACE, "filters": {"label": [2]},
                    "color_by": {"kind": "variable", "name": "arm"}}))  # fmt: skip
    assert body["volume_feature"] == VOLUME and body["size_driven"] is True
    assert body["rho"] > 0.95 and len(body["points"]) == len(syn.items)
    top = {r["feature"] for r in body["ranked"][:3]}
    assert {SURFACE, ENERGY} <= top
    noise = ok(view(mod_client, syn, "feature-vs-volume", {"feature": CONTRAST}))
    assert noise["size_driven"] is False


def test_group_comparison_view(mod_client: TestClient, syn: Synthetic) -> None:
    body = ok(view(mod_client, syn, "group-comparison", {"variable": "arm", "feature": MEAN}))
    assert body["unit"]["n_rows"] == 33 and body["unit"]["label"] == 2
    assert [g["level"] for g in body["groups"]] == ["A", "B"]
    assert body["selected"]["feature"] == MEAN and body["selected"]["q"] < 1e-6
    assert [b["level"] for b in body["boxes"]] == ["A", "B"]
    assert len(body["points"]) == 33 and body["points"][0]["item_ids"]
    assert {d["group"] for d in body["descriptives"]} == {"A", "B"}
    assert len(body["results"]) == 13


def test_association_view(mod_client: TestClient, syn: Synthetic) -> None:
    body = ok(view(mod_client, syn, "association", {"variable": "score"}))
    assert body["choice"]["default_test"] == "spearman"
    assert body["selected"]["test"] == "spearman"
    assert all(p["x"] is not None for p in body["points"])


def test_balance_view(mod_client: TestClient, syn: Synthetic) -> None:
    body = ok(view(mod_client, syn, "balance", {"variable": "site", "other": "manufacturer"}))
    t = body["table"]
    assert t["rows"] == ["S1", "S2"] and len(t["cols"]) == 5
    assert sum(c["n"] for c in t["cells"]) == 33
    cell = next(c for c in t["cells"] if c["n"] > 0)
    assert len(cell["item_ids"]) == cell["n"] and cell["case_ids"]
    assert t["result"]["test"] == "fisher" and t["result"]["p"] < 0.001


def test_phase_consistency(mod_client: TestClient, syn: Synthetic) -> None:
    body = ok(view(mod_client, syn, "phase-side-consistency",
                   {"feature": MEAN, "filters": {"label": [2]}}))  # fmt: skip
    assert (body["a"], body["b"]) == ("NP", "CMP")  # project phase priority
    assert body["n_pairs"] == 32  # the outlier case has one scan
    assert body["bias"] == pytest.approx(25, abs=2)
    diffs = [p["diff"] for p in body["points"]]
    sd = float(np.std(diffs, ddof=1))
    assert body["loa_high"] == pytest.approx(body["bias"] + 1.96 * sd, rel=1e-12)
    assert math.isfinite(body["rho"])


def test_view_problems(mod_client: TestClient, syn: Synthetic) -> None:
    c = mod_client
    assert_problem(view(c, syn, "nope", {}), "not-found")
    bad = Synthetic(syn.pid, "01JAAAAAAAAAAAAAAAAAAAAAAA", syn.pdir, {})
    assert_problem(view(c, bad, "outliers", {}), "not-found")
    assert_problem(view(c, syn, "feature-distribution", {"feature": "nope"}), "validation")
    assert_problem(view(c, syn, "feature-distribution", {}), "validation")
    assert_problem(
        view(c, syn, "feature-distribution",
             {"feature": MEAN, "split": {"kind": "variable", "name": "score"}}),
        "validation",
    )  # fmt: skip
    assert_problem(view(c, syn, "outliers", {"filters": {"var": {"nope": ["x"]}}}), "validation")
    assert_problem(view(c, syn, "group-comparison", {"variable": "grade"}), "validation")
    assert_problem(view(c, syn, "outliers", {"threshold": -1}), "validation")
