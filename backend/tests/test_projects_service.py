"""Workspace service unit tests (PRJ-01..06, 10, 11; BE-05, BE-07; TST-01)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.core.errors import FormatVersionUnsupported, NotFound, PathOutsideRoot, ValidationProblem
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import new_ulid
from app.core.locks import ProjectLocks
from app.core.paths import PathGuard
from app.projects import migrations
from app.projects.models import FORMAT_VERSION, PathRoot, ProjectPatch
from app.projects.service import SUBDIRS, Workspace


@pytest.fixture
def ws(settings: Settings) -> Workspace:
    w = Workspace(settings, PathGuard(settings.allowed_roots), ProjectLocks())
    w.open()
    return w


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_open_creates_layout(ws: Workspace) -> None:
    assert (ws.root / "projects" / ".archive").is_dir()
    doc = read_json(ws.root / "workspace.json")
    assert doc == {"format": "radiology-workbench-workspace", "format_version": 1, "projects": []}
    ws.open()  # idempotent
    assert read_json(ws.root / "workspace.json")["projects"] == []


def test_create_layout_and_registry(ws: Workspace) -> None:
    cfg = run(ws.create("Demo", "desc"))
    folder = ws.root / "projects" / cfg.project_id
    for sub in SUBDIRS:
        assert (folder / sub).is_dir()
    raw = read_json(folder / "project.json")
    assert raw["format"] == "radiology-workbench-project"
    assert raw["format_version"] == FORMAT_VERSION
    assert raw["name"] == "Demo" and raw["description"] == "desc"
    # PRJ-14: neutral (no labels, raw phases, no pack, CT default)
    assert raw["label_map"] == [] and raw["packs"] == [] and raw["phase_vocabulary"] == []
    assert raw["default_modality"] == "CT" and raw["view_token"] is None
    reg = read_json(ws.root / "workspace.json")["projects"]
    assert reg == [
        {
            "project_id": cfg.project_id,
            "name": "Demo",
            "created_at": cfg.created_at,
            "last_opened_at": None,
            "archived": False,
        }
    ]
    assert ws.project_dir(cfg.project_id) == folder


def test_registry_survives_reload(ws: Workspace, settings: Settings) -> None:
    ids = {run(ws.create(f"P{i}")).project_id for i in range(3)}
    fresh = Workspace(settings, ws.guard, ProjectLocks())
    fresh.open()
    assert {s.project_id for s in fresh.list()} == ids
    assert fresh.get(next(iter(ids))).project_id in ids


def test_list_summary(ws: Workspace) -> None:
    cfg = run(ws.create("Demo"))
    cases = ws.project_dir(cfg.project_id) / "index" / "cases.jsonl"
    cases.write_text(
        '{"case_id":"case_00001"}\n\n{"case_id":"case_00002"}\n{"case_id":"x","n_items":0}\n'
    )
    [row] = ws.list()
    assert row.n_cases == 2 and row.n_cases_excluded == 1  # AUD-A2-08: all-excluded not counted
    assert row.curation_progress == 0.0
    assert row.share_url == f"{ws.settings.base_url}/p/{cfg.project_id}"
    assert ws.list(archived=True) == []


def test_unknown_and_invalid_ids(ws: Workspace) -> None:
    for pid in ("nope", "../etc", new_ulid()):
        with pytest.raises(NotFound):
            ws.project_dir(pid)
        with pytest.raises(NotFound):
            ws.get(pid)


def test_update_patch_and_rename(ws: Workspace) -> None:
    cfg = run(ws.create("Old"))
    new = run(ws.update(cfg.project_id, ProjectPatch(name="New", description="d")))
    assert new.name == "New" and new.description == "d"
    assert new.label_map == cfg.label_map
    assert read_json(ws.project_dir(cfg.project_id) / "project.json")["name"] == "New"
    assert (ws.project_dir(cfg.project_id) / "project.json.bak").exists()
    assert ws.list()[0].name == "New"
    same = run(ws.update(cfg.project_id, ProjectPatch()))
    assert same == new


def test_update_rejects_unknown_phase(ws: Workspace) -> None:
    cfg = run(ws.create("P", packs=["ccrcc"]))
    with pytest.raises(ValidationProblem):
        run(ws.update(cfg.project_id, ProjectPatch(phase_priority=["NP", "XX"])))


def test_lru_cache_and_invalidation(ws: Workspace) -> None:
    cfg = run(ws.create("P"))
    pid = cfg.project_id
    assert ws.get(pid) is ws.get(pid)
    path = ws.project_dir(pid) / "project.json"
    raw = read_json(path)
    atomic_write_json(path, {**raw, "name": "External"})
    assert ws.get(pid).name == "P"  # cached
    ws.invalidate(pid)
    assert ws.get(pid).name == "External"
    updated = run(ws.update(pid, ProjectPatch(name="Mine")))
    assert ws.get(pid) is updated
    for i in range(ws.settings.project_cache_max + 2):
        ws.get(run(ws.create(f"X{i}")).project_id)
    assert len(ws._cache) == ws.settings.project_cache_max


def test_archive_and_unarchive(ws: Workspace) -> None:
    cfg = run(ws.create("P"))
    pid = cfg.project_id
    folder = ws.project_dir(pid)
    (folder / "cache" / "meshes").mkdir()
    (folder / "cache" / "meshes" / "m.glb").write_bytes(b"x")
    (folder / "cache" / "a.nii").write_bytes(b"x")
    (folder / "curation" / "events.jsonl").write_text("{}\n")
    run(ws.archive(pid))
    dest = ws.root / "projects" / ".archive" / pid
    assert not folder.exists() and dest.is_dir()
    assert list((dest / "cache").iterdir()) == []
    assert (dest / "curation" / "events.jsonl").exists()
    assert ws.list() == [] and [s.project_id for s in ws.list(archived=True)] == [pid]
    with pytest.raises(NotFound):
        ws.get(pid)
    with pytest.raises(NotFound):
        run(ws.archive(pid))
    restored = run(ws.unarchive(pid))
    assert restored.project_id == pid and folder.is_dir()
    assert read_json(ws.root / "workspace.json")["projects"][0]["archived"] is False
    with pytest.raises(NotFound):
        run(ws.unarchive(pid))


def test_touch_opened(ws: Workspace) -> None:
    pid = run(ws.create("P")).project_id
    assert ws.list()[0].last_opened_at is None
    run(ws.touch_opened(pid))
    assert ws.list()[0].last_opened_at is not None


def test_newer_format_version_rejected(ws: Workspace) -> None:
    pid = run(ws.create("P")).project_id
    path = ws.project_dir(pid) / "project.json"
    atomic_write_json(path, {**read_json(path), "format_version": FORMAT_VERSION + 1})
    ws.invalidate(pid)
    with pytest.raises(FormatVersionUnsupported):
        ws.get(pid)


def test_wrong_format_rejected(ws: Workspace) -> None:
    pid = run(ws.create("P")).project_id
    path = ws.project_dir(pid) / "project.json"
    atomic_write_json(path, {**read_json(path), "format": "something-else"})
    ws.invalidate(pid)
    with pytest.raises(FormatVersionUnsupported):
        ws.get(pid)


def test_missing_migration_rejected(ws: Workspace) -> None:
    pid = run(ws.create("P")).project_id
    path = ws.project_dir(pid) / "project.json"
    atomic_write_json(path, {**read_json(path), "format_version": 0})
    ws.invalidate(pid)
    with pytest.raises(FormatVersionUnsupported):
        ws.get(pid)


def test_migration_runs_with_backup(ws: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    def v0_to_v1(raw: dict[str, Any]) -> dict[str, Any]:
        raw["description"] = raw.pop("notes")
        return raw

    monkeypatch.setitem(migrations.MIGRATIONS, 0, v0_to_v1)
    pid = run(ws.create("P")).project_id
    path = ws.project_dir(pid) / "project.json"
    raw = read_json(path)
    del raw["description"]
    old = {**raw, "format_version": 0, "notes": "legacy"}
    atomic_write_json(path, old)
    ws.invalidate(pid)
    cfg = ws.get(pid)
    assert cfg.description == "legacy" and cfg.format_version == FORMAT_VERSION
    assert read_json(path.with_name("project.json.v0.bak")) == old
    on_disk = read_json(path)
    assert on_disk["format_version"] == FORMAT_VERSION and "notes" not in on_disk


def test_set_root_and_resolver(ws: Workspace, data_root: Path) -> None:
    pid = run(ws.create("P")).project_id
    cfg = run(ws.set_root(pid, PathRoot(alias="DATA", path=str(data_root))))
    assert [(r.alias, r.path) for r in cfg.path_roots] == [("DATA", str(data_root))]
    res = ws.resolver(pid)
    assert res.resolve("DATA:metadata.jsonl").name == "metadata.jsonl"
    cfg = run(ws.set_root(pid, PathRoot(alias="DATA", path=str(data_root / "nifti"))))
    assert len(cfg.path_roots) == 1 and cfg.path_roots[0].path.endswith("nifti")
    assert ws.roots(pid)[0].exists is True


def test_set_root_rejections(ws: Workspace, data_root: Path, fixtures_copy: Path) -> None:
    pid = run(ws.create("P")).project_id
    with pytest.raises(ValidationProblem):
        run(ws.set_root(pid, PathRoot(alias="DATA", path="relative/path")))
    with pytest.raises(ValidationProblem):
        run(ws.set_root(pid, PathRoot(alias="DATA", path=str(data_root / "missing"))))
    with pytest.raises(ValidationProblem):
        run(ws.set_root(pid, PathRoot(alias="DATA", path=str(data_root / "metadata.jsonl"))))
    with pytest.raises(PathOutsideRoot):
        run(ws.set_root(pid, PathRoot(alias="DATA", path=str(fixtures_copy / "outside"))))
    with pytest.raises(ValidationProblem):
        PathRoot(alias="bad alias", path=str(data_root))
    assert ws.get(pid).path_roots == []
