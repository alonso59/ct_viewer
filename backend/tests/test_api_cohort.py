"""Cohort read endpoints (COH-03 rows, COH-06 column summary): unit tests on small
in-memory tables, then the synthetic fixture project with filter parity to the cases
endpoint on the same variable filters."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

from app.cohort.models import (
    CohortBalanceRequest,
    RowsRequest,
    RowsResponse,
    SummaryBin,
    SummaryRequest,
)
from app.cohort.service import CohortService
from app.core.errors import ValidationProblem
from app.ingest.models import CaseSummary
from app.variables.models import Catalog, Profile, Variable
from tests.test_api_ingest import API, do_import
from tests.test_contract import assert_problem


def _var(name: str, vtype: str, level: str) -> Variable:
    return Variable(
        name=name,
        source="metadata",
        type=vtype,
        inferred_type=vtype,
        level=level,
        group="study",
        visible=True,
        confidence=1.0,
        review=False,
        profile=Profile(n_units=1, n_missing=0, missing_pct=0.0, distinct=1),
    )


CATALOG = Catalog(
    variables=[
        _var("kvp", "continuous", "scan"),
        _var("manufacturer", "categorical", "case"),
        _var("marker_a", "categorical", "case"),
        _var("scan_date", "date", "scan"),
    ]
)

_SCHEMA = pa.schema(
    [
        pa.field("item_id", pa.string()),
        pa.field("case_id", pa.string()),
        pa.field("scan_idx", pa.string()),
        pa.field("scope", pa.string()),
        pa.field("phase", pa.string()),
        pa.field("kvp", pa.float64()),
        pa.field("manufacturer", pa.string()),
        pa.field("marker_a", pa.string()),
        pa.field("scan_date", pa.string()),
    ]
)


def _table(rows: list[dict[str, Any]]) -> pa.Table:
    return pa.Table.from_pydict({k: [r[k] for r in rows] for k in _SCHEMA.names}, schema=_SCHEMA)


def _row(
    item_id: str,
    case_id: str,
    scan_idx: str,
    scope: str = "complete",
    phase: str = "NC",
    kvp: float | None = 100.0,
    manufacturer: str = "",
    marker_a: str = "A",
    scan_date: str = "2021-01-01",
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "case_id": case_id,
        "scan_idx": scan_idx,
        "scope": scope,
        "phase": phase,
        "kvp": kvp,
        "manufacturer": manufacturer,
        "marker_a": marker_a,
        "scan_date": scan_date,
    }


_TABLE = _table(
    [
        _row("c1.01.complete.-", "c1", "01", kvp=120.0, manufacturer="SIEMENS"),
        _row("c1.02.complete.-", "c1", "02", phase="CMP", kvp=140.0, manufacturer="SIEMENS"),
        _row("c1.03.voi.L", "c1", "03", scope="voi", phase="NP", kvp=90.0, manufacturer="SIEMENS"),
        _row(
            "c2.01.complete.-",
            "c2",
            "01",
            kvp=110.0,
            manufacturer="GE",
            marker_a="B",
            scan_date="2021-02-01",
        ),
    ]
)


class _StubVariables:
    def __init__(self, table: pa.Table | None, vocab: list[str] = ()) -> None:
        self.workspace = SimpleNamespace(get=lambda pid: SimpleNamespace(phase_vocabulary=vocab))
        self._table = table

    async def catalog(self, pid: str) -> Catalog:
        return CATALOG

    async def table(self, pid: str, columns: list[str] | None) -> pa.Table | None:
        if self._table is None:
            return None
        return self._table.select(columns) if columns else self._table


def _item(item_id: str, case_id: str, status: str = "active", modality: str = "CT"):
    return SimpleNamespace(item_id=item_id, case_id=case_id, status=status, modality=modality)


def _service(
    table: pa.Table | None = _TABLE,
    vocab: list[str] = (),
    items: list[SimpleNamespace] | None = None,
) -> CohortService:
    cases = [
        CaseSummary(case_id="c1", patient_id="P1", phases=["NC", "CMP", "NP"]),
        CaseSummary(case_id="c2", patient_id="P2", phases=["NC"]),
    ]
    items = items or [
        _item("c1.01.complete.-", "c1"),
        _item("c1.02.complete.-", "c1"),
        _item("c1.03.voi.L", "c1"),
        _item("c2.01.complete.-", "c2", modality="MR"),
    ]
    return CohortService(
        _StubVariables(table, vocab),
        SimpleNamespace(load=lambda pid: SimpleNamespace(cases=cases, items=items)),
    )


def test_rows_differs_case_level_and_scan_unit() -> None:
    resp = asyncio.run(
        _service().rows("p", RowsRequest(columns=["kvp", "manufacturer", "marker_a"]))
    )
    assert resp.n_cases == 2 and resp.n_scans == 3  # the voi item is not a scan
    c1, c2 = resp.rows
    assert c1.differs == ["kvp"]
    assert c1.values == {"kvp": None, "manufacturer": "SIEMENS", "marker_a": "A"}
    assert [s.values["kvp"] for s in c1.scans] == [120.0, 140.0]
    assert [s.phase for s in c1.scans] == ["NC", "CMP"]
    assert [s.modality for s in c1.scans] == ["CT", "CT"]
    assert c2.differs == [] and c2.values["kvp"] == 110.0
    assert c2.scans[0].modality == "MR"


def test_rows_paging_and_sort() -> None:
    svc = _service()
    first = asyncio.run(svc.rows("p", RowsRequest(columns=["marker_a"], limit=1)))
    assert first.n_cases == 2 and [r.case_id for r in first.rows] == ["c1"]
    second = asyncio.run(svc.rows("p", RowsRequest(columns=["marker_a"], offset=1)))
    assert [r.case_id for r in second.rows] == ["c2"]
    desc = asyncio.run(
        svc.rows("p", RowsRequest(columns=["marker_a"], sort={"column": "marker_a", "desc": True}))
    )
    assert [r.case_id for r in desc.rows] == ["c2", "c1"]
    # A differing column reads as missing and sorts last, in both directions.
    for desc_ in (True, False):
        got = asyncio.run(
            svc.rows("p", RowsRequest(columns=["kvp"], sort={"column": "kvp", "desc": desc_}))
        )
        assert [r.case_id for r in got.rows] == ["c2", "c1"]
    cid = asyncio.run(svc.rows("p", RowsRequest(sort={"column": "case_id", "desc": True})))
    assert [r.case_id for r in cid.rows] == ["c2", "c1"]


def test_rows_q_phase_and_validation() -> None:
    svc = _service(vocab=["NC", "CMP"])
    assert [r.case_id for r in asyncio.run(svc.rows("p", RowsRequest(q="p2"))).rows] == ["c2"]
    assert [r.case_id for r in asyncio.run(svc.rows("p", RowsRequest(q="C1"))).rows] == ["c1"]
    assert [r.case_id for r in asyncio.run(svc.rows("p", RowsRequest(phase="CMP"))).rows] == ["c1"]
    assert asyncio.run(svc.rows("p", RowsRequest(q="nobody"))).rows == []
    with pytest.raises(ValidationProblem):
        asyncio.run(svc.rows("p", RowsRequest(columns=["nope"])))
    with pytest.raises(ValidationProblem):
        asyncio.run(svc.rows("p", RowsRequest(filters={"nope": ["x"]})))
    with pytest.raises(ValidationProblem):
        asyncio.run(svc.rows("p", RowsRequest(columns=["kvp"], sort={"column": "marker_a"})))
    with pytest.raises(ValidationProblem):
        asyncio.run(svc.rows("p", RowsRequest(phase="ZZZ")))


def test_rows_empty_table() -> None:
    resp = asyncio.run(_service(None).rows("p", RowsRequest(columns=["kvp"])))
    assert resp == RowsResponse(n_cases=0, n_scans=0)


def test_rows_hide_fully_excluded_cases() -> None:
    items = [
        _item("c1.01.complete.-", "c1", status="excluded_upstream"),
        _item("c1.02.complete.-", "c1", status="excluded_upstream"),
        _item("c2.01.complete.-", "c2", modality="MR"),
    ]
    svc = _service(items=items)
    resp = asyncio.run(svc.rows("p", RowsRequest(columns=["kvp"])))
    assert [r.case_id for r in resp.rows] == ["c2"]
    b = asyncio.run(svc.summary("p", SummaryRequest(column="kvp")))
    assert b.bins == [SummaryBin(lo="110", hi="110", count=1)]


def test_summary_categorical_and_filters() -> None:
    svc = _service()
    b = asyncio.run(svc.summary("p", SummaryRequest(column="manufacturer")))
    assert b.counts == {"SIEMENS": 1, "GE": 1}  # case-level: once per case
    assert b.other == 0 and b.missing == 0 and b.bins is None
    b = asyncio.run(
        svc.summary("p", SummaryRequest(column="manufacturer", filters={"manufacturer": ["GE"]}))
    )
    assert b.counts == {"GE": 1}


def test_summary_top20_other() -> None:
    rows = [_row(f"c{i}.01.complete.-", f"c{i}", "01", manufacturer=f"m{i}") for i in range(25)]
    items = [_item(f"c{i}.01.complete.-", f"c{i}") for i in range(25)]
    svc = _service(_table(rows), items=items)
    b = asyncio.run(svc.summary("p", SummaryRequest(column="manufacturer")))
    assert len(b.counts or {}) == 20 and b.other == 5 and b.missing == 0


def test_summary_numeric_bins() -> None:
    b = asyncio.run(_service().summary("p", SummaryRequest(column="kvp")))
    assert b.counts is None and b.missing == 0
    bins = b.bins
    assert bins is not None and len(bins) == 20
    assert bins[0].lo == "110" and bins[-1].hi == "140"
    assert sum(x.count for x in bins) == 3


def test_summary_single_value_bin() -> None:
    rows = [_row(f"c{i}.01.complete.-", f"c{i}", "01", manufacturer="M") for i in range(2)]
    items = [_item(f"c{i}.01.complete.-", f"c{i}") for i in range(2)]
    svc = _service(_table(rows), items=items)
    b = asyncio.run(svc.summary("p", SummaryRequest(column="kvp")))
    assert b.bins == [SummaryBin(lo="100", hi="100", count=2)]


def test_summary_date_bins_and_missing() -> None:
    b = asyncio.run(_service().summary("p", SummaryRequest(column="scan_date")))
    assert b.bins is not None and len(b.bins) == 20
    assert b.bins[0].lo == "2021-01-01" and b.bins[-1].hi == "2021-02-01"
    d = _TABLE.to_pylist()
    d[0]["kvp"] = None
    b = asyncio.run(_service(_table(d)).summary("p", SummaryRequest(column="kvp")))
    assert b.missing == 1
    assert sum(x.count for x in b.bins or []) == 2


@pytest.fixture
def pid(client: TestClient, data_root: Path) -> str:
    r = client.post(f"{API}/projects", json={"name": "cohort", "packs": ["ccrcc"]})
    assert r.status_code == 201, r.text
    p = str(r.json()["project_id"])
    do_import(client, p, data_root)
    return p


def rows_url(pid: str) -> str:
    return f"{API}/projects/{pid}/cohort/rows"


def sum_url(pid: str) -> str:
    return f"{API}/projects/{pid}/cohort/summary"


def post_rows(client: TestClient, pid: str, **body: Any) -> dict[str, Any]:
    r = client.post(rows_url(pid), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def case_ids(client: TestClient, pid: str, **params: Any) -> set[str]:
    r = client.get(f"{API}/projects/{pid}/cases", params={**params, "limit": 2000})
    assert r.status_code == 200, r.text
    return {c["case_id"] for c in r.json()["items"]}


def test_rows_paging_differs_and_scan_fields(client: TestClient, pid: str) -> None:
    body = post_rows(client, pid, columns=["manufacturer", "kvp"])
    all_cases = case_ids(client, pid)
    assert body["n_cases"] == len(all_cases)
    assert sum(len(r["scans"]) for r in body["rows"]) == body["n_scans"] >= len(all_cases)
    page = post_rows(client, pid, columns=["kvp"], limit=10, offset=5)
    assert len(page["rows"]) == 10 and page["n_cases"] == body["n_cases"]
    assert [r["case_id"] for r in page["rows"]] == sorted(all_cases)[5:15]
    diff = next(r for r in body["rows"] if "kvp" in r["differs"])
    assert diff["values"]["kvp"] is None
    assert len({s["values"]["kvp"] for s in diff["scans"]}) > 1
    for s in diff["scans"]:
        assert s["item_id"].endswith(".complete.-")
        assert s["modality"] in {"CT", "MR", None}
        assert s["phase"]
    same = next(
        r
        for r in body["rows"]
        if r["scans"] and "kvp" not in r["differs"] and r["values"]["kvp"] is not None
    )
    assert all(s["values"]["kvp"] == same["values"]["kvp"] for s in same["scans"])


@pytest.mark.parametrize(
    ("filters", "params"),
    [
        ({"manufacturer": ["Siemens Healthineers"]}, {"var.manufacturer": "Siemens Healthineers"}),
        ({"kvp": ["100..120"]}, {"var.kvp": "100..120"}),
        (
            {"manufacturer": ["SIEMENS"], "kvp": ["100..140"]},
            {"var.manufacturer": "SIEMENS", "var.kvp": "100..140"},
        ),
    ],
)
def test_rows_filters_match_the_cases_endpoint(
    client: TestClient, pid: str, filters: dict[str, list[str]], params: dict[str, str]
) -> None:
    rows = post_rows(client, pid, columns=[], filters=filters, limit=500)["rows"]
    got = {r["case_id"] for r in rows}
    want = case_ids(client, pid, **params)
    assert want
    assert got == want


def test_rows_q_and_phase(client: TestClient, pid: str) -> None:
    assert [r["case_id"] for r in post_rows(client, pid, q="case_00030")["rows"]] == ["case_00030"]
    assert [r["case_id"] for r in post_rows(client, pid, q="P030")["rows"]] == ["case_00030"]
    assert post_rows(client, pid, q="no such case")["rows"] == []
    np_cases = case_ids(client, pid, phase="NP")
    assert np_cases
    got = {r["case_id"] for r in post_rows(client, pid, phase="NP", limit=500)["rows"]}
    assert got == np_cases


def test_rows_sort(client: TestClient, pid: str) -> None:
    body = post_rows(
        client,
        pid,
        columns=["manufacturer"],
        sort={"column": "manufacturer", "desc": True},
        limit=500,
    )
    vals = [r["values"]["manufacturer"] for r in body["rows"]]
    present = [v for v in vals if v is not None]
    assert present and present == sorted(present, reverse=True)
    assert all(v is None for v in vals[len(present) :])


def test_rows_and_summary_validation(client: TestClient, pid: str) -> None:
    u, s = rows_url(pid), sum_url(pid)
    assert_problem(client.post(u, json={"columns": ["nope"]}), "validation")
    assert_problem(client.post(u, json={"filters": {"nope": ["x"]}}), "validation")
    assert_problem(client.post(u, json={"sort": {"column": "kvp"}}), "validation")
    assert_problem(client.post(u, json={"phase": "ZZZ"}), "validation")
    assert_problem(client.post(u, json={"columns": ["kvp"], "limit": 501}), "validation")
    assert_problem(client.post(s, json={"column": "nope"}), "validation")


def test_summary_categorical(client: TestClient, pid: str) -> None:
    b = client.post(sum_url(pid), json={"column": "manufacturer"}).json()
    assert b["bins"] is None
    assert set(b["counts"]) == {
        "Siemens Healthineers",
        "Philips Medical Systems",
        "SIEMENS",
        "PHILIPS",
        "GE MEDICAL SYSTEMS",
    }
    assert sum(b["counts"].values()) + b["other"] + b["missing"] == len(case_ids(client, pid))


def test_summary_numeric_and_filters(client: TestClient, pid: str) -> None:
    n_scans = post_rows(client, pid)["n_scans"]
    b = client.post(sum_url(pid), json={"column": "kvp"}).json()
    assert b["counts"] is None
    assert len(b["bins"]) == 20
    assert b["bins"][0]["lo"] == "100" and b["bins"][-1]["hi"] == "140"
    assert sum(x["count"] for x in b["bins"]) + b["missing"] == n_scans
    b = client.post(
        sum_url(pid),
        json={"column": "manufacturer", "filters": {"manufacturer": ["Siemens Healthineers"]}},
    ).json()
    n = len(case_ids(client, pid, **{"var.manufacturer": "Siemens Healthineers"}))
    assert b["counts"] == {"Siemens Healthineers": n} and b["other"] == 0 and b["missing"] == 0


def test_view_only_token_reads_cohort(client: TestClient, pid: str) -> None:
    token = client.post(f"{API}/projects/{pid}/view-token").json()["view_token"]
    v = f"{API}/view/{token}"
    r = client.post(f"{v}/cohort/rows", json={"columns": ["manufacturer", "kvp"]})
    assert r.status_code == 200, r.text
    assert r.json()["n_cases"] == len(case_ids(client, pid))
    r = client.post(f"{v}/cohort/summary", json={"column": "manufacturer"})
    assert r.status_code == 200, r.text
    assert r.json()["counts"]
    r = client.post(f"{v}/cohort/balance", json={"a": "manufacturer", "b": "manufacturer"})
    assert_problem(r, "validation")
    # nothing else may POST on the view prefix
    assert client.post(f"{v}/segmentations/imports", json={}).status_code == 405
    assert pid not in client.post(f"{v}/cohort/rows", json={}).text


def _balance_service(pairs: list[tuple[str, str]]) -> CohortService:
    rows = [
        _row(f"c{i}.01.complete.-", f"c{i}", "01", manufacturer=m, marker_a=a)
        for i, (m, a) in enumerate(pairs)
    ]
    return _service(
        _table(rows), items=[_item(f"c{i}.01.complete.-", f"c{i}") for i in range(len(pairs))]
    )


def test_balance_counts_levels_and_tests_them() -> None:
    pairs = [("SIEMENS", "A")] * 8 + [("SIEMENS", "B")] * 2 + [("GE", "A")] * 2 + [("GE", "B")] * 8
    b = asyncio.run(
        _balance_service(pairs).balance("p", CohortBalanceRequest(a="manufacturer", b="marker_a"))
    )
    assert b.unit == "case" and b.n == 20 and b.missing == 0
    assert b.rows == ["GE", "SIEMENS"] and b.cols == ["A", "B"]
    assert {(c.row, c.col): c.n for c in b.cells} == {
        ("GE", "A"): 2, ("GE", "B"): 8, ("SIEMENS", "A"): 8, ("SIEMENS", "B"): 2,
    }  # fmt: skip
    assert b.test == "chi2" and b.p is not None and b.p < 0.05  # every expected count is 5
    forced = asyncio.run(
        _balance_service(pairs).balance(
            "p", CohortBalanceRequest(a="manufacturer", b="marker_a", test="alternative")
        )
    )
    assert forced.test == "fisher" and forced.cramers_v is not None


def test_balance_lists_thin_levels_and_refuses_bad_variables() -> None:
    pairs = [("SIEMENS", "A")] * 6 + [("GE", "B")] * 6 + [("PHILIPS", "A")]
    svc = _balance_service(pairs)
    b = asyncio.run(svc.balance("p", CohortBalanceRequest(a="manufacturer", b="marker_a")))
    assert b.excluded_rows == ["PHILIPS"] and "PHILIPS" not in b.rows
    with pytest.raises(ValidationProblem, match="two different"):
        asyncio.run(svc.balance("p", CohortBalanceRequest(a="kvp", b="kvp")))
    with pytest.raises(ValidationProblem, match="categorical"):
        asyncio.run(svc.balance("p", CohortBalanceRequest(a="kvp", b="marker_a")))
    with pytest.raises(ValidationProblem, match="Unknown variable"):
        asyncio.run(svc.balance("p", CohortBalanceRequest(a="nope", b="marker_a")))


def test_empty_project(client: TestClient) -> None:
    p = client.post(f"{API}/projects", json={"name": "cohort-empty"}).json()["project_id"]
    assert client.post(rows_url(p), json={}).json() == {"n_cases": 0, "n_scans": 0, "rows": []}
    # No variables exist yet, so a named column is unknown.
    assert_problem(client.post(sum_url(p), json={"column": "manufacturer"}), "validation")
