"""TST-19 backend half (LBL-01..08, 10): tables at case/scan/item level, typed cell events with
last-writer-wins and history, `lbl.*` variables and layers, CSV import report, export, view-only."""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.test_api_ingest import ctx_of, do_import
from tests.test_contract import assert_problem
from tests.test_projects_v3 import neutral

API = "/api/v1"
HDR = {"X-Reviewer": "Dr. A", "X-Session-Id": "tab-a"}
CASE = "case_00001"
ITEM = "case_00001.01.complete.-"


@pytest.fixture
def pid(client: TestClient, data_root: Path) -> str:
    p = neutral(client, packs=["ccrcc"])
    do_import(client, p, data_root)
    return p


def lab(pid: str) -> str:
    return f"{API}/plugins/labeling/projects/{pid}"


def make_table(c: TestClient, pid: str, level: str = "case") -> dict[str, Any]:
    body = {
        "name": "Clinical review",
        "level": level,
        "columns": [
            {"name": "Tumour present", "type": "bool"},
            {"name": "Grade", "type": "category", "levels": ["G1", "G2", "G3"]},
            {"name": "Size", "type": "number", "unit": "mm", "min": 0, "max": 300},
            {"name": "Note", "type": "text"},
            {"name": "Surgery date", "type": "date"},
        ],
    }
    r = c.post(f"{lab(pid)}/tables", json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


def col(t: dict[str, Any], name: str) -> str:
    return str(next(x["column_id"] for x in t["columns"] if x["name"] == name))


def test_tables_levels_and_progress(client: TestClient, pid: str) -> None:
    case_t = make_table(client, pid, "case")
    scan_t = make_table(client, pid, "scan")
    item_t = make_table(client, pid, "item")
    assert case_t["slug"] == "clinical_review" and scan_t["slug"] == "clinical_review_2"
    assert [x["slug"] for x in case_t["columns"]][:2] == ["tumour_present", "grade"]
    rows = {t["level"]: t["n_rows"] for t in client.get(f"{lab(pid)}/tables").json()}
    idx = ctx_of(client).index.load(pid).items
    live = [i for i in idx if i.status != "excluded_upstream"]
    assert rows["case"] == len({i.case_id for i in live})
    assert rows["scan"] == len({(i.case_id, i.scan_idx) for i in live})
    assert rows["item"] == len(live)
    cells = client.get(f"{lab(pid)}/tables/{scan_t['table_id']}/cells", params={"q": CASE}).json()
    assert cells["items"][0]["target"] == f"{CASE}.01" and cells["items"][0]["item_id"] == ITEM
    it = client.get(f"{lab(pid)}/tables/{item_t['table_id']}/cells", params={"limit": 3}).json()
    assert it["next_cursor"] == "3" and it["total"] == rows["item"]
    assert_problem(client.post(f"{lab(pid)}/tables", json={"name": "x", "level": "case",
                   "columns": [{"name": "c", "type": "category"}]}), "validation")  # fmt: skip


def test_cells_events_lww_history(client: TestClient, pid: str) -> None:
    t = make_table(client, pid)
    url = f"{lab(pid)}/tables/{t['table_id']}/cells"
    grade, size, present = col(t, "Grade"), col(t, "Size"), col(t, "Tumour present")
    one = {"cells": [{"column_id": grade, "target": CASE, "value": "G2"}]}
    assert_problem(client.post(url, json=one), "reviewer-required")  # LBL-04 stamp
    bad = {"cells": [{"column_id": grade, "target": CASE, "value": "G9"},
                     {"column_id": size, "target": CASE, "value": 999},
                     {"column_id": present, "target": "nope", "value": True}]}  # fmt: skip
    r = client.post(url, json=bad, headers=HDR)
    assert_problem(r, "validation")
    assert len(r.json()["errors"]) == 3
    ok = {"cells": [{"column_id": grade, "target": CASE, "value": "g2"},
                    {"column_id": size, "target": CASE, "value": "12,5"},
                    {"column_id": present, "target": CASE, "value": "yes"}]}  # fmt: skip
    w = client.post(url, json=ok, headers=HDR).json()
    assert w["n_events"] == 3 and w["events"][0]["session_id"] == "tab-a"
    b = {"X-Reviewer": "Dr. B"}
    client.post(
        url, json={"cells": [{"column_id": grade, "target": CASE, "value": "G3"}]}, headers=b
    )
    row = client.get(url, params={"q": CASE}).json()["items"][0]
    assert row["values"] == {grade: "G3", size: 12.5, present: True}  # last writer wins
    assert row["updated"][grade] == "Dr. B"
    hist = client.get(f"{lab(pid)}/tables/{t['table_id']}/history",
                      params={"target": CASE, "column_id": grade}).json()  # fmt: skip
    assert [(h["value"], h["reviewer"]) for h in hist] == [("G3", "Dr. B"), ("G2", "Dr. A")]
    client.post(
        url, json={"cells": [{"column_id": size, "target": CASE, "value": None}]}, headers=HDR
    )
    assert size not in client.get(url, params={"q": CASE}).json()["items"][0]["values"]
    events = (ctx_of(client).workspace.project_dir(pid) / "events" / "labeling.jsonl").read_text()
    assert len(events.splitlines()) == 5  # append-only


def test_rename_keeps_id_and_hide_keeps_events(client: TestClient, pid: str) -> None:
    t = make_table(client, pid)
    grade = col(t, "Grade")
    url = f"{lab(pid)}/tables/{t['table_id']}"
    client.post(f"{url}/cells", json={"cells": [{"column_id": grade, "target": CASE,
                "value": "G1"}]}, headers=HDR)  # fmt: skip
    r = client.patch(url, json={"columns": [{"column_id": grade, "name": "WHO grade"}]}).json()
    g = next(x for x in r["columns"] if x["column_id"] == grade)
    assert g["name"] == "WHO grade" and g["slug"] == "grade"
    add = client.patch(url, json={"columns": [{"name": "Necrosis", "type": "bool"}]}).json()
    assert len(add["columns"]) == 6
    client.patch(url, json={"columns": [{"column_id": grade, "name": "WHO grade", "hidden": True}]})
    row = client.get(f"{url}/cells", params={"q": CASE}).json()["items"][0]
    assert grade not in row["values"]
    assert len(client.get(f"{url}/history", params={"column_id": grade}).json()) == 1
    assert_problem(client.patch(url, json={"columns": [{"column_id": grade, "name": "x",
                   "type": "text"}]}), "validation")  # fmt: skip
    size = col(t, "Size")
    r = client.patch(url, json={"columns": [{"column_id": size, "name": "Size", "max": None,
                     "unit": "cm", "description": "longest axis"}]}).json()  # fmt: skip
    s = next(x for x in r["columns"] if x["column_id"] == size)
    assert (s["max"], s["min"], s["unit"], s["description"]) == (None, 0, "cm", "longest axis")


def test_delete_table_hides_it_keeps_events_and_restores(client: TestClient, pid: str) -> None:
    """LBL-10: rename keeps the slug; delete hides the table everywhere but PATCH; restore is
    lossless; the slug stays reserved while deleted."""
    t = make_table(client, pid)
    url = f"{lab(pid)}/tables/{t['table_id']}"
    size = col(t, "Size")
    client.post(f"{url}/cells", json={"cells": [{"column_id": size, "target": CASE,
                "value": 40}]}, headers=HDR)  # fmt: skip
    wait_var(client, pid, "lbl.clinical_review.size")
    r = client.patch(url, json={"name": "Clinical review v2"}).json()
    assert r["name"] == "Clinical review v2" and r["slug"] == "clinical_review"

    assert client.patch(url, json={"hidden": True}).json()["hidden"] is True
    assert [x["table_id"] for x in client.get(f"{lab(pid)}/tables").json()] == []
    gone = client.get(f"{lab(pid)}/tables", params={"deleted": "true"}).json()
    assert [x["table_id"] for x in gone] == [t["table_id"]]
    assert_problem(client.get(f"{url}/cells"), "not-found")
    assert_problem(client.post(f"{url}/cells", json={"cells": [{"column_id": size,
                   "target": CASE, "value": 1}]}, headers=HDR), "not-found")  # fmt: skip
    layers = {x["field"] for x in client.get(f"{API}/projects/{pid}/layers").json()}
    assert "lbl.clinical_review.size" not in layers
    time.sleep(1.3)
    names = {v["name"] for v in client.get(f"{API}/projects/{pid}/variables").json()["variables"]}
    assert "lbl.clinical_review.size" not in names
    # a new table with the same name gets another slug: the deleted one keeps its variable names
    other = client.post(f"{lab(pid)}/tables", json={"name": "Clinical review", "level": "case"})
    assert other.json()["slug"] == "clinical_review_2"

    client.patch(url, json={"hidden": False})
    row = client.get(f"{url}/cells", params={"q": CASE}).json()["items"][0]
    assert row["values"][size] == 40
    assert wait_var(client, pid, "lbl.clinical_review.size")["type"] == "continuous"


def wait_var(c: TestClient, pid: str, name: str) -> dict[str, Any]:
    end = time.monotonic() + 10
    while time.monotonic() < end:
        for v in c.get(f"{API}/projects/{pid}/variables").json()["variables"]:
            if v["name"] == name:
                return dict(v)
        time.sleep(0.2)
    raise AssertionError(f"{name} never appeared")


def test_columns_are_variables_and_layers(client: TestClient, pid: str) -> None:
    t = make_table(client, pid)
    url = f"{lab(pid)}/tables/{t['table_id']}/cells"
    present, size = col(t, "Tumour present"), col(t, "Size")
    cells = [
        {"column_id": present, "target": f"case_0000{n}", "value": n % 2 == 1} for n in (1, 2, 3)
    ]
    cells.append({"column_id": size, "target": CASE, "value": 40})
    client.post(url, json={"cells": cells}, headers=HDR)
    time.sleep(1.3)
    v = wait_var(client, pid, "lbl.clinical_review.tumour_present")
    assert v["type"] == "categorical" and v["level"] == "case" and v["source"] == "layer"
    assert wait_var(client, pid, "lbl.clinical_review.size")["type"] == "continuous"
    flt = {"var.lbl.clinical_review.tumour_present": "yes"}
    got = client.get(f"{API}/projects/{pid}/cases", params=flt).json()["items"]
    assert {c["case_id"] for c in got} == {"case_00001", "case_00003"}
    layers = {x["field"]: x for x in client.get(f"{API}/projects/{pid}/layers").json()}
    assert layers["lbl.clinical_review.size"]["plugin"] == "labeling"
    table = client.get(f"{API}/projects/{pid}/exports/dataset-table").text
    rows = list(csv.DictReader(io.StringIO(table)))
    colname = "lbl.clinical_review.size@labeling:clinical_review"
    assert next(r for r in rows if r["item_id"] == ITEM)[colname] == "40"


def test_csv_import_report_and_export(client: TestClient, pid: str) -> None:
    t = make_table(client, pid)
    url = f"{lab(pid)}/tables/{t['table_id']}"
    raw = "case_id,Grade,size,unknown\ncase_00001,G1,10\ncase_00002,G9,11\nnope,G2,1\n"
    files = {"file": ("t.csv", io.BytesIO(raw.encode()), "text/csv")}
    rep = client.post(f"{url}/import", files=files, headers=HDR).json()
    assert rep["key"] == "case_id" and rep["n_rows"] == 3 and rep["matched"] == 2
    assert rep["unmatched"] == ["nope"] and rep["columns"] == ["Grade", "size"]
    assert rep["ignored_columns"] == ["unknown"] and len(rep["errors"]) == 1  # G9
    assert rep["n_events"] == 3
    out = client.get(f"{url}/export").text.splitlines()
    assert out[0].startswith("target,case_id,Tumour present,Grade,Size")
    assert next(x for x in out if x.startswith("case_00001,")).split(",")[3] == "G1"
    assert client.get(f"{url}/export", params={"format": "parquet"}).content[:4] == b"PAR1"


def test_view_only_reads_tables_but_cannot_write(client: TestClient, pid: str) -> None:
    t = make_table(client, pid)
    token = client.post(f"{API}/projects/{pid}/view-token").json()["view_token"]
    v = f"{API}/view/{token}/plugins/labeling/tables"
    assert [x["table_id"] for x in client.get(v).json()] == [t["table_id"]]
    assert client.get(f"{v}/{t['table_id']}/cells").status_code == 200
    w = {"cells": [{"column_id": col(t, "Grade"), "target": CASE, "value": "G1"}]}
    assert client.post(f"{v}/{t['table_id']}/cells", json=w, headers=HDR).status_code == 405
    assert pid not in client.get(v).text


def test_cell_writes_publish_live_events(client: TestClient, pid: str) -> None:
    t = make_table(client, pid)
    calls: list[tuple[str, str, dict[str, Any]]] = []
    bus = ctx_of(client).bus
    orig = bus.publish
    bus.publish = lambda p, e, d: calls.append((p, e, d)) or orig(p, e, d)  # type: ignore[method-assign,func-returns-value]
    w = {"cells": [{"column_id": col(t, "Grade"), "target": CASE, "value": "G1"}]}
    client.post(f"{lab(pid)}/tables/{t['table_id']}/cells", json=w, headers=HDR)
    ev = [d for p, e, d in calls if e == "labeling.appended"]
    assert ev and ev[0]["target"] == CASE and ev[0]["session_id"] == "tab-a"


def test_reference_column_mirrors_a_comparable_variable(client: TestClient, pid: str) -> None:
    """LBL-09 / VAR-13: a read-only column that follows `phase.effective` live; patient tables
    and non-comparable variables are refused."""
    wait_var(client, pid, "phase.effective")
    bad = client.post(f"{lab(pid)}/tables", json={"name": "Per patient", "level": "case",
                      "columns": [{"name": "Phase", "ref": "phase.effective"}]})  # fmt: skip
    assert_problem(bad, "validation")
    bad = client.post(f"{lab(pid)}/tables", json={"name": "Dates", "level": "scan",
                      "columns": [{"name": "When", "ref": "scan_date"}]})  # fmt: skip
    assert_problem(bad, "validation")
    cols = [{"name": "App phase", "ref": "phase.effective"}, {"name": "Mine", "type": "text"}]
    r = client.post(f"{lab(pid)}/tables", json={"name": "Phase check", "level": "scan",
                    "columns": cols})  # fmt: skip
    assert r.status_code == 201, r.text
    t = r.json()
    ref = col(t, "App phase")
    assert next(c for c in t["columns"] if c["column_id"] == ref)["ref"] == "phase.effective"
    url = f"{lab(pid)}/tables/{t['table_id']}"
    target = f"{CASE}.01"
    row = client.get(f"{url}/cells", params={"q": target}).json()["items"][0]
    before = client.get(f"{API}/projects/{pid}/items/{ITEM}").json()["phase"]["canonical"]
    assert row["values"][ref] == before
    # read-only: no cell events of its own; not a layer or variable itself (LBL-06)
    w = client.post(f"{url}/cells", json={"cells": [{"column_id": ref, "target": target,
                    "value": "NC"}]}, headers=HDR)  # fmt: skip
    assert_problem(w, "validation")
    assert not any(v["name"] == "lbl.phase_check.app_phase" for v in
                   client.get(f"{API}/projects/{pid}/variables").json()["variables"])  # fmt: skip
    # follows a native phase selection (PHS-03 → VAR-12)
    new = next(p for p in ("NC", "CMP", "NP", "EP") if p != before)
    sel = client.post(f"{API}/projects/{pid}/phase/events", headers=HDR,
                      json={"case_id": CASE, "scan_idx": "01", "value": new})  # fmt: skip
    assert sel.status_code == 201, sel.text
    end = time.monotonic() + 10
    while time.monotonic() < end:
        row = client.get(f"{url}/cells", params={"q": target}).json()["items"][0]
        if row["values"].get(ref) == new:
            break
        time.sleep(0.2)
    assert row["values"][ref] == new
    exported = client.get(f"{url}/export").text
    assert "App phase" in exported.splitlines()[0] and new in exported
