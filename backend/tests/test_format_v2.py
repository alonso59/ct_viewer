"""P7b Wave 1 contracts: format_version 2 (PRJ-11), derived roots (PRJ-13, OPS-11/12, BE-15),
segmentation sets (ADR-0015, API-24/27), problem `actions[]` (SRC-11)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from tests.test_api_ingest import ctx_of, do_import
from tests.test_contract import assert_problem
from tools.make_fixtures import DATASET

API = "/api/v1"
ITEM = "case_00001.01.complete.-"


def derived_settings(tmp_path: Path, data: Path, derived: Path | None) -> Settings:
    return Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(data.resolve()),
        allowed_derived_roots=str(derived.resolve()) if derived else "",
        job_workers=2,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def derived_dir(tmp_path: Path) -> Path:
    d = tmp_path / "derived"
    d.mkdir()
    return d


@pytest.fixture
def dclient(tmp_path: Path, fixtures_copy: Path, derived_dir: Path) -> Iterator[TestClient]:
    s = derived_settings(tmp_path, fixtures_copy / DATASET, derived_dir)
    with TestClient(create_app(s, inline_jobs=True)) as c:
        yield c


def new_project(c: TestClient, name: str = "p") -> str:
    r = c.post(f"{API}/projects", json={"name": name})
    assert r.status_code == 201, r.text
    return str(r.json()["project_id"])


# -- config (OPS-11/12, BE-15) ------------------------------------------------------------


def test_derived_roots_must_be_absolute_and_not_overlap(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="absolute"):
        Settings(_env_file=None, allowed_derived_roots="rel")  # type: ignore[call-arg]
    data = tmp_path / "data"
    for bad in (data, data / "derived", tmp_path):
        with pytest.raises(ValidationError, match="roots-overlap"):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                allowed_data_roots=str(data),
                allowed_derived_roots=str(bad),
            )
    ok = Settings(
        _env_file=None,  # type: ignore[call-arg]
        allowed_data_roots=str(data),
        allowed_derived_roots=str(tmp_path / "out"),
    )
    assert ok.derived_roots == [(tmp_path / "out").resolve()]


# -- migration 1 → 2 (PRJ-11) -------------------------------------------------------------


def test_v1_project_and_index_migrate(dclient: TestClient, data_root: Path) -> None:
    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    ws = ctx_of(dclient).workspace
    folder = ws.project_dir(pid)
    # Rewrite project.json and items.jsonl as format_version 1 wrote them.
    raw = json.loads((folder / "project.json").read_text())
    for k in ("segmentations", "default_seg", "annotation_sources"):
        raw.pop(k)
    raw["format_version"] = 1
    raw["path_roots"] = [{"alias": r["alias"], "path": r["path"]} for r in raw["path_roots"]]
    (folder / "project.json").write_text(json.dumps(raw))
    items_path = folder / "index" / "items.jsonl"
    rows = [json.loads(line) for line in items_path.read_text().splitlines()]
    for row in rows:
        masks = row.pop("masks")
        row["mask"] = masks.get("imported")
    items_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    ws.invalidate(pid)
    ctx_of(dclient).index.invalidate(pid)

    body = dclient.get(f"{API}/projects/{pid}").json()
    assert body["format_version"] == 2
    assert body["path_roots"][0]["role"] == "source"
    assert body["default_seg"] == "imported" and body["annotation_sources"] == {}
    assert [s["seg_id"] for s in body["segmentations"]] == ["imported"]
    assert body["segmentations"][0]["label_mapping"] == {"1": 1, "2": 2, "3": 3}
    assert (folder / "project.json.v1.bak").is_file()
    item = dclient.get(f"{API}/projects/{pid}/items/{ITEM}").json()
    assert item["masks"]["imported"]["ref"] == "DATA:seg/01_case_00001.nii.gz"
    assert item["mask"] == item["masks"]["imported"]  # deprecated alias (ADR-0015 §6)


# -- derived root (PRJ-13) ----------------------------------------------------------------


def test_derived_root_registration(dclient: TestClient, derived_dir: Path, data_root: Path) -> None:
    pid = new_project(dclient)
    url = f"{API}/projects/{pid}/roots/DERIVED"
    r = dclient.put(url, json={"path": str(data_root), "role": "derived"})
    assert_problem(r, "path-outside-root")
    assert "ALLOWED_DERIVED_ROOTS" in r.json()["detail"]
    r = dclient.put(url, json={"path": str(derived_dir), "role": "derived"})
    assert r.status_code == 200, r.text
    assert r.json()["root"]["role"] == "derived"
    # Relinking keeps the role; a second derived alias is refused (one per project).
    assert dclient.put(url, json={"path": str(derived_dir)}).json()["root"]["role"] == "derived"
    other = dclient.put(
        f"{API}/projects/{pid}/roots/OUT2", json={"path": str(derived_dir), "role": "derived"}
    )
    assert_problem(other, "validation")
    # A source root inside ALLOWED_DERIVED_ROOTS is refused by the data guard.
    assert_problem(
        dclient.put(f"{API}/projects/{pid}/roots/DATA", json={"path": str(derived_dir)}),
        "path-outside-root",
    )
    listing = dclient.get(f"{API}/fs/list", params={"role": "derived"}).json()
    assert [e["path"] for e in listing["entries"]] == [str(derived_dir.resolve())]


def test_no_derived_roots_configured(client: TestClient, tmp_path: Path) -> None:
    pid = new_project(client)
    r = client.put(
        f"{API}/projects/{pid}/roots/DERIVED", json={"path": str(tmp_path), "role": "derived"}
    )
    assert_problem(r, "derived-root-required")
    assert r.json()["actions"] == ["configure:ALLOWED_DERIVED_ROOTS"]
    r = client.get(f"{API}/fs/list", params={"role": "derived"})
    assert_problem(r, "derived-root-required")


def test_project_roots_must_not_overlap(tmp_path: Path) -> None:
    """Dev mode (unrestricted data roots): a derived folder inside a source root is refused."""
    data = tmp_path / "data"
    (data / "out").mkdir(parents=True)
    s = Settings(
        workspace_root=tmp_path / "ws",
        allowed_derived_roots=str(data / "out"),
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(s, inline_jobs=True)) as c:
        pid = new_project(c)
        assert (
            c.put(f"{API}/projects/{pid}/roots/DATA", json={"path": str(data)}).status_code == 200
        )
        r = c.put(
            f"{API}/projects/{pid}/roots/DERIVED",
            json={"path": str(data / "out"), "role": "derived"},
        )
        assert_problem(r, "roots-overlap")


# -- segmentation sets (API-24/27) --------------------------------------------------------


def test_segmentations_endpoints_and_default(dclient: TestClient, data_root: Path) -> None:
    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    sets = dclient.get(f"{API}/projects/{pid}/segmentations").json()
    assert [(s["seg_id"], s["is_default"]) for s in sets] == [("imported", True)]
    assert sets[0]["n_items"] > 0
    r = dclient.patch(
        f"{API}/projects/{pid}/segmentations/imported",
        json={"name": "Ground truth", "label_mapping": {"1": 1, "2": 2}},
    )
    assert r.status_code == 200 and r.json()["name"] == "Ground truth"
    assert_problem(
        dclient.patch(
            f"{API}/projects/{pid}/segmentations/imported", json={"label_mapping": {"1": 99}}
        ),
        "validation",
    )
    assert_problem(dclient.patch(f"{API}/projects/{pid}/segmentations/nope", json={}), "not-found")
    assert_problem(dclient.patch(f"{API}/projects/{pid}", json={"default_seg": "x"}), "validation")
    # API-24: `?seg=` picks the set; an unknown set is 404.
    ok = dclient.get(f"{API}/projects/{pid}/items/{ITEM}/mask", params={"seg": "imported"})
    assert (
        ok.status_code == 200
        and ok.content == dclient.get(f"{API}/projects/{pid}/items/{ITEM}/mask").content
    )
    assert_problem(
        dclient.get(f"{API}/projects/{pid}/items/{ITEM}/mask", params={"seg": "other"}),
        "not-found",
    )


def test_problem_actions_in_body(client: TestClient) -> None:
    from app.core.errors import problem_body

    body: dict[str, Any] = problem_body("unsupported-format", "x", "/i", None, ["import_as:a"])
    assert body["status"] == 415 and body["actions"] == ["import_as:a"]
    assert "actions" not in problem_body("validation", "x", "/i")


def test_bundle_excludes_derived_ledger_volumes(tmp_path: Path) -> None:
    """Bundles never carry derived volumes (ADR-0014 §7): the ledger holds refs only."""
    from app.projects.bundle import write_bundle

    folder = tmp_path / "01JAAAAAAAAAAAAAAAAAAAAAAA"
    (folder / "derived").mkdir(parents=True)
    (folder / "derived" / "runs.jsonl").write_text('{"ref": "DERIVED:x.nii.gz"}\n')
    (folder / "project.json").write_text("{}")
    (folder / "tasks" / "runs" / "r").mkdir(parents=True)
    (folder / "tasks" / "runs" / "r" / "m.nii.gz").write_bytes(b"x")
    out = tmp_path / "b.zip"
    write_bundle(folder, folder.name, out)
    import zipfile

    names = zipfile.ZipFile(out).namelist()
    assert any(n.endswith("derived/runs.jsonl") for n in names)
    assert not any(n.endswith(".nii.gz") for n in names)
    shutil.rmtree(folder)
