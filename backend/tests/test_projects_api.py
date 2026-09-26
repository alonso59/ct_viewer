"""API-02..05 projects and roots (PRJ-01..06; BE-08; TST-03)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.fsio import atomic_write_json, read_json
from app.core.ids import new_ulid
from app.imaging.fingerprint import quick_fingerprint
from app.ingest.models import Item, PhaseInfo, VolumeRef
from app.ingest.store import IndexStore
from app.jobs.types import JobInfo
from app.projects.relink import evenly_spaced

API = "/api/v1"
PROBLEM = "application/problem+json"


@pytest.fixture
def published(client: TestClient) -> list[tuple[str, str, dict[str, Any]]]:
    calls: list[tuple[str, str, dict[str, Any]]] = []
    ctx = client.app.state.ctx  # type: ignore[attr-defined]
    ctx.bus.publish = lambda pid, event, data: calls.append((pid, event, data))
    return calls


def assert_problem(res: Any, status: int, slug: str) -> None:
    assert res.status_code == status, res.text
    assert res.headers["content-type"].startswith(PROBLEM)
    assert res.json()["type"] == f"/problems/{slug}"


def create(client: TestClient, name: str = "Demo") -> dict[str, Any]:
    res = client.post(
        f"{API}/projects", json={"name": name, "description": "d", "packs": ["ccrcc"]}
    )
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def test_create_list_get(client: TestClient) -> None:
    body = create(client)
    pid = body["project_id"]
    assert body["name"] == "Demo" and body["format_version"] == 3
    assert body["share_url"].endswith(f"/p/{pid}")
    rows = client.get(f"{API}/projects").json()
    assert [r["project_id"] for r in rows] == [pid]
    assert rows[0]["last_opened_at"] is None and rows[0]["n_cases"] == 0
    got = client.get(f"{API}/projects/{pid}")
    assert got.status_code == 200 and got.json()["project_id"] == pid
    assert client.get(f"{API}/projects").json()[0]["last_opened_at"] is not None


def patch_project(c: TestClient, pid: str, body: dict[str, Any]) -> Any:
    """API-03 PATCH with the current ETag (PRJ-15)."""
    etag = c.get(f"{API}/projects/{pid}").headers.get("ETag", "")
    return c.patch(f"{API}/projects/{pid}", json=body, headers={"If-Match": etag})


def test_create_validation(client: TestClient) -> None:
    assert_problem(client.post(f"{API}/projects", json={"name": ""}), 422, "validation")
    assert_problem(client.post(f"{API}/projects", json={}), 422, "validation")


def test_not_found(client: TestClient) -> None:
    for pid in (new_ulid(), "not-a-ulid"):
        assert_problem(client.get(f"{API}/projects/{pid}"), 404, "not-found")
        assert_problem(
            client.patch(f"{API}/projects/{pid}", json={}, headers={"If-Match": "*"}),
            404,
            "not-found",
        )
        assert_problem(client.post(f"{API}/projects/{pid}/archive"), 404, "not-found")
        assert_problem(client.get(f"{API}/projects/{pid}/roots"), 404, "not-found")


def test_no_delete_endpoint(client: TestClient) -> None:
    pid = create(client)["project_id"]
    assert client.delete(f"{API}/projects/{pid}").status_code in (404, 405)
    assert client.get(f"{API}/projects/{pid}").status_code == 200


def test_patch_publishes_changed_fields(
    client: TestClient, published: list[tuple[str, str, dict[str, Any]]]
) -> None:
    pid = create(client)["project_id"]
    display = {"layout": "one-up-axial", "wl": {"CT": {"ww": 350, "wl": 40}}}
    res = patch_project(client, pid, {"name": "Renamed", "description": "d", "display": display})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "Renamed" and body["display"]["wl"]["CT"]["ww"] == 350
    assert published == [(pid, "project.updated", {"fields": ["display", "name"]})]
    assert client.get(f"{API}/projects").json()[0]["name"] == "Renamed"
    bad = patch_project(client, pid, {"label_map": [{"value": 1}]})
    assert_problem(bad, 422, "validation")


def test_archive_unarchive(client: TestClient) -> None:
    pid = create(client)["project_id"]
    res = client.post(f"{API}/projects/{pid}/archive")
    assert res.status_code == 200 and res.json()["archived"] is True
    assert client.get(f"{API}/projects").json() == []
    archived = client.get(f"{API}/projects", params={"archived": "true"}).json()
    assert [r["project_id"] for r in archived] == [pid] and archived[0]["archived"] is True
    assert_problem(client.get(f"{API}/projects/{pid}"), 404, "not-found")
    res = client.post(f"{API}/projects/{pid}/unarchive")
    assert res.status_code == 200 and res.json()["project_id"] == pid
    assert_problem(client.post(f"{API}/projects/{pid}/unarchive"), 404, "not-found")


def test_archive_refused_while_a_job_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRJ-06, API-04, AUD-A5-10: archive is refused (409) while a job of the project is live."""
    pid = create(client)["project_id"]
    ctx = client.app.state.ctx  # type: ignore[attr-defined]
    live = JobInfo(
        job_id="J1", kind="radiomics", project_id=pid, status="running", total=1, created_at="t"
    )
    monkeypatch.setattr(ctx.jobs, "busy", lambda p: live if p == pid else None)
    assert_problem(client.post(f"{API}/projects/{pid}/archive"), 409, "job-conflict")
    assert client.get(f"{API}/projects/{pid}").status_code == 200
    monkeypatch.setattr(ctx.jobs, "busy", lambda p: None)
    assert client.post(f"{API}/projects/{pid}/archive").status_code == 200


def test_format_version_problem(client: TestClient) -> None:
    pid = create(client)["project_id"]
    ctx = client.app.state.ctx  # type: ignore[attr-defined]
    path = ctx.workspace.project_dir(pid) / "project.json"
    atomic_write_json(path, {**read_json(path), "format_version": 99})
    ctx.workspace.invalidate(pid)
    assert_problem(client.get(f"{API}/projects/{pid}"), 409, "format-version-unsupported")


def test_roots_put_and_errors(client: TestClient, data_root: Path, fixtures_copy: Path) -> None:
    pid = create(client)["project_id"]
    assert client.get(f"{API}/projects/{pid}/roots").json() == []
    url = f"{API}/projects/{pid}/roots/DATA"
    res = client.put(url, json={"path": str(data_root)})
    assert res.status_code == 200, res.text
    expected = {"alias": "DATA", "path": str(data_root), "exists": True, "role": "source"}
    assert res.json()["root"] == expected
    assert res.json()["verify"]["sampled"] == 0
    rows = client.get(f"{API}/projects/{pid}/roots").json()
    assert rows == [expected]
    outside = fixtures_copy / "outside"
    assert_problem(client.put(url, json={"path": str(outside)}), 403, "path-outside-root")
    assert_problem(client.put(url, json={"path": "rel/path"}), 422, "validation")
    missing = str(data_root / "nope")
    assert_problem(client.put(url, json={"path": missing}), 422, "validation")
    bad_alias = f"{API}/projects/{pid}/roots/lower"
    assert_problem(client.put(bad_alias, json={"path": str(data_root)}), 422, "validation")
    assert_problem(
        client.put(f"{API}/projects/{new_ulid()}/roots/DATA", json={"path": str(data_root)}),
        404,
        "not-found",
    )


def _item(n: int, ref: str, fp: str | None, *, alias_mask: str | None = None) -> Item:
    return Item(
        item_id=f"case_{n:05d}.01.complete.-",
        case_id=f"case_{n:05d}",
        scan_idx="01",
        scope="complete",
        side="-",
        phase=PhaseInfo(canonical="NC"),
        image=VolumeRef(ref=ref, fp=fp),
        mask=VolumeRef(ref=alias_mask, fp="1-x") if alias_mask else None,
        import_id="imp1",
    )


def test_relink_verify_report(client: TestClient, data_root: Path) -> None:
    pid = create(client)["project_id"]
    ctx = client.app.state.ctx  # type: ignore[attr-defined]
    files = sorted((data_root / "nifti").glob("*.nii.gz"))[:3]
    items = [
        _item(i + 1, f"DATA:nifti/{f.name}", quick_fingerprint(f)) for i, f in enumerate(files)
    ]
    items += [
        _item(10, f"DATA:nifti/{files[0].name}", "1-deadbeef"),
        _item(11, "DATA:nifti/gone.nii.gz", "1-deadbeef"),
        _item(12, f"DATA:nifti/{files[1].name}", None),
        _item(13, "OTHER:x.nii.gz", "1-x"),
    ]
    store: IndexStore = ctx.index
    store.replace(pid, items, [], [])
    res = client.put(f"{API}/projects/{pid}/roots/DATA", json={"path": str(data_root)})
    assert res.status_code == 200, res.text
    v = res.json()["verify"]
    assert (v["sampled"], v["matched"], v["mismatched"], v["missing"]) == (5, 3, 1, 1)
    status = {s["item_id"]: s["status"] for s in v["samples"]}
    assert status["case_00010.01.complete.-"] == "mismatched"
    assert status["case_00011.01.complete.-"] == "missing"


def test_evenly_spaced_caps_sample() -> None:
    assert evenly_spaced(list(range(5)), 20) == [0, 1, 2, 3, 4]
    picked = evenly_spaced(list(range(100)), 20)
    assert len(picked) == 20 and picked[0] == 0 and picked[-1] == 95
