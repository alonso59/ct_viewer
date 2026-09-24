"""TST-17 plugins (PLG-*): manifest validation, Library status reasons, task ownership, pending."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.plugins.registry import PluginRegistry, StatusInputs, parse_plugin, status_of
from tests.test_api_ingest import do_import
from tests.test_contract import assert_problem
from tests.test_format_v2 import derived_settings
from tools.make_fixtures import DATASET

API = "/api/v1"
REPO = Path(__file__).resolve().parents[2]
SHIPPED = {"dicom", "analyzers", "radiomics", "dashboard", "curation", "nnunet", "voi"}


def write(root: Path, pid: str, **fields: object) -> Path:
    (root / pid).mkdir(parents=True, exist_ok=True)
    p = root / pid / "plugin.json"
    p.write_text(json.dumps({"plugin": 1, "id": pid, "version": "1.0.0", "title": pid, **fields}))
    return p


def test_every_shipped_manifest_is_valid() -> None:
    reg = PluginRegistry()
    reg.load(REPO / "plugins")
    assert reg.invalid == []
    assert set(reg.plugins) >= SHIPPED
    assert "threshold" in reg.plugins and reg.plugins["threshold"].hidden  # CI only
    owners = reg.task_owner()
    assert owners["dicom.convert"] == "dicom" and owners["radiomics.pyradiomics"] == "radiomics"
    assert owners["analyzer.phase"] == "analyzers"


def test_manifest_validation_errors(tmp_path: Path) -> None:
    write(tmp_path, "typo", typo=1)
    write(tmp_path, "badcap", requires={"capabilities": ["gpu-magic"]})
    write(tmp_path, "orphan", requires={"plugins": ["missing"]})
    write(tmp_path, "ok")
    (tmp_path / "wrong").mkdir()
    (tmp_path / "wrong" / "plugin.json").write_text(
        json.dumps({"plugin": 1, "id": "other", "version": "1", "title": "x"})
    )
    (tmp_path / "junk").mkdir()
    (tmp_path / "junk" / "plugin.json").write_text("{nope")
    reg = PluginRegistry()
    reg.load(tmp_path)
    assert set(reg.plugins) == {"ok"}
    errors = {Path(i.path).parent.name or i.path: i.error for i in reg.invalid}
    assert "typo" in errors["typo"]
    assert "capabilities" in errors["badcap"]
    assert "must match its folder" in errors["wrong"]
    assert "not JSON" in errors["junk"]
    assert any("requires unknown plugins" in i.error for i in reg.invalid)
    with pytest.raises(ValueError, match="id"):
        parse_plugin(write(tmp_path, "Bad_Id"))


def test_status_reasons(tmp_path: Path) -> None:
    def m(**kw: object):  # type: ignore[no-untyped-def]
        return parse_plugin(write(tmp_path, "p", **kw))

    ok = StatusInputs(derived_roots=True, runner_missing=lambda _t: False, has_segmentation=True)
    assert status_of(m(), ok).status == "ready"
    pend = status_of(m(pending=True), ok)
    assert pend.status == "pending" and pend.reason
    no_root = StatusInputs(derived_roots=False, runner_missing=lambda _t: False)
    s = status_of(m(requires={"capabilities": ["derived_root"]}), no_root)
    assert s.status == "needs_derived_root" and "ALLOWED_DERIVED_ROOTS" in (s.reason or "")
    assert s.actions == ["configure:ALLOWED_DERIVED_ROOTS"]
    runner = StatusInputs(derived_roots=True, runner_missing=lambda _t: True)
    s = status_of(m(contributes={"tasks": ["a.b"]}, requires={"capabilities": ["runner"]}), runner)
    assert s.status == "needs_runner" and "rw-runner" in (s.reason or "")
    noseg = StatusInputs(True, lambda _t: False, has_segmentation=False)
    assert status_of(m(requires={"capabilities": ["segmentation"]}), noseg).status == (
        "needs_segmentation"
    )
    # Outside a project the segmentation requirement cannot be judged: ready.
    assert status_of(m(requires={"capabilities": ["segmentation"]}), no_root).status == "ready"


def test_library_api(tmp_path: Path, fixtures_copy: Path) -> None:
    s = derived_settings(tmp_path, fixtures_copy / DATASET, None)  # no derived root
    with TestClient(create_app(s, inline_jobs=True)) as c:
        body = c.get(f"{API}/plugins").json()
        rows = {p["manifest"]["id"]: p for p in body["plugins"]}
        assert set(rows) == SHIPPED  # hidden CI plugin not listed (PLG-05)
        assert rows["dicom"]["status"] == "needs_derived_root"
        assert rows["nnunet"]["status"] == "pending" and rows["voi"]["status"] == "pending"
        assert rows["curation"]["status"] == "ready"
        assert rows["radiomics"]["manifest"]["contributes"]["tasks"] == ["radiomics.pyradiomics"]
        assert body["invalid"] == []
        pid = str(c.post(f"{API}/projects", json={"name": "p"}).json()["project_id"])
        empty = c.get(f"{API}/plugins/radiomics", params={"project": pid}).json()
        assert empty["status"] == "needs_segmentation"
        do_import(c, pid, fixtures_copy / DATASET)
        assert c.get(f"{API}/plugins/radiomics", params={"project": pid}).json()["status"] == (
            "ready"
        )
        assert_problem(c.get(f"{API}/plugins/nope"), "not-found")
        assert_problem(c.get(f"{API}/plugins", params={"project": "01NOPE"}), "not-found")
        # TSK-01: every loaded task names its plugin
        tasks = c.get(f"{API}/tasks").json()["tasks"]
        assert all(t["plugin"] for t in tasks)


def test_plugins_root_accepts_first_party_tasks_only(tmp_path: Path) -> None:
    root = tmp_path / "plugins_root"
    root.mkdir()
    (root / "threshold").symlink_to(REPO / "plugins" / "threshold")
    raw = json.loads((REPO / "plugins" / "threshold" / "task.json").read_text())
    (root / "foreign").mkdir()
    (root / "foreign" / "task.json").write_text(json.dumps({**raw, "id": "third.party"}))
    s = derived_settings(tmp_path, tmp_path, None)
    s.plugins_root = root
    with TestClient(create_app(s, inline_jobs=True)) as c:
        body = c.get(f"{API}/tasks").json()
        ids = {t["manifest"]["id"]: t for t in body["tasks"]}
        assert ids["segment.threshold"]["plugin"] == "threshold"
        assert "third.party" not in ids
        errors = {Path(i["path"]).parent.name: i["error"] for i in body["invalid"]}
        assert "first-party" in errors["foreign"]
