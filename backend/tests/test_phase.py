"""Native phase selection (PHASE.md PHS-01..08, ADR-0026): events, read-time join, exports."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.ids import new_ulid
from tests.test_api_ingest import API, ctx_of
from tests.test_contract import assert_problem
from tests.test_curation_api import HDR, active_with_mask, proj  # noqa: F401

Proj = tuple[str, list[dict[str, Any]]]


def select(c: TestClient, pid: str, body: dict[str, Any], headers: dict[str, str] = HDR) -> Any:
    return c.post(f"{API}/projects/{pid}/phase/events", json=body, headers=headers)


def scan_of(items: list[dict[str, Any]]) -> tuple[str, str, str]:
    """A scan with a complete-scope item and its current (resolved) phase."""
    it = next(i for i in active_with_mask(items) if i["scope"] == "complete")
    return it["case_id"], it["scan_idx"], it["phase"]["canonical"]


def other(phase: str) -> str:
    return next(p for p in ("NC", "CMP", "NP", "EP") if p != phase)


def test_select_replaces_the_effective_phase_everywhere(client: TestClient, proj: Proj) -> None:  # noqa: F811
    pid, items = proj
    case_id, scan_idx, before = scan_of(items)
    new = other(before)
    pdir = ctx_of(client).workspace.project_dir(pid)
    index_bytes = (pdir / "index" / "items.jsonl").read_bytes()
    bus = ctx_of(client).bus
    calls: list[tuple[str, str, dict[str, Any]]] = []
    orig = bus.publish
    bus.publish = lambda p, e, d: calls.append((p, e, d)) or orig(p, e, d)  # type: ignore[method-assign,func-returns-value]

    r = select(client, pid, {"case_id": case_id, "scan_idx": scan_idx, "value": new})
    assert r.status_code == 201, r.text
    ev = r.json()
    assert ev["reviewer"] == "Dr. AP" and ev["session_id"] == "tab-1"
    assert ev["source"] == "manual" and ev["accepted_run_id"] is None and ev["value"] == new
    assert [d for _, e, d in calls if e == "phase.appended"] == [ev]  # PHS-05

    # PHS-03: every item of the scan (complete and VOIs), the case detail and summary
    scan_items = [i for i in items if i["case_id"] == case_id and i["scan_idx"] == scan_idx]
    for it in scan_items:
        got = client.get(f"{API}/projects/{pid}/items/{it['item_id']}").json()["phase"]
        assert got["canonical"] == new and got["source"] == "manual"
        assert got["resolved"]["canonical"] == before and got["resolved"]["resolved"] is None
    detail = client.get(f"{API}/projects/{pid}/cases/{case_id}").json()
    group = next(s for s in detail["scans"] if s["scan_idx"] == scan_idx)
    assert group["phase"]["canonical"] == new
    assert new in detail["case"]["phases"]
    listed = client.get(f"{API}/projects/{pid}/cases", params={"phase": new, "limit": 2000})
    assert case_id in {c["case_id"] for c in listed.json()["items"]}

    # R1: the index is never rewritten by a selection
    assert (pdir / "index" / "items.jsonl").read_bytes() == index_bytes
    assert (pdir / "events" / "phase.jsonl").is_file()

    # dataset table: effective phase + `phase_source` = manual (PHASE §Where it surfaces)
    table = client.get(f"{API}/projects/{pid}/exports/dataset-table").text
    rows = [x for x in csv.DictReader(io.StringIO(table)) if x["case_id"] == case_id]
    row = next(x for x in rows if x["scan_idx"] == scan_idx)
    assert row["phase"] == new and row["phase_source"] == "manual"
    untouched = [x for x in rows if x["scan_idx"] != scan_idx]
    assert all(x["phase_source"] != "manual" for x in untouched)
    header = next(csv.reader(io.StringIO(table)))
    assert len(header) == len(set(header))  # an input `phase` field does not shadow the column


def test_latest_event_wins_with_history_and_state(client: TestClient, proj: Proj) -> None:  # noqa: F811
    pid, items = proj
    case_id, scan_idx, before = scan_of(items)
    scan = {"case_id": case_id, "scan_idx": scan_idx}
    select(client, pid, {**scan, "value": "EP"})
    select(client, pid, {**scan, "value": "NC"}, headers={"X-Reviewer": "B"})
    hist = client.get(f"{API}/projects/{pid}/phase/events", params=scan).json()["items"]
    assert [(e["value"], e["reviewer"]) for e in hist] == [("NC", "B"), ("EP", "Dr. AP")]  # PHS-07
    state = client.get(f"{API}/projects/{pid}/phase/state", params={"case_id": case_id}).json()
    assert state["n_events"] == 2
    [sel] = state["selections"]
    assert sel["value"] == "NC" and sel["reviewer"] == "B"
    assert sel["resolved"] == before and sel["resolved_source"] not in (None, "manual")
    item = f"{case_id}.{scan_idx}.complete.-"
    assert client.get(f"{API}/projects/{pid}/items/{item}").json()["phase"]["canonical"] == "NC"


def test_validation(client: TestClient, proj: Proj) -> None:  # noqa: F811
    pid, items = proj
    case_id, scan_idx, _ = scan_of(items)
    base = {"case_id": case_id, "scan_idx": scan_idx, "value": "NP"}
    assert_problem(select(client, pid, base, headers={}), "reviewer-required")
    for bad in (
        base | {"value": "ZZ"},  # not in phase_vocabulary
        base | {"value": ""},
        base | {"scan_idx": "99"},
        base | {"case_id": "case_09999"},
        base | {"accepted_run_id": new_ulid()},  # only with analyzer_accept
        base | {"source": "analyzer_accept"},  # needs the active run
        base | {"source": "analyzer_accept", "accepted_run_id": new_ulid()},  # not active
        base | {"source": "v2_import"},  # imports only via their routes
        base | {"extra": 1},
    ):
        assert_problem(select(client, pid, bad), "validation")
    assert client.get(f"{API}/projects/{pid}/phase/events").json()["items"] == []


def test_accept_analyzer_guess(client: TestClient, proj: Proj) -> None:  # noqa: F811
    """PHS-04: accepting the active `analyzer.phase` run's guess is the same one-click event."""
    pid, items = proj
    case_id, scan_idx, _ = scan_of(items)
    run_id = new_ulid()
    ws = ctx_of(client).workspace
    client.portal.call(ws.set_annotation_source, pid, "phase", run_id)  # type: ignore[union-attr]
    body = {"case_id": case_id, "scan_idx": scan_idx, "value": "CMP"}
    r = select(client, pid, body | {"source": "analyzer_accept", "accepted_run_id": run_id})
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "analyzer_accept" and r.json()["accepted_run_id"] == run_id


def test_export_phase_selections(client: TestClient, proj: Proj) -> None:  # noqa: F811
    pid, items = proj
    case_id, scan_idx, _ = scan_of(items)
    select(client, pid, {"case_id": case_id, "scan_idx": scan_idx, "value": "EP"})
    select(client, pid, {"case_id": case_id, "scan_idx": scan_idx, "value": "NP"})
    r = client.post(f"{API}/projects/{pid}/phase/exports")
    assert r.status_code == 201, r.text
    assert r.json()["files"] == ["phase_selections.json"] and r.json()["dir"] == "exports"
    pdir = ctx_of(client).workspace.project_dir(pid)
    doc = json.loads((pdir / "exports" / "phase_selections.json").read_text())
    assert doc["schema_version"] == 1 and doc["updated_at"].endswith("Z")  # like phase.json
    assert doc["phases"] == [{"case_id": case_id, "scan_idx": scan_idx, "phase": "NP"}]


def test_index_writers_never_store_the_selection(client: TestClient, proj: Proj) -> None:  # noqa: F811
    pid, items = proj
    case_id, scan_idx, before = scan_of(items)
    select(client, pid, {"case_id": case_id, "scan_idx": scan_idx, "value": other(before)})
    ctx = ctx_of(client)
    svc_items = ctx.index.load(pid).items  # joined
    assert any(i.phase.source == "manual" for i in svc_items)
    # a writer that loads and replaces the index (ADR-0015 segmentation re-join)
    from app.api.v1.imports import ingest_service

    client.portal.call(ingest_service(ctx).reapply_segmentations, pid)  # type: ignore[union-attr]
    stored = (ctx.workspace.project_dir(pid) / "index" / "items.jsonl").read_text()
    assert '"manual"' not in stored and '"resolved"' not in stored
    ctx.index.invalidate(pid)
    it = ctx.index.get_item(pid, f"{case_id}.{scan_idx}.complete.-")
    assert it.phase.source == "manual" and it.phase.resolved is not None  # still joined on read
    assert it.phase.resolved.canonical == before
    assert ctx.index.load_resolved(pid).by_id[it.item_id].phase.canonical == before


def test_v2_phase_issue_becomes_a_phase_event(client: TestClient, proj: Proj) -> None:  # noqa: F811
    """PHS-08: v2 `phase_issue` → native `v2_import` event (latest per scan), not curation."""
    pid, items = proj
    case_id, scan_idx, _ = scan_of(items)
    header = (
        "review_id,case_id,scan_idx,scope,side,target,status,reviewer,reviewed_at,proposed_phase\n"
    )
    body = (
        f"p1,{case_id},{scan_idx},complete,,phase_issue,wrong_phase_suspected,OLD,2025-05-02T10:00:00Z,ep\n"
        f"p0,{case_id},{scan_idx},complete,,phase_issue,wrong_phase_suspected,OLD,2025-05-01T10:00:00Z,nc\n"
        f"p2,{case_id},,,,phase_issue,wrong_phase_suspected,OLD,2025-05-01T10:00:00Z,NP\n"
        f"p3,{case_id},{scan_idx},complete,,phase_issue,accepted,OLD,2025-05-01T10:00:00Z,\n"
        f"s1,{case_id},{scan_idx},complete,,SEG,wrong_phase_suspected,OLD,2025-05-01T10:00:00Z,\n"
    )
    url = f"{API}/projects/{pid}/curation/import-v2"
    files = {"file": ("curation_review.csv", (header + body).encode(), "text/csv")}
    rep = client.post(url, files=files, headers=HDR).json()
    assert rep["imported"] == 0 and rep["phase_events"] == 1
    reasons = {s["review_id"]: s["reason"] for s in rep["skipped"]}
    assert reasons["p0"].startswith("superseded") and reasons["p2"].endswith("without scan_idx")
    assert "proposed_phase" in reasons["p3"] and reasons["s1"].startswith("unknown status")
    [ev] = client.get(f"{API}/projects/{pid}/phase/events").json()["items"]
    assert (ev["value"], ev["source"], ev["reviewer"], ev["at"]) == (
        "EP", "v2_import", "OLD", "2025-05-02T10:00:00Z"
    )  # fmt: skip
    assert client.get(f"{API}/projects/{pid}/curation/events").json()["items"] == []
    again = client.post(url, files=files, headers=HDR).json()
    assert again["phase_events"] == 0  # one import per scan


def test_import_never_overrides_a_reviewer_selection(client: TestClient, proj: Proj) -> None:  # noqa: F811
    pid, items = proj
    case_id, scan_idx, _ = scan_of(items)
    select(client, pid, {"case_id": case_id, "scan_idx": scan_idx, "value": "NC"})
    csv_body = f"case_id,scan_idx,curated_phase\n{case_id},{scan_idx},EP\n".encode()
    files = {"file": ("curation.csv", io.BytesIO(csv_body), "text/csv")}
    url = f"{API}/projects/{pid}/curation/import-converter"
    rep = client.post(url, files=files, headers=HDR).json()
    assert rep["phase_events"] == 0 and rep["skipped"][0]["reason"] == "phase already set"
    item = client.get(f"{API}/projects/{pid}/items/{case_id}.{scan_idx}.complete.-").json()
    assert item["phase"]["canonical"] == "NC"


def test_legacy_curation_phase_events_are_ignored(client: TestClient, proj: Proj) -> None:  # noqa: F811
    """Pre-ADR-0026 `phase` target / `wrong_phase_suspected` events stay on disk, unread."""
    pid, items = proj
    it = active_with_mask(items)[0]
    pdir: Path = ctx_of(client).workspace.project_dir(pid)
    old = [
        {"event_id": new_ulid(), "at": "2026-01-01T00:00:00Z", "reviewer": "A",
         "item_id": it["item_id"], "case_id": it["case_id"], "target": "phase",
         "status": status, "proposed_phase": "EP"}
        for status in ("wrong_phase_suspected", "accepted")
    ]  # fmt: skip
    (pdir / "curation").mkdir(exist_ok=True)
    (pdir / "curation" / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in old))
    state = client.get(f"{API}/projects/{pid}/curation/state").json()
    assert state["n_events"] == 0 and state["items"] == []


def test_view_only_link_reads_phase(client: TestClient, proj: Proj) -> None:  # noqa: F811
    pid, items = proj
    case_id, scan_idx, _ = scan_of(items)
    select(client, pid, {"case_id": case_id, "scan_idx": scan_idx, "value": "EP"})
    token = client.post(f"{API}/projects/{pid}/view-token").json()["view_token"]
    r = client.get(f"{API}/view/{token}/phase/state")
    assert r.status_code == 200 and r.json()["selections"][0]["value"] == "EP"
    assert client.get(f"{API}/view/{token}/phase/events").status_code == 200
    assert client.post(f"{API}/view/{token}/phase/events", json={}).status_code == 405
