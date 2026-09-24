"""P5/P6 exit over the synthetic fixtures with the real engine (RAD-*, DB-*, ANA-*).

Import → PyRadiomics run on the cohort + injected outlier (tumor label, NP phase) → the
outlier view flags the defect with an item_id the viewer opens (DB-03) → two- and
three-group comparisons on derived variables match SciPy, with q-values and ≥ 1
recommendation (ANA-04/05/08).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from scipy import stats

from tests.test_api_ingest import API, ctx_of, do_import, wait

pytest.importorskip("radiomics")

WHO = {"X-Reviewer": "E2E"}
TUMOR = 2


def test_outlier_and_group_comparisons_on_real_run(
    client: TestClient, data_root: Path, fixtures_copy: Path
) -> None:
    expected = json.loads((fixtures_copy / "expected.json").read_text())
    pid = client.post(f"{API}/projects", json={"name": "e2e", "packs": ["ccrcc"]}).json()[
        "project_id"
    ]
    do_import(client, pid, data_root)
    cases = [*expected["cohort"], *expected["radiomics_outlier"]]
    items = [f"{c}.01.complete.-" for c in cases]
    body = {
        "name": "NP tumor",
        "selection": {"item_ids": items, "scope": "complete", "labels": [TUMOR]},
    }
    r = client.post(f"{API}/projects/{pid}/radiomics/runs", json=body, headers=WHO)
    assert r.status_code in (201, 202), r.text
    run = r.json()
    rid = run["run_id"]
    if run.get("job_id"):
        wait(client, run["job_id"])
    run = client.get(f"{API}/projects/{pid}/radiomics/runs/{rid}").json()
    assert run["status"] == "completed", run
    assert run["counts"]["ok"] == len(items)

    # DB-03/exit: the injected defect is the top outlier and carries an openable item_id.
    r = client.post(f"{API}/projects/{pid}/radiomics/runs/{rid}/views/outliers", json={})
    assert r.status_code == 200, r.text
    out = r.json()
    top = out["items"][0]
    assert top["case_id"] == expected["radiomics_outlier"][0]
    assert client.get(f"{API}/projects/{pid}/items/{top['item_id']}").status_code == 200

    # Derived grouping variables (VAR-06): 2 groups and 3 groups.
    derived = f"{API}/projects/{pid}/variables/derived"
    two = {"op": "bin", "name": "marker_hi", "source": "marker_a", "thresholds": [50]}
    three = {"op": "bin", "name": "score3", "source": "score", "quantiles": [1 / 3, 2 / 3]}
    for d in (two, three):
        assert client.post(derived, json=d).status_code == 201

    for name, n_groups in (("marker_hi", 2), ("score3", 3)):
        spec = {"run_id": rid, "question": "compare", "variable": name, "unit": {"label": TUMOR}}
        r = client.post(f"{API}/projects/{pid}/analyses", json=spec, headers=WHO)
        assert r.status_code == 201, r.text
        a = r.json()
        results = a["results"]
        assert results and all(row["q"] is not None for row in results if row["p"] is not None)
        assert a["recommendations"], "at least one recommendation (ANA-08)"
        # Recompute the first result with SciPy on the tidy export (TST-12).
        tidy = client.get(
            f"{API}/projects/{pid}/analyses/{a['analysis_id']}/export", params={"file": "tidy"}
        )
        assert tidy.status_code == 200
        _check_against_scipy(tidy.content, name, results[0], n_groups)


def _check_against_scipy(csv: bytes, var: str, row: dict[str, Any], n_groups: int) -> None:
    import pyarrow.csv as pacsv

    t = pacsv.read_csv(io.BytesIO(csv)).to_pydict()
    feat = row["feature"]
    groups: dict[str, list[float]] = {}
    for g, v in zip(t[var], t[feat], strict=True):
        if g not in (None, "") and v is not None:
            groups.setdefault(str(g), []).append(float(v))
    samples = [g for g in groups.values() if len(g) >= 5]
    assert len(samples) == n_groups
    test = row["test"]
    if test == "welch_t":
        ref = stats.ttest_ind(*samples, equal_var=False).pvalue
    elif test == "mann_whitney":
        ref = stats.mannwhitneyu(*samples, alternative="two-sided").pvalue
    elif test == "welch_anova":
        ref = stats.f_oneway(*samples, equal_var=False).pvalue
    elif test in ("kruskal", "kruskal_wallis"):
        ref = stats.kruskal(*samples).pvalue
    else:
        raise AssertionError(f"unexpected test {test}")
    assert row["p"] == pytest.approx(float(ref), rel=1e-9, abs=1e-12)


def test_features_parquet_long_schema(client: TestClient, data_root: Path) -> None:
    """RAD-10 output columns (no study variables copied into features)."""
    pid = client.post(f"{API}/projects", json={"name": "cols", "packs": ["ccrcc"]}).json()[
        "project_id"
    ]
    do_import(client, pid, data_root)
    body = {"selection": {"item_ids": ["case_00030.01.complete.-"], "labels": [TUMOR]}}
    run = client.post(f"{API}/projects/{pid}/radiomics/runs", json=body, headers=WHO).json()
    if run.get("job_id"):
        wait(client, run["job_id"])
    f = ctx_of(client).workspace.project_dir(pid) / "radiomics/runs" / run["run_id"]
    cols = pq.read_schema(f / "features.parquet").names
    assert cols == [
        "run_id", "item_id", "case_id", "scan_idx", "scope", "side", "phase", "label",
        "image_type", "feature_class", "feature", "value", "ibsi_code", "ibsi_status",
    ]  # fmt: skip
