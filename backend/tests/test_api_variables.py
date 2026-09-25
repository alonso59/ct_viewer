"""TST-03: API-16..18 over the synthetic fixtures (VAR-*), packs on create (PRJ-16)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.test_api_ingest import API, ctx_of, do_import
from tests.test_contract import assert_problem
from tests.test_projects_api import patch_project


@pytest.fixture
def pid(client: TestClient, data_root: Path) -> str:
    r = client.post(f"{API}/projects", json={"name": "vars", "packs": ["ccrcc"]})
    assert r.status_code == 201, r.text
    p = str(r.json()["project_id"])
    do_import(client, p, data_root)
    return p


def catalog(c: TestClient, pid: str) -> dict[str, Any]:
    r = c.get(f"{API}/projects/{pid}/variables")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def var(cat: dict[str, Any], name: str) -> dict[str, Any]:
    return next(v for v in cat["variables"] if v["name"] == name)


def test_catalog_profiles_the_fixture_as_documented(
    client: TestClient, pid: str, fixtures_copy: Path
) -> None:
    expected = json.loads((fixtures_copy / "expected.json").read_text())["variables"]
    cat = catalog(client, pid)
    names = {v["name"] for v in cat["variables"]}
    assert "group" not in names  # ADR-0011: nothing assumed
    study = {
        v["name"] for v in cat["variables"] if v["group"] == "study" and v["source"] != "layer"
    }
    assert study == set(expected["study"])
    # VAR-12/13 (ADR-0026): the effective phase is a comparable scan-level layer variable
    eff = var(cat, "phase.effective")
    assert (eff["source"], eff["level"], eff["type"], eff["comparable"]) == (
        "layer",
        "scan",
        "categorical",
        True,
    )
    assert not var(cat, "scan_date")["comparable"]
    for n in expected["compositional"]:
        v = var(cat, n)
        assert (v["type"], v["level"], v["visible"]) == ("continuous", "case", True)
        assert 30 < v["profile"]["missing_pct"] < 80
    for n in expected["numeric_discrete"]:
        assert (var(cat, n)["type"], var(cat, n)["review"]) == ("numeric-discrete", True)
    excluded = {e["name"] for e in cat["excluded"]}
    assert set(expected["excluded"]) <= excluded and "raw_metadata" in excluded
    m = var(cat, "modality")
    assert m["group"] == "acquisition" and "confounder" in m["tags"] and not m["visible"]
    assert {t["value"] for t in m["profile"]["top"]} == {"CT", "MR"}
    assert var(cat, "scan_date")["type"] == "date"
    pdir = ctx_of(client).workspace.project_dir(pid)
    assert (pdir / "variables/catalog.json").is_file()
    assert (pdir / "index/variables.parquet").is_file()


def test_patch_confirms_type(client: TestClient, pid: str) -> None:
    url = f"{API}/projects/{pid}/variables/grade"
    r = client.patch(url, json={"type": "categorical", "tags": ["outcome"]})
    assert r.status_code == 200, r.text
    v = var(r.json(), "grade")
    assert (v["type"], v["inferred_type"], v["review"], v["overridden"]) == (
        "categorical",
        "numeric-discrete",
        False,
        True,
    )
    r = client.patch(url, json={"visible": False})
    v = var(r.json(), "grade")
    assert v["tags"] == ["outcome"] and v["type"] == "categorical" and not v["visible"]
    # Overrides survive a re-import (VAR-11).
    root = ctx_of(client).workspace.get(pid).path_roots[0].path
    do_import(client, pid, Path(root))
    assert var(catalog(client, pid), "grade")["type"] == "categorical"
    assert_problem(client.patch(f"{API}/projects/{pid}/variables/nope", json={}), "not-found")
    assert_problem(client.patch(url, json={"type": "weird"}), "validation")


def test_derived_variables_and_filters(client: TestClient, pid: str) -> None:
    base = f"{API}/projects/{pid}/variables/derived"
    two = {"op": "bin", "name": "marker_hi", "source": "marker_a", "thresholds": [50],
           "labels": ["low", "high"]}  # fmt: skip
    r = client.post(base, json=two)
    assert r.status_code == 201, r.text
    assert {t["value"] for t in var(r.json(), "marker_hi")["profile"]["top"]} == {"low", "high"}
    three = {"op": "bin", "name": "score3", "source": "score", "quantiles": [1 / 3, 2 / 3]}
    assert client.post(base, json=three).status_code == 201
    vendor = {"op": "recode", "name": "vendor", "source": "manufacturer",
              "map": {"SIEMENS": "Siemens", "Siemens Healthineers": "Siemens",
                      "Philips Medical Systems": "Philips", "PHILIPS": "Philips",
                      "GE MEDICAL SYSTEMS": "GE"}}  # fmt: skip
    assert client.post(base, json=vendor).status_code == 201
    dom = {"op": "dominant", "name": "marker_dom", "sources": ["marker_a", "marker_b"]}
    cat = client.post(base, json=dom).json()
    assert {t["value"] for t in var(cat, "vendor")["profile"]["top"]} == {
        "Siemens",
        "Philips",
        "GE",
    }
    assert {t["value"] for t in var(cat, "marker_dom")["profile"]["top"]} <= {
        "marker_a",
        "marker_b",
        "tie",
    }
    assert [d["name"] for d in cat["derived"]] == ["marker_hi", "score3", "vendor", "marker_dom"]
    # Filters work on derived variables too (VAR-10).
    cases = client.get(f"{API}/projects/{pid}/cases?var.marker_hi=high&limit=2000").json()
    hi = {c["case_id"] for c in cases["items"]}
    lo = {
        c["case_id"]
        for c in client.get(f"{API}/projects/{pid}/cases?var.marker_hi=low").json()["items"]
    }
    assert hi and lo and not hi & lo
    # Errors: duplicate name, bad source, in-use delete, unknown delete.
    assert_problem(client.post(base, json=two), "validation")
    assert_problem(client.post(base, json={**two, "name": "x2", "source": "vendor"}), "validation")
    bad_name = {**two, "name": "2bad"}
    assert_problem(client.post(base, json=bad_name), "validation")
    grow = {"op": "recode", "name": "hi2", "source": "marker_hi", "map": {"high": "H"}}
    assert client.post(base, json=grow).status_code == 201
    assert_problem(client.delete(f"{base}/marker_hi"), "validation")
    assert client.delete(f"{base}/hi2").status_code == 200
    r = client.delete(f"{base}/marker_hi")
    assert r.status_code == 200 and all(v["name"] != "marker_hi" for v in r.json()["variables"])
    assert_problem(client.delete(f"{base}/marker_hi"), "not-found")


def test_external_table(client: TestClient, pid: str) -> None:
    url = f"{API}/projects/{pid}/variables/external"
    body = "case_id,biopsy,marker_a\ncase_00030,pos,1\ncase_00031,neg,2\ncase_99999,pos,3\n"
    r = client.post(url, files={"file": ("labs.csv", body.encode(), "text/csv")})
    assert r.status_code == 201, r.text
    rep = r.json()
    assert (rep["n_rows"], rep["n_matched"], rep["n_unmatched"]) == (3, 2, 1)
    assert rep["unmatched_keys"] == ["case_99999"] and rep["conflicts"] == ["marker_a"]
    cat = catalog(client, pid)
    b = var(cat, "biopsy")
    assert (b["source"], b["level"], b["group"]) == ("external", "case", "study")
    assert var(cat, "marker_a")["source"] == "metadata"
    assert len(cat["external"]) == 1
    pdir = ctx_of(client).workspace.project_dir(pid)
    assert (pdir / "variables/external" / cat["external"][0]["filename"]).is_file()
    got = client.get(f"{API}/projects/{pid}/cases?var.biopsy=pos").json()["items"]
    assert [c["case_id"] for c in got] == ["case_00030"]
    tsv = "patient_id\tsite\nP030\tnorth\n"
    r = client.post(url, files={"file": ("s.tsv", tsv.encode(), "text/tab-separated-values")})
    assert r.status_code == 201 and r.json()["table"]["key"] == "patient_id"
    assert_problem(
        client.post(url, files={"file": ("x.csv", b"foo,bar\n1,2\n", "text/csv")}), "validation"
    )
    only_taken = b"case_id,marker_a\ncase_00030,1\n"
    assert_problem(
        client.post(url, files={"file": ("y.csv", only_taken, "text/csv")}), "validation"
    )


def test_empty_project_has_an_empty_catalog(client: TestClient) -> None:
    p = client.post(f"{API}/projects", json={"name": "empty", "packs": ["ccrcc"]}).json()[
        "project_id"
    ]
    cat = catalog(client, p)
    assert cat["variables"] == [] and cat["n_items"] == 0


@pytest.mark.parametrize(
    ("preset", "phases", "labels"),
    [
        ("ccrcc", {"NC", "CMP", "NP", "EP", "UNK"}, ["kidney", "tumor", "cyst"]),
        ("generic-ct", {"NC", "ART", "PV", "DELAYED", "UNK"}, ["label_1", "label_2", "label_3"]),
        ("none", {"NC", "ART", "VEN", "CMP", "NP", "EP", "UNK"}, ["label_1", "label_2", "label_3"]),
    ],
)
def test_packs_on_create_seed_phases_and_labels(
    client: TestClient, data_root: Path, preset: str, phases: set[str], labels: list[str]
) -> None:
    packs = [] if preset == "none" else [preset]
    r = client.post(f"{API}/projects", json={"name": preset, "packs": packs})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["packs"] == packs
    do_import(client, p["project_id"], data_root)
    cases = client.get(f"{API}/projects/{p['project_id']}/cases?limit=2000").json()["items"]
    seen = {ph for c in cases for ph in c["phases"]}
    assert seen <= phases and len(seen) >= 3
    detail = client.get(f"{API}/projects/{p['project_id']}").json()
    assert [lab["name"] for lab in detail["label_map"]] == labels
    if preset == "generic-ct":
        c1 = next(c for c in cases if c["case_id"] == "case_00001")
        assert c1["phases"] == ["NC", "ART", "PV"]  # vocabulary order


def test_phase_config_patch_is_validated(client: TestClient) -> None:
    p = client.post(f"{API}/projects", json={"name": "x", "packs": ["ccrcc"]}).json()["project_id"]
    url = f"{API}/projects/{p}"
    del url
    body: dict[str, Any] = {"phase_vocabulary": ["NC", "CMP", "UNK"], "phase_priority": ["UNK"]}
    body["phase_mapping"] = {"ART": "ZZZ"}
    assert_problem(patch_project(client, p, body), "validation")
    body["phase_mapping"] = {"ARTERIAL-LATE": "CMP"}
    r = patch_project(client, p, body)
    assert r.status_code == 200 and r.json()["phase_mapping"] == {"ARTERIAL-LATE": "CMP"}
    assert_problem(client.post(f"{API}/projects", json={"name": "y", "packs": ["z"]}), "validation")


def test_case_summaries_carry_variables_and_thumbnail_item(client: TestClient, pid: str) -> None:
    cases = client.get(f"{API}/projects/{pid}/cases?limit=2000").json()["items"]
    c30 = next(c for c in cases if c["case_id"] == "case_00030")
    assert set(c30["variables"]) >= {"marker_a", "marker_b", "score", "patient_sex"}
    assert "manufacturer" not in c30["variables"]  # acquisition: hidden by default
    assert c30["thumb_item_id"] == "case_00030.01.complete.-"  # NP first (ccrcc priority)
    c1 = next(c for c in cases if c["case_id"] == "case_00001")
    assert c1["thumb_item_id"] == "case_00001.03.complete.-"  # VEN -> NP
    detail = client.get(f"{API}/projects/{pid}/cases/case_00030").json()["case"]
    assert detail["variables"] == c30["variables"]
