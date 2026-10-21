"""CUR-16 / API-66: dataset recycling, audit metadata and failure atomicity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.fsio import read_json, read_jsonl, write_jsonl_atomic
from app.ingest import recycle
from tests.test_api_ingest import ctx_of, do_import, wait

API = "/api/v1"


def setup_scan(client: TestClient, data_root: Path) -> tuple[str, str]:
    pid = client.post(f"{API}/projects", json={"name": "Recycle"}).json()["project_id"]
    do_import(client, pid, data_root)
    ctx = ctx_of(client)
    # Thumbnail generation is normally a short, independent follow-up job.
    for job in ctx.jobs.list():
        wait(client, job.job_id)
    item = next(
        i
        for i in ctx.index.load(pid).items
        if i.scope == "complete" and i.masks and i.status == "active"
    )
    return pid, item.item_id


def preview(client: TestClient, pid: str, iid: str) -> dict[str, Any]:
    response = client.get(f"{API}/projects/{pid}/items/{iid}/recycle")
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_CUR16_recycles_scan_and_all_metadata(client: TestClient, data_root: Path) -> None:
    pid, iid = setup_scan(client, data_root)
    ctx = ctx_of(client)
    # This scan also owns left/right VOIs: the delete unit is the entire CT, not one item.
    iid = "case_00001.03.complete.-"
    item = ctx.index.get_item(pid, iid)
    original = read_jsonl(data_root / "metadata.jsonl")
    scan_rows = [
        r for r in original if r["case_id"] == item.case_id and str(r["scan_idx"]) == item.scan_idx
    ]
    image = ctx.workspace.resolver(pid).resolve(item.image.ref)  # type: ignore[union-attr]
    image_bytes = image.read_bytes()
    plan = preview(client, pid, iid)
    assert len(plan["item_ids"]) >= 3
    assert plan["recycle_bin"] == str(data_root / "recycle_bin")
    assert image.exists() and read_jsonl(data_root / "metadata.jsonl") == original
    response = client.post(
        f"{API}/projects/{pid}/items/{iid}/recycle",
        json={"confirmed": True, "token": plan["token"]},
        headers={"X-Reviewer": "Reviewer"},
    )
    assert response.status_code == 200, response.text
    destination = Path(response.json()["recycle_dir"])
    manifest = read_json(destination / "manifest.json")
    assert manifest["status"] == "completed" and manifest["reviewer"] == "Reviewer"
    assert manifest["removed_metadata"][str(data_root / "metadata.jsonl")] == scan_rows
    assert (destination / "files" / image.relative_to(data_root)).read_bytes() == image_bytes
    assert not image.exists()
    remaining = read_jsonl(data_root / "metadata.jsonl")
    assert remaining == [r for r in original if r not in scan_rows]
    assert not any(r.get("recycle_id") for r in remaining)
    assert not any(
        i.scan_idx == item.scan_idx and i.case_id == item.case_id for i in ctx.index.load(pid).items
    )
    journal = read_jsonl(ctx.workspace.project_dir(pid) / "logs/recycle.jsonl")
    assert journal[-1]["recycle_id"] == response.json()["recycle_id"]
    # Immutable import snapshots do not bring deleted scans back on analyzer activation.
    from app.api.v1.imports import ingest_service

    job = client.portal.call(ingest_service(ctx).reindex, pid)  # type: ignore[union-attr]
    assert job and wait(client, job).status == "succeeded"
    assert iid not in ctx.index.load(pid).by_id
    assert (
        client.post(
            f"{API}/projects/{pid}/items/{iid}/recycle",
            json={"confirmed": True, "token": plan["token"]},
            headers={"X-Reviewer": "Reviewer"},
        ).status_code
        == 404
    )


def test_API66_requires_confirmation_reviewer_and_current_plan(
    client: TestClient, data_root: Path
) -> None:
    pid, iid = setup_scan(client, data_root)
    url = f"{API}/projects/{pid}/items/{iid}/recycle"
    plan = preview(client, pid, iid)
    body = {"confirmed": True, "token": plan["token"]}
    assert client.post(url, json=body).status_code == 428
    assert (
        client.post(url, json={**body, "confirmed": False}, headers={"X-Reviewer": "R"}).status_code
        == 422
    )
    assert (
        client.post(url, json={**body, "token": "stale"}, headers={"X-Reviewer": "R"}).status_code
        == 412
    )
    assert not (data_root / "recycle_bin").exists()


def test_CUR16_rolls_back_after_write_failure(
    client: TestClient, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, iid = setup_scan(client, data_root)
    ctx = ctx_of(client)
    before = {p: p.read_bytes() for p in data_root.rglob("*") if p.is_file()}
    plan = preview(client, pid, iid)
    original_write = recycle.atomic_write_bytes
    failed = False

    def fail_once(path: Path, data: bytes, **kwargs: Any) -> None:
        nonlocal failed
        if path == data_root / "metadata.jsonl" and not failed:
            failed = True
            raise OSError("simulated disk failure")
        original_write(path, data, **kwargs)

    monkeypatch.setattr(recycle, "atomic_write_bytes", fail_once)
    with pytest.raises(OSError, match="simulated"):
        client.post(
            f"{API}/projects/{pid}/items/{iid}/recycle",
            json={"confirmed": True, "token": plan["token"]},
            headers={"X-Reviewer": "R"},
        )
    assert all(p.read_bytes() == content for p, content in before.items())
    assert iid in ctx.index.load(pid).by_id
    assert not read_jsonl(ctx.workspace.project_dir(pid) / "logs/recycle.jsonl")


def test_CUR16_cleans_derived_tables_and_shared_projects(
    client: TestClient, data_root: Path
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    pid, iid = setup_scan(client, data_root)
    other = client.post(f"{API}/projects", json={"name": "Shared"}).json()["project_id"]
    do_import(client, other, data_root)
    ctx = ctx_of(client)
    for job in ctx.jobs.list():
        wait(client, job.job_id)
    pdir = ctx.workspace.project_dir(pid)
    run = pdir / "radiomics/runs/example"
    run.mkdir(parents=True)
    pq.write_table(
        pa.table({"item_id": [iid, "retained"], "feature": [1.0, 2.0]}), run / "features.parquet"
    )
    write_jsonl_atomic(
        pdir / "tasks/runs/example/masks.jsonl",
        [{"item_id": iid, "ref": "DATA:mask.nii.gz"}, {"item_id": "retained"}],
    )
    plan = preview(client, pid, iid)
    assert set(plan["projects"]) == {pid, other}
    res = client.post(
        f"{API}/projects/{pid}/items/{iid}/recycle",
        json={"confirmed": True, "token": plan["token"]},
        headers={"X-Reviewer": "R"},
    )
    assert res.status_code == 200, res.text
    assert iid not in ctx.index.load(other).by_id
    assert pq.read_table(run / "features.parquet").to_pylist() == [
        {"item_id": "retained", "feature": 2.0}
    ]
    assert read_jsonl(pdir / "tasks/runs/example/masks.jsonl") == [{"item_id": "retained"}]


def test_CUR16_refuses_symlinked_recycle_bin(
    client: TestClient, data_root: Path, tmp_path: Path
) -> None:
    pid, iid = setup_scan(client, data_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (data_root / "recycle_bin").symlink_to(outside, target_is_directory=True)
    assert client.get(f"{API}/projects/{pid}/items/{iid}/recycle").status_code == 422
    assert not list(outside.iterdir())


def test_CUR16_detection_skips_recycled_volumes(tmp_path: Path) -> None:
    from app.sources.formats import scan

    (tmp_path / "active.nii.gz").write_bytes(b"active")
    removed = tmp_path / "recycle_bin/entry/files"
    removed.mkdir(parents=True)
    (removed / "deleted.nii.gz").write_bytes(b"deleted")
    assert scan(tmp_path).files["nifti"] == ["active.nii.gz"]
    assert not scan(tmp_path, ["recycle_bin/entry/files/deleted.nii.gz"]).n_accepted


def test_CUR16_recovers_interrupted_transaction(client: TestClient, data_root: Path) -> None:
    pid, iid = setup_scan(client, data_root)
    ctx = ctx_of(client)
    original = (data_root / "metadata.jsonl").read_bytes()
    image = ctx.workspace.resolver(pid).resolve(ctx.index.get_item(pid, iid).image.ref)  # type: ignore[union-attr]
    plan = preview(client, pid, iid)
    response = client.post(
        f"{API}/projects/{pid}/items/{iid}/recycle",
        json={"confirmed": True, "token": plan["token"]},
        headers={"X-Reviewer": "R"},
    )
    assert response.status_code == 200, response.text
    destination = Path(response.json()["recycle_dir"])
    manifest = read_json(destination / "manifest.json")
    # Simulate a stop after files/index were written but before the commit marker.
    manifest["status"] = "prepared"
    recycle.atomic_write_json(destination / "manifest.json", manifest)
    pending = ctx.settings.workspace_root / "recycle_pending" / f"{manifest['recycle_id']}.json"
    recycle.atomic_write_json(pending, {"manifest": str(destination / "manifest.json")})
    recycle.RecycleService(ctx.workspace, ctx.index, ctx.jobs, ctx.bus).recover()
    assert image.is_file()
    assert (data_root / "metadata.jsonl").read_bytes() == original
    assert iid in ctx.index.load(pid).by_id
    assert not pending.exists()
    assert read_json(destination / "manifest.json")["status"] == "rolled_back"


def test_CUR16_moves_across_filesystems_only_after_verified_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    source, target = tmp_path / "source", tmp_path / "other/recycled"
    source.write_bytes(b"CT data" * 1000)

    def cross_device(*args: Any) -> None:
        raise OSError(errno.EXDEV, "cross device")

    monkeypatch.setattr(recycle.os, "rename", cross_device)
    recycle._move_file(source, target)
    assert target.read_bytes() == b"CT data" * 1000
    assert not source.exists()


def test_API66_refuses_active_jobs(
    client: TestClient, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    pid, iid = setup_scan(client, data_root)
    plan = preview(client, pid, iid)
    monkeypatch.setattr(
        ctx_of(client).jobs, "list", lambda *args: [SimpleNamespace(status="running")]
    )
    response = client.post(
        f"{API}/projects/{pid}/items/{iid}/recycle",
        json={"confirmed": True, "token": plan["token"]},
        headers={"X-Reviewer": "R"},
    )
    assert response.status_code == 409
    assert not (data_root / "recycle_bin").exists()


def test_CUR16_workspace_derived_dataset(tmp_path: Path, data_root: Path) -> None:
    """CUR-16 works for generated datasets registered through a source alias (SRC-16)."""
    import shutil

    from app.config import Settings
    from app.main import create_app

    derived = tmp_path / "derived"
    dataset = derived / "_datasets/converted"
    shutil.copytree(data_root, dataset)
    settings = Settings(
        workspace_root=tmp_path / "derived-workspace",
        allowed_data_roots=str(data_root),
        allowed_derived_roots=str(derived),
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as c:
        pid, iid = setup_scan(c, dataset)
        plan = preview(c, pid, iid)
        response = c.post(
            f"{API}/projects/{pid}/items/{iid}/recycle",
            json={"confirmed": True, "token": plan["token"]},
            headers={"X-Reviewer": "R"},
        )
        assert response.status_code == 200, response.text
        assert Path(response.json()["recycle_dir"]).parent == dataset / "recycle_bin"
        assert iid not in ctx_of(c).index.load(pid).by_id


def test_CUR16_refuses_dataset_escaping_symlink(
    client: TestClient, data_root: Path, tmp_path: Path
) -> None:
    pid, iid = setup_scan(client, data_root)
    original = data_root / "metadata.jsonl"
    outside = tmp_path / "outside-metadata.jsonl"
    original.rename(outside)
    original.symlink_to(outside)
    assert client.get(f"{API}/projects/{pid}/items/{iid}/recycle").status_code == 422
    assert outside.exists()
    assert not (data_root / "recycle_bin").exists()
