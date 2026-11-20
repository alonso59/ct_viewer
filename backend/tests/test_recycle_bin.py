"""CUR-17 / API-82: list, restore and permanently delete recycled scans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.fsio import read_jsonl
from app.ingest import recycle, recycle_bin
from tests.test_api_ingest import ctx_of, wait
from tests.test_recycle import API, preview, setup_scan

R = {"X-Reviewer": "Reviewer"}


def recycled(client: TestClient, data_root: Path) -> tuple[str, str, str]:
    pid, iid = setup_scan(client, data_root)
    plan = preview(client, pid, iid)
    res = client.post(
        f"{API}/projects/{pid}/items/{iid}/recycle",
        json={"confirmed": True, "token": plan["token"]},
        headers=R,
    )
    assert res.status_code == 200, res.text
    return pid, iid, res.json()["recycle_id"]


def restore_plan(client: TestClient, pid: str, rid: str) -> dict[str, Any]:
    res = client.get(f"{API}/projects/{pid}/recycle-bin/{rid}/restore")
    assert res.status_code == 200, res.text
    return res.json()  # type: ignore[no-any-return]


def test_CUR17_lists_and_restores_scan_keeping_later_edits(
    client: TestClient, data_root: Path
) -> None:
    pid, iid = setup_scan(client, data_root)
    ctx = ctx_of(client)
    item = ctx.index.get_item(pid, iid)
    image = ctx.workspace.resolver(pid).resolve(item.image.ref)  # type: ignore[union-attr]
    image_bytes = image.read_bytes()
    metadata = read_jsonl(data_root / "metadata.jsonl")
    plan = preview(client, pid, iid)
    rid = client.post(
        f"{API}/projects/{pid}/items/{iid}/recycle",
        json={"confirmed": True, "token": plan["token"]},
        headers=R,
    ).json()["recycle_id"]

    [entry] = client.get(f"{API}/projects/{pid}/recycle-bin").json()
    assert entry["recycle_id"] == rid and entry["available"] is True
    assert (entry["case_id"], entry["reviewer"]) == (item.case_id, "Reviewer")
    assert entry["n_files"] >= 1 and entry["projects"] == [pid]

    # An edit made after the recycle survives the restore
    later = {"case_id": "case_later", "scan_idx": "0", "note": "added after the recycle"}
    with (data_root / "metadata.jsonl").open("a") as fh:
        fh.write('{"case_id": "case_later", "scan_idx": "0", "note": "added after the recycle"}\n')

    restore = restore_plan(client, pid, rid)
    assert iid in restore["item_ids"] and restore["n_files"] >= 1
    assert not image.exists()  # the preview writes nothing
    url = f"{API}/projects/{pid}/recycle-bin/{rid}/restore"
    body = {"confirmed": True, "token": restore["token"]}
    assert client.post(url, json=body).status_code == 428
    assert client.post(url, json={**body, "token": "stale"}, headers=R).status_code == 412
    res = client.post(url, json=body, headers=R)
    assert res.status_code == 200, res.text

    assert image.read_bytes() == image_bytes
    rows = read_jsonl(data_root / "metadata.jsonl")
    assert later in rows and all(r in rows for r in metadata) and len(rows) == len(metadata) + 1
    assert iid in ctx.index.load(pid).by_id
    assert item.case_id in ctx.index.load(pid).cases_by_id
    assert not (data_root / "recycle_bin" / rid).exists()
    assert client.get(f"{API}/projects/{pid}/recycle-bin").json() == []
    # The journal no longer excludes the scan from a rebuild
    from app.api.v1.imports import ingest_service

    job = client.portal.call(ingest_service(ctx).reindex, pid)  # type: ignore[union-attr]
    assert job and wait(client, job).status == "succeeded"
    assert iid in ctx.index.load(pid).by_id


def test_CUR16_CUR17_recycle_and_restore_only_one_voi(client: TestClient, data_root: Path) -> None:
    pid, _ = setup_scan(client, data_root)
    other = client.post(f"{API}/projects", json={"name": "Shared dataset"}).json()["project_id"]
    from tests.test_api_ingest import do_import

    do_import(client, other, data_root)
    ctx = ctx_of(client)
    for job in ctx.jobs.list():
        wait(client, job.job_id)
    full, left, right = (
        "case_00001.03.complete.-",
        "case_00001.03.voi.L",
        "case_00001.03.voi.R",
    )
    resolver = ctx.workspace.resolver(pid)
    volumes: dict[Path, bytes] = {
        path: path.read_bytes()
        for iid in (full, left, right)
        for vol in ctx.index.get_item(pid, iid).volumes()
        if (path := resolver.resolve(vol.ref)).is_file()
    }
    left_paths = {resolver.resolve(vol.ref) for vol in ctx.index.get_item(pid, left).volumes()}

    catalog = data_root / "voi/voi_catalog.jsonl"
    rows = read_jsonl(catalog)
    metadata = read_jsonl(data_root / "metadata.jsonl")
    url = f"{API}/projects/{pid}/items/{left}/recycle"
    plan = client.get(url, params={"scope": "voi"}).json()
    assert plan["item_ids"] == [left] and plan["scope"] == "voi"
    assert set(plan["projects"]) == {pid, other}
    body = {"confirmed": True, "token": plan["token"]}
    assert client.post(url, json=body, headers=R).status_code == 412
    response = client.post(url, params={"scope": "voi"}, json=body, headers=R)
    assert response.status_code == 200, response.text
    rid = response.json()["recycle_id"]

    assert read_jsonl(data_root / "metadata.jsonl") == metadata
    assert read_jsonl(catalog) == [
        row
        for row in rows
        if (row["case_id"], str(row["scan_idx"]), row["side"]) != ("case_00001", "03", "L")
    ]
    for path, original in volumes.items():
        if path in left_paths:
            assert not path.exists()
        else:
            assert path.read_bytes() == original
    for project in (pid, other):
        entries = ctx.index.load(project).by_id
        assert full in entries and right in entries and left not in entries

    from app.api.v1.imports import ingest_service

    job = client.portal.call(ingest_service(ctx).reindex, pid)  # type: ignore[union-attr]
    assert job and wait(client, job).status == "succeeded"
    assert left not in ctx.index.load(pid).by_id

    [entry] = client.get(f"{API}/projects/{other}/recycle-bin").json()
    assert entry["scope"] == "voi" and entry["item_ids"] == [left]
    restore = restore_plan(client, other, rid)
    url = f"{API}/projects/{other}/recycle-bin/{rid}/restore"
    response = client.post(url, json={"confirmed": True, "token": restore["token"]}, headers=R)
    assert response.status_code == 200, response.text
    assert restore["item_ids"] == [left]
    assert read_jsonl(data_root / "metadata.jsonl") == metadata
    restored_rows = read_jsonl(catalog)
    assert len(restored_rows) == len(rows) and all(row in restored_rows for row in rows)
    assert all(path.read_bytes() == original for path, original in volumes.items())
    for project in (pid, other):
        assert {full, left, right} <= ctx.index.load(project).by_id.keys()


def test_CUR17_refuses_restore_over_an_existing_file(client: TestClient, data_root: Path) -> None:
    pid, _, rid = recycled(client, data_root)
    ctx = ctx_of(client)
    manifest = recycle.read_json(data_root / "recycle_bin" / rid / "manifest.json")
    taken = Path(manifest["files"][0]["original"])
    taken.write_bytes(b"re-imported")
    res = client.get(f"{API}/projects/{pid}/recycle-bin/{rid}/restore")
    assert res.status_code == 422 and "already exists" in res.text
    assert taken.read_bytes() == b"re-imported"
    assert (data_root / "recycle_bin" / rid / manifest["files"][0]["recycled"]).is_file()
    assert not set(manifest["scan"]["item_ids"]) & set(ctx.index.load(pid).by_id)


def test_CUR17_permanent_delete_keeps_only_the_rebuild_exclusion(
    client: TestClient, data_root: Path
) -> None:
    pid, iid, rid = recycled(client, data_root)
    ctx = ctx_of(client)
    journal_path = ctx.workspace.project_dir(pid) / "logs/recycle.jsonl"
    [entry] = [e for e in read_jsonl(journal_path) if e["recycle_id"] == rid]
    url = f"{API}/projects/{pid}/recycle-bin/{rid}/delete"
    assert client.post(url, json={"confirmed": False}).status_code == 422
    assert (data_root / "recycle_bin" / rid).is_dir()
    assert client.post(url, json={"confirmed": True}).status_code == 204
    assert not (data_root / "recycle_bin" / rid).exists()
    assert [e for e in read_jsonl(journal_path) if e["recycle_id"] == rid] == [
        {"recycle_id": rid, "item_ids": entry["item_ids"], "purged": True}
    ]
    assert client.get(f"{API}/projects/{pid}/recycle-bin").json() == []
    assert client.post(url, json={"confirmed": True}).status_code == 404
    assert iid in recycle.excluded_items(ctx.workspace.project_dir(pid))


def test_CUR17_rolls_back_a_failed_restore(
    client: TestClient, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, iid, rid = recycled(client, data_root)
    ctx = ctx_of(client)
    folder = data_root / "recycle_bin" / rid
    before = {
        p: p.read_bytes() for p in data_root.rglob("*") if p.is_file() and folder not in p.parents
    }
    plan = restore_plan(client, pid, rid)
    original_write = recycle.atomic_write_bytes

    failed = False

    def fail(path: Path, data: bytes, **kwargs: Any) -> None:
        nonlocal failed
        if path.name == "items.jsonl" and path.parent.name == "index" and not failed:
            failed = True
            raise OSError("simulated disk failure")
        original_write(path, data, **kwargs)

    monkeypatch.setattr(recycle, "atomic_write_bytes", fail)
    with pytest.raises(OSError, match="simulated"):
        client.post(
            f"{API}/projects/{pid}/recycle-bin/{rid}/restore",
            json={"confirmed": True, "token": plan["token"]},
            headers=R,
        )
    monkeypatch.undo()
    after = {
        p: p.read_bytes() for p in data_root.rglob("*") if p.is_file() and folder not in p.parents
    }
    assert after == before
    assert recycle.read_json(folder / "restore.json")["status"] == "rolled_back"
    assert iid not in ctx.index.load(pid).by_id
    # It can still be restored afterwards
    plan = restore_plan(client, pid, rid)
    res = client.post(
        f"{API}/projects/{pid}/recycle-bin/{rid}/restore",
        json={"confirmed": True, "token": plan["token"]},
        headers=R,
    )
    assert res.status_code == 200, res.text


def test_CUR17_recovers_an_interrupted_restore(
    client: TestClient, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, iid, rid = recycled(client, data_root)
    ctx = ctx_of(client)
    folder = data_root / "recycle_bin" / rid
    metadata = (data_root / "metadata.jsonl").read_bytes()
    plan = restore_plan(client, pid, rid)
    # Simulate a stop after files and index were written but before the commit marker
    monkeypatch.setattr(recycle_bin.shutil, "rmtree", lambda *a, **k: None)
    res = client.post(
        f"{API}/projects/{pid}/recycle-bin/{rid}/restore",
        json={"confirmed": True, "token": plan["token"]},
        headers=R,
    )
    assert res.status_code == 200, res.text
    transaction = recycle.read_json(folder / "restore.json")
    transaction["status"] = "prepared"
    recycle.atomic_write_json(folder / "restore.json", transaction)
    pending = ctx.settings.workspace_root / "recycle_pending" / f"{rid}.restore.json"
    recycle.atomic_write_json(pending, {"manifest": str(folder / "restore.json")})
    recycle.RecycleService(ctx.workspace, ctx.index, ctx.jobs, ctx.bus).recover()
    assert (data_root / "metadata.jsonl").read_bytes() == metadata
    assert iid not in ctx.index.load(pid).by_id
    assert all((folder / f["recycled"]).is_file() for f in transaction["files"])
    assert not pending.exists()
    assert [e["recycle_id"] for e in client.get(f"{API}/projects/{pid}/recycle-bin").json()] == [
        rid
    ]
