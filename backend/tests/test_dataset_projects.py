"""PRJ-19 / API-67: portable dataset-local projects, managed outputs and legacy compatibility."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.core.paths import PathOutsideRoot
from app.main import create_app
from tests.test_api_ingest import ctx_of, do_import, wait


def test_create_import_archive_and_restore(client: TestClient, data_root: Path) -> None:
    res = client.post("/api/v1/projects", json={"name": "Local", "dataset_root": str(data_root)})
    assert res.status_code == 201, res.text
    project = res.json()
    pid = project["project_id"]
    ctx = ctx_of(client)
    folder = data_root / ".workbench/projects" / pid
    assert ctx.workspace.project_dir(pid) == folder
    assert (folder / "project.json").is_file()
    assert not (ctx.workspace.projects_dir / pid).exists()
    assert ctx.workspace.derived_root(pid).path == str(data_root / "derived")
    do_import(client, pid, data_root)
    for job in ctx.jobs.list():
        wait(client, job.job_id)
    assert ctx.index.load(pid).items
    res = client.post(f"/api/v1/projects/{pid}/archive")
    assert res.status_code == 200, res.text
    assert (data_root / ".workbench/.archive" / pid / "project.json").exists()
    res = client.post(f"/api/v1/projects/{pid}/unarchive")
    assert res.status_code == 200, res.text
    assert folder.exists()
    assert "/derived/" in (data_root / ".gitignore").read_text()


def test_multiple_projects_and_open_after_move(tmp_path: Path, data_root: Path) -> None:
    allowed = data_root.parent
    settings = Settings(
        workspace_root=tmp_path / "first/workspace", allowed_data_roots=str(allowed), _env_file=None
    )  # type: ignore[call-arg]
    ids = []
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        for name in ["one", "two"]:
            res = client.post(
                "/api/v1/projects", json={"name": name, "dataset_root": str(data_root)}
            )
            assert res.status_code == 201, res.text
            ids.append(res.json()["project_id"])
        do_import(client, ids[0], data_root)
    moved = data_root.with_name("MovedDataset")
    shutil.move(data_root, moved)
    settings = settings.model_copy(update={"workspace_root": tmp_path / "second/workspace"})
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        res = client.post("/api/v1/projects/open", json={"dataset_root": str(moved)})
        assert res.status_code == 200, res.text
        assert {p["project_id"] for p in res.json()} == set(ids)
        assert all(p["dataset_root"] == str(moved) for p in res.json())
        assert all(r["path"].startswith(str(moved)) for p in res.json() for r in p["path_roots"])
        ctx = ctx_of(client)
        image = next(i.image for i in ctx.index.load(ids[0]).items if i.image)
        assert image and ctx.workspace.resolver(ids[0]).resolve(image.ref).is_file()


def test_guard_managed_outputs_and_discovery(client: TestClient, data_root: Path) -> None:
    import pytest

    from app.sources.formats import scan

    pid = client.post(
        "/api/v1/projects", json={"name": "Local", "dataset_root": str(data_root)}
    ).json()["project_id"]
    resolver = ctx_of(client).workspace.resolver(pid)
    output = data_root / "derived/output.nii.gz"
    output.write_bytes(b"output")
    assert resolver.resolve("DERIVED:output.nii.gz") == output
    with pytest.raises(PathOutsideRoot):
        resolver.resolve("DATA:derived/output.nii.gz")
    assert "derived/output.nii.gz" not in scan(data_root).files["nifti"]
    assert (
        client.put(
            f"/api/v1/projects/{pid}/roots/OTHER",
            json={"path": str(data_root / "derived"), "role": "source"},
        ).status_code
        == 422
    )


def test_refuse_symlinks_and_collision(client: TestClient, data_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (data_root / ".workbench").symlink_to(outside, target_is_directory=True)
    res = client.post("/api/v1/projects", json={"name": "unsafe", "dataset_root": str(data_root)})
    assert res.status_code == 422, res.text
    assert not list(outside.iterdir())


def test_new_empty_dataset_and_legacy(client: TestClient, data_root: Path) -> None:
    root = data_root / "NewDataset"
    res = client.post("/api/v1/projects", json={"name": "New", "dataset_root": str(root)})
    assert res.status_code == 201, res.text
    assert (root / "derived").is_dir()
    res = client.post("/api/v1/projects", json={"name": "Legacy API"})
    assert res.status_code == 201, res.text
    pid = res.json()["project_id"]
    assert ctx_of(client).workspace.project_dir(pid) == ctx_of(client).workspace.projects_dir / pid


def test_config_home_browsing_with_explicit_managed_fallback(tmp_path: Path) -> None:
    """OPS-15 permits only the explicitly managed global fallback, never arbitrary overlap."""
    import pytest
    from pydantic import ValidationError

    state = tmp_path / ".local/share/workbench"
    cfg = Settings(
        workspace_root=state / "workspace",
        allowed_data_roots=str(tmp_path),
        allowed_derived_roots=str(state / "derived"),
        managed_derived_root=state / "derived",
        _env_file=None,
    )  # type: ignore[call-arg]
    assert cfg.derived_roots == [state / "derived"]
    with pytest.raises(ValidationError):
        Settings(
            workspace_root=state / "workspace",
            allowed_data_roots=str(tmp_path),
            allowed_derived_roots=str(tmp_path / "arbitrary"),
            _env_file=None,
        )  # type: ignore[call-arg]
