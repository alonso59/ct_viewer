"""TST-03: API-50..54 curation endpoints over the synthetic fixtures (CUR-01..14)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.curation.models import QUEUE_COLUMNS
from tests.test_api_ingest import API, ctx_of, do_import
from tests.test_contract import assert_problem

HDR = {"X-Reviewer": "Dr. AP", "X-Session-Id": "tab-1"}


@pytest.fixture
def proj(client: TestClient, data_root: Path) -> tuple[str, list[dict[str, Any]]]:
    cfg = client.portal.call(ctx_of(client).workspace.create, "cur", "", "CT", ["ccrcc"])  # type: ignore[union-attr]
    pid = str(cfg.project_id)
    do_import(client, pid, data_root)
    items = [i.model_dump(mode="json") for i in ctx_of(client).index.load(pid).items]
    return pid, items


def post(c: TestClient, pid: str, body: dict[str, Any], headers: dict[str, str] = HDR) -> Any:
    return c.post(f"{API}/projects/{pid}/curation/events", json=body, headers=headers)


def active_with_mask(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [i for i in items if i["status"] == "active" and i["mask"] and i["image"]]


def test_append_history_and_sse(client: TestClient, proj: tuple[str, list[dict[str, Any]]]) -> None:
    pid, items = proj
    it = active_with_mask(items)[0]
    r = post(client, pid, {"item_id": it["item_id"], "target": "label:2", "status": "accepted"})
    assert r.status_code == 201, r.text
    ev = r.json()
    assert ev["reviewer"] == "Dr. AP" and ev["session_id"] == "tab-1"
    assert ev["schema_version"] == 1 and ev["source"] == "ui" and ev["at"].endswith("Z")
    assert ev["case_id"] == it["case_id"] and ev["context"]["phase"] == it["phase"]["canonical"]
    r2 = post(
        client,
        pid,
        {
            "item_id": it["item_id"],
            "target": "label:2",
            "status": "needs_minor_correction",
            "priority": "high",
            "comment": "leak",
            "session_id": "body-tab",
            "source": "api",
        },
        headers={"X-Reviewer": "B"},
    ).json()
    assert r2["session_id"] == "body-tab" and r2["source"] == "api"
    case_ev = post(client, pid, {"case_id": it["case_id"], "target": "case", "status": "accepted"})
    assert case_ev.status_code == 201 and case_ev.json()["item_id"] is None

    pdir = ctx_of(client).workspace.project_dir(pid)
    lines = (pdir / "curation" / "events.jsonl").read_text().splitlines()
    assert [json.loads(x)["event_id"] for x in lines] == [
        ev["event_id"],
        r2["event_id"],
        case_ev.json()["event_id"],
    ]
    snap = json.loads((pdir / "curation" / "state.json").read_text())
    assert snap["n_events"] == 3 and snap["items"][0]["status"] == "needs_minor_correction"

    h = client.get(f"{API}/projects/{pid}/curation/events", params={"item_id": it["item_id"]})
    assert [e["event_id"] for e in h.json()["items"]] == [r2["event_id"], ev["event_id"]]
    h = client.get(f"{API}/projects/{pid}/curation/events", params={"case_id": it["case_id"]})
    assert h.json()["total"] == 3 and h.json()["items"][0]["target"] == "case"

    bus = ctx_of(client).bus

    async def appended() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        async for e in bus.subscribe(pid, bus.first_id - 1):
            if e.event == "curation.appended":
                out.append(e.data)
                if len(out) == 3:
                    return out
        raise AssertionError("missing curation.appended")

    data = client.portal.call(appended)  # type: ignore[union-attr]
    assert data[0] == ev and data[1]["reviewer"] == "B"


def test_errors(client: TestClient, proj: tuple[str, list[dict[str, Any]]]) -> None:
    pid, items = proj
    it = items[0]
    base = {"item_id": it["item_id"], "target": "seg", "status": "accepted"}
    assert_problem(post(client, pid, base, headers={}), "reviewer-required")
    assert_problem(post(client, pid, base, headers={"X-Reviewer": "  "}), "reviewer-required")
    bad: list[dict[str, Any]] = [
        base | {"status": "fine"},
        base | {"target": "label:x"},
        base | {"target": "tumor"},
        base | {"target": "label:99"},
        base | {"item_id": "case_09999.01.complete.-"},
        base | {"item_id": None},
        base | {"case_id": "case_09999"},
        base | {"priority": "urgent"},
        base | {"proposed_phase": "NP"},  # phase is native now (ADR-0026)
        base | {"target": "phase"},
        base | {"status": "wrong_phase_suspected"},
        base | {"proposed_side": "X"},
        base | {"source": "v2_import"},
        base | {"extra_field": 1},
        {
            "case_id": it["case_id"],
            "item_id": it["item_id"],
            "target": "case",
            "status": "accepted",
        },
        {"target": "case", "status": "accepted"},
        {"case_id": "case_09999", "target": "case", "status": "accepted"},
    ]
    for body in bad:
        assert_problem(post(client, pid, body), "validation")
    unknown = "01JAAAAAAAAAAAAAAAAAAAAAAA"
    assert_problem(post(client, unknown, base), "not-found")
    for path in ("events", "state", "queue"):
        assert_problem(client.get(f"{API}/projects/{unknown}/curation/{path}"), "not-found")
    assert_problem(client.post(f"{API}/projects/{unknown}/curation/exports"), "not-found")
    assert_problem(
        client.get(f"{API}/projects/{pid}/curation/queue", params={"format": "xml"}), "validation"
    )
    csv_bad = {"file": ("r.csv", b"a,b\n1,2\n", "text/csv")}
    url = f"{API}/projects/{pid}/curation/import-v2"
    assert_problem(client.post(url, files=csv_bad), "reviewer-required")
    assert_problem(client.post(url, files=csv_bad, headers=HDR), "validation")
    assert (
        ctx_of(client).workspace.project_dir(pid).joinpath("curation/events.jsonl").exists()
        is False
    )


def test_state_rollup_and_case_summaries(
    client: TestClient, proj: tuple[str, list[dict[str, Any]]]
) -> None:
    pid, items = proj
    it = active_with_mask(items)[0]
    siblings = [i for i in items if i["case_id"] == it["case_id"] and i["item_id"] != it["item_id"]]
    post(client, pid, {"item_id": it["item_id"], "target": "seg", "status": "accepted"})
    post(client, pid, {"item_id": it["item_id"], "target": "label:1", "status": "missing"})
    if siblings:
        post(
            client, pid, {"item_id": siblings[0]["item_id"], "target": "seg", "status": "accepted"}
        )
    s = client.get(f"{API}/projects/{pid}/curation/state").json()
    item_state = next(x for x in s["items"] if x["item_id"] == it["item_id"])
    assert item_state["status"] == "missing" and item_state["reviewer"] == "Dr. AP"
    case_state = next(x for x in s["cases"] if x["case_id"] == it["case_id"])
    assert case_state["status"] == "missing" and case_state["last_reviewed_at"]
    s = client.get(f"{API}/projects/{pid}/curation/state", params={"case_id": "case_09999"})
    assert s.json()["items"] == [] and s.json()["cases"] == []

    cases = client.get(f"{API}/projects/{pid}/cases", params={"limit": 2000}).json()["items"]
    by_id = {c["case_id"]: c for c in cases}
    assert by_id[it["case_id"]]["curation_status"] == "missing"
    assert by_id[it["case_id"]]["last_reviewed_at"] == case_state["last_reviewed_at"]
    others = [c for c in cases if c["case_id"] != it["case_id"]]
    assert all(c["curation_status"] == "not_reviewed" for c in others)
    detail = client.get(f"{API}/projects/{pid}/cases/{it['case_id']}").json()
    assert detail["case"]["curation_status"] == "missing"

    summary = client.get(f"{API}/projects/{pid}").json()
    assert summary["project_id"] == pid
    # CUR-08 (AUD-A5-15): reviewed only once every active item has a decision
    active = [
        i["item_id"] for i in items if i["case_id"] == it["case_id"] and i["status"] == "active"
    ]
    case = by_id[it["case_id"]]
    assert case["n_items_active"] == len(active)
    assert case["n_items_reviewed"] == len({it["item_id"], *[s["item_id"] for s in siblings[:1]]})
    n_cases = len(ctx_of(client).index.load(pid).cases)

    def progress() -> float:
        rows = [p for p in client.get(f"{API}/projects").json() if p["project_id"] == pid]
        return float(rows[0]["curation_progress"])

    if case["n_items_reviewed"] < len(active):
        assert case["review_state"] == "partial" and progress() == 0.0
    for iid in active:
        post(client, pid, {"item_id": iid, "target": "side", "status": "accepted"})
    case = client.get(f"{API}/projects/{pid}/cases/{it['case_id']}").json()["case"]
    assert case["review_state"] == "reviewed" and case["curation_status"] == "missing"
    assert progress() == pytest.approx(1 / n_cases)


def test_partially_reviewed_rollup_and_status_filter(
    client: TestClient, proj: tuple[str, list[dict[str, Any]]]
) -> None:
    """CUR-08 (AUD-A5-15): one accepted item of several → `partially_reviewed`, not counted;
    API-20 `?curation_status=` filters on the rollup (AUD-A5-09)."""
    pid, items = proj
    by_case: dict[str, list[str]] = {}
    for i in items:
        if i["status"] == "active":
            by_case.setdefault(i["case_id"], []).append(i["item_id"])
    cid, ids = next((c, v) for c, v in by_case.items() if len(v) > 1)
    post(client, pid, {"item_id": ids[0], "target": "side", "status": "accepted"})
    url = f"{API}/projects/{pid}/cases"
    case = client.get(f"{url}/{cid}").json()["case"]
    assert (case["curation_status"], case["review_state"]) == ("partially_reviewed", "partial")
    assert (case["n_items_reviewed"], case["n_items_active"]) == (1, len(ids))
    got = client.get(url, params={"curation_status": "partially_reviewed"}).json()["items"]
    assert [c["case_id"] for c in got] == [cid]
    assert client.get(url, params={"curation_status": "accepted"}).json()["items"] == []
    rest = client.get(url, params={"curation_status": "not_reviewed", "limit": 2000}).json()
    assert cid not in {c["case_id"] for c in rest["items"]} and rest["total"] > 0
    assert_problem(client.get(url, params={"curation_status": "bogus"}), "validation")
    for iid in ids[1:]:
        post(client, pid, {"item_id": iid, "target": "side", "status": "accepted"})
    case = client.get(f"{url}/{cid}").json()["case"]
    assert (case["curation_status"], case["review_state"]) == ("accepted", "reviewed")
    got = client.get(url, params={"curation_status": "accepted"}).json()["items"]
    assert [c["case_id"] for c in got] == [cid]


def test_queue_json_and_csv(client: TestClient, proj: tuple[str, list[dict[str, Any]]]) -> None:
    pid, items = proj
    a, b, c = active_with_mask(items)[:3]
    post(
        client,
        pid,
        {"item_id": a["item_id"], "target": "seg", "status": "rejected", "comment": "x, y"},
    )
    post(
        client,
        pid,
        {"item_id": b["item_id"], "target": "seg", "status": "accepted", "add_to_queue": True},
    )
    post(
        client, pid, {"item_id": c["item_id"], "target": "seg", "status": "needs_major_correction"}
    )
    post(client, pid, {"item_id": c["item_id"], "target": "seg", "status": "accepted"})  # fixed
    post(client, pid, {"case_id": a["case_id"], "target": "case", "status": "rejected"})
    q = client.get(f"{API}/projects/{pid}/curation/queue")
    assert q.status_code == 200
    rows = q.json()
    assert [r["item_id"] for r in rows] == [a["item_id"], b["item_id"]]
    assert list(rows[0]) == list(QUEUE_COLUMNS)
    root = ctx_of(client).workspace.resolver(pid)
    assert rows[0]["image_path_abs"] == str(root.resolve(a["image"]["ref"]))
    assert rows[0]["mask_path_abs"] == str(root.resolve(a["mask"]["ref"]))
    assert (
        Path(rows[0]["image_path_abs"]).is_absolute() and Path(rows[0]["image_path_abs"]).exists()
    )
    assert rows[0]["phase"] == a["phase"]["canonical"] and rows[0]["scope"] == a["scope"]
    assert rows[0]["seg_id"] == "imported"  # AUD-A2-16: mask targets name their set

    r = client.get(f"{API}/projects/{pid}/curation/queue", params={"format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    parsed = list(csv.DictReader(io.StringIO(r.text)))
    assert list(parsed[0]) == list(QUEUE_COLUMNS)
    assert r.text.splitlines()[0] == ",".join(QUEUE_COLUMNS)
    assert parsed[0]["comment"] == "x, y" and parsed[0]["status"] == "rejected"
    assert parsed[0]["mask_path_abs"] == rows[0]["mask_path_abs"]


def test_exports(client: TestClient, proj: tuple[str, list[dict[str, Any]]]) -> None:
    pid, items = proj
    a, b = active_with_mask(items)[:2]
    minor = {"target": "seg", "status": "needs_minor_correction"}
    post(client, pid, {"item_id": a["item_id"], **minor, "comment": "first"})
    post(client, pid, {"item_id": a["item_id"], **minor, "comment": "second"})
    side = {"target": "side", "status": "wrong_side_suspected", "proposed_side": "R"}
    post(client, pid, {"item_id": b["item_id"], **side})
    r = client.post(f"{API}/projects/{pid}/curation/exports")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["files"] == ["curation_state.csv", "events.jsonl"]  # phase: PHS-06
    pdir = ctx_of(client).workspace.project_dir(pid)
    exp = pdir / "exports"
    assert (exp / "events.jsonl").read_bytes() == (pdir / "curation" / "events.jsonl").read_bytes()
    state_rows = list(csv.DictReader((exp / "curation_state.csv").open()))
    assert len(state_rows) == 2
    row_a = next(x for x in state_rows if x["item_id"] == a["item_id"])
    assert row_a["comment"] == "second" and row_a["item_status"] == "needs_minor_correction"
    assert "proposed_phase" not in state_rows[0]
    assert not (exp / "phase_proposals.json").exists()


def test_import_v2(client: TestClient, proj: tuple[str, list[dict[str, Any]]]) -> None:
    pid, items = proj
    a = active_with_mask(items)[0]
    side = a["side"] if a["scope"] == "voi" else ""
    header = (
        "review_id,dataset_id,case_id,scan_idx,scope,side,target,status,priority,comment,"
        "reviewer,reviewed_at\n"
    )
    body = (
        f"r1,D,{a['case_id']},{a['scan_idx']},{a['scope']},{side},tumor_mask,"
        "needs_major_correction,high,v2 note,OLD,2025-05-01T10:00:00+00:00\n"
        f"r2,D,{a['case_id']},,complete,,SEG,accepted,medium,,,2025-05-02T10:00:00+00:00\n"
        f"r3,D,case_09999,01,complete,,SEG,accepted,medium,,,2025-05-02T10:00:00+00:00\n"
    )
    url = f"{API}/projects/{pid}/curation/import-v2"
    files = {"file": ("curation_review.csv", (header + body).encode(), "text/csv")}
    r = client.post(url, files=files, headers=HDR)
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["n_rows"] == 3 and rep["imported"] == 2
    assert rep["skipped"] == [
        {"line": 4, "review_id": "r3", "reason": "case 'case_09999' not in index"}
    ]
    evs = client.get(f"{API}/projects/{pid}/curation/events").json()["items"]
    assert {e["source"] for e in evs} == {"v2_import"}
    ev1 = next(e for e in evs if e["context"]["v2_review_id"] == "r1")
    assert (
        ev1["target"] == "label:2" and ev1["reviewer"] == "OLD" and ev1["item_id"] == a["item_id"]
    )
    ev2 = next(e for e in evs if e["context"]["v2_review_id"] == "r2")
    assert ev2["target"] == "case" and ev2["reviewer"] == "Dr. AP"
    again = client.post(url, files=files, headers=HDR).json()
    assert again["imported"] == 0 and len(again["skipped"]) == 3
    cases = client.get(f"{API}/projects/{pid}/cases", params={"limit": 2000}).json()["items"]
    status = next(c for c in cases if c["case_id"] == a["case_id"])["curation_status"]
    assert status == "needs_major_correction"
