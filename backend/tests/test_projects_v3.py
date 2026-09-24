"""Format 3 (ADR-0019): neutral projects (PRJ-14), If-Match (PRJ-15), packs (PRJ-16, API-28),
view-only links (PRJ-17, API-60/61, TST-18) and the 2 → 3 migration (PRJ-11)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_api_ingest import API, ctx_of, do_import, wait
from tests.test_contract import assert_problem
from tests.test_projects_api import patch_project

HDR = {"X-Reviewer": "Dr. AP"}
ITEM = "case_00001.01.complete.-"


def neutral(c: TestClient, **body: object) -> str:
    r = c.post(f"{API}/projects", json={"name": "n", **body})
    assert r.status_code == 201, r.text
    return str(r.json()["project_id"])


def test_new_project_is_neutral_with_optional_modality(client: TestClient) -> None:
    p = client.get(f"{API}/projects/{neutral(client)}").json()
    assert p["label_map"] == [] and p["packs"] == [] and p["phase_vocabulary"] == []
    assert p["default_modality"] == "CT" and p["view_token"] is None and p["view_url"] is None
    assert p["display"]["layout"] == "four-up" and p["display"]["convention"] == "radiological"
    assert p["display"]["wl"] == {"CT": {"ww": 400, "wl": 50}, "MR": "percentile"}
    mr = client.get(f"{API}/projects/{neutral(client, default_modality='MR')}").json()
    assert mr["default_modality"] == "MR"
    bad = client.post(f"{API}/projects", json={"name": "x", "default_modality": "PET"})
    assert_problem(bad, "validation")


def test_if_match_etag(client: TestClient) -> None:
    pid = neutral(client)
    got = client.get(f"{API}/projects/{pid}")
    etag = got.headers["ETag"]
    assert etag == got.json()["etag"]
    url = f"{API}/projects/{pid}"
    assert_problem(client.patch(url, json={"name": "a"}), "precondition-required")
    ok = client.patch(url, json={"name": "a"}, headers={"If-Match": etag})
    assert ok.status_code == 200 and ok.headers["ETag"] != etag
    stale = client.patch(url, json={"name": "b"}, headers={"If-Match": etag})
    assert_problem(stale, "precondition-failed")
    assert stale.json()["actions"] == ["reload"]
    assert client.get(url).json()["name"] == "a"  # the stale write changed nothing
    display = {"interpolation": "nearest", "convention": "neurological", "use_dicom_window": False}
    r = patch_project(client, pid, {"default_modality": "mixed", "display": display})
    assert r.json()["default_modality"] == "mixed"
    assert r.json()["display"]["interpolation"] == "nearest"


def test_packs_list_and_apply_never_delete(client: TestClient, data_root: Path) -> None:
    packs = {p["pack_id"]: p for p in client.get(f"{API}/packs").json()}
    assert packs["ccrcc"]["labels"] == ["kidney", "tumor", "cyst"]
    assert packs["ccrcc"]["target_profile"] == "kidneys" and packs["ccrcc"]["plugin"] == "ccrcc"
    assert "generic-ct" in packs
    pid = neutral(client)
    do_import(client, pid, data_root)
    before = client.get(f"{API}/projects/{pid}").json()
    assert [e["name"] for e in before["label_map"]] == ["label_1", "label_2", "label_3"]
    raw_phases = {ph for c in client.get(f"{API}/projects/{pid}/cases").json()["items"]
                  for ph in c["phases"]}  # fmt: skip
    assert "ART" in raw_phases  # no pack: raw values
    ev = {"item_id": ITEM, "target": "seg", "status": "accepted"}
    assert client.post(f"{API}/projects/{pid}/curation/events", json=ev, headers=HDR).is_success
    r = client.post(f"{API}/projects/{pid}/packs", json={"pack_id": "ccrcc"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project"]["packs"] == ["ccrcc"] and body["job_id"]
    wait(client, body["job_id"])
    after = client.get(f"{API}/projects/{pid}").json()
    assert [e["name"] for e in after["label_map"]] == ["kidney", "tumor", "cyst"]
    phases = {ph for c in client.get(f"{API}/projects/{pid}/cases").json()["items"]
              for ph in c["phases"]}  # fmt: skip
    assert phases <= {"NC", "CMP", "NP", "EP", "UNK"}
    assert client.get(f"{API}/projects/{pid}/curation/events").json()["total"] == 1  # kept
    again = client.post(f"{API}/projects/{pid}/packs", json={"pack_id": "ccrcc"}).json()
    assert again["project"]["packs"] == ["ccrcc"]  # recorded once
    assert_problem(client.post(f"{API}/projects/{pid}/packs", json={"pack_id": "no"}), "not-found")


def test_view_only_link(client: TestClient, data_root: Path) -> None:
    """TST-18: reads only, never the project_id, rotation revokes the old token."""
    pid = neutral(client, packs=["ccrcc"])
    do_import(client, pid, data_root)
    created = client.post(f"{API}/projects/{pid}/view-token").json()
    token = created["view_token"]
    assert created["view_url"].endswith(f"/v/{token}")
    v = f"{API}/view/{token}"
    proj = client.get(v)
    assert proj.status_code == 200 and pid not in proj.text
    assert proj.json()["read_only"] is True and proj.json()["project_id"] == f"view-{token}"
    assert all(r["path"] == "" for r in proj.json()["path_roots"])
    cases = client.get(f"{v}/cases").json()
    assert cases["total"] > 0 and pid not in json.dumps(cases)
    assert client.get(f"{v}/cases/case_00001").status_code == 200
    img = client.get(f"{v}/items/{ITEM}/image")
    assert img.status_code == 200 and img.content[:2] == b"\x1f\x8b"
    assert client.get(f"{v}/items/{ITEM}/mask", params={"seg": "imported"}).status_code == 200
    assert client.get(f"{v}/curation/state").status_code == 200
    assert client.get(f"{v}/segmentations").status_code == 200
    # No writes and no unlisted reads on this prefix
    ev = {"item_id": ITEM, "target": "seg", "status": "accepted"}
    assert client.post(f"{v}/curation/events", json=ev, headers=HDR).status_code == 405
    assert client.patch(v, json={"name": "x"}).status_code == 405
    assert_problem(client.get(f"{v}/roots"), "not-found")
    assert_problem(client.get(f"{v}/imports"), "not-found")
    # Rotation revokes the old token; revoke removes the link
    new = client.post(f"{API}/projects/{pid}/view-token").json()["view_token"]
    assert new != token
    assert_problem(client.get(v), "not-found")
    assert client.get(f"{API}/view/{new}/cases").status_code == 200
    assert client.delete(f"{API}/projects/{pid}/view-token").status_code == 204
    assert_problem(client.get(f"{API}/view/{new}"), "not-found")
    assert_problem(client.get(f"{API}/view/short"), "not-found")


def test_bundle_never_carries_the_view_token(client: TestClient) -> None:
    pid = neutral(client)
    client.post(f"{API}/projects/{pid}/view-token")
    data = client.post(f"{API}/projects/{pid}/bundle").content
    raw = json.loads(zipfile.ZipFile(io.BytesIO(data)).read(f"{pid}/project.json"))
    assert raw["view_token"] is None


def test_v2_project_migrates_to_v3(client: TestClient) -> None:
    ws = ctx_of(client).workspace
    pid = neutral(client)
    folder = ws.project_dir(pid)
    raw = json.loads((folder / "project.json").read_text())
    for k in ("packs", "default_modality", "display", "view_token", "label_map",
              "phase_vocabulary", "phase_mapping", "phase_priority"):  # fmt: skip
        raw.pop(k)
    raw.update(format_version=2, viewer_defaults={"ww": 300, "wl": 40, "layout": "one-up"})
    (folder / "project.json").write_text(json.dumps(raw))  # v2 without `preset` = ccRCC
    ws.invalidate(pid)
    p = client.get(f"{API}/projects/{pid}").json()
    assert p["format_version"] == 3 and p["packs"] == ["ccrcc"]
    assert [e["name"] for e in p["label_map"]] == ["kidney", "tumor", "cyst"]
    assert p["phase_vocabulary"] == ["NC", "CMP", "NP", "EP", "UNK"]
    assert p["display"]["layout"] == "one-up-axial" and p["display"]["wl"]["CT"] == {
        "ww": 300,
        "wl": 40,
    }
    assert p["default_modality"] == "CT" and p["view_token"] is None
    assert (folder / "project.json.v2.bak").is_file()
    raw.update(preset="none")
    (folder / "project.json").write_text(json.dumps(raw))
    ws.invalidate(pid)
    p = client.get(f"{API}/projects/{pid}").json()
    assert p["packs"] == [] and p["label_map"] == []
