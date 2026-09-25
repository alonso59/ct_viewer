"""API-06 project bundles: export (PRJ-08) and import with a relink report (PRJ-09), R1."""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import make_settings
from tests.test_contract import assert_problem
from tests.test_e2e_import import import_root, sha_tree, wait_job
from tests.test_imaging import forbid_source_writes

API = "/api/v1"


def _export(c: TestClient, pid: str) -> bytes:
    r = c.post(f"{API}/projects/{pid}/bundle")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert f'filename="Bundle-me-ccRCC-{pid}.zip"' in r.headers["content-disposition"]
    return r.content


def _import(c: TestClient, data: bytes) -> Any:
    return c.post(f"{API}/projects/import-bundle", files={"bundle": ("b.zip", data)})


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, blob in entries.items():
            zf.writestr(name, blob)
    return buf.getvalue()


@pytest.fixture
def exported(
    client: TestClient, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, bytes, dict[str, str]]:
    """A project with an index, hashes, a curation event and junk that must stay out."""
    before = sha_tree(data_root)
    pid = client.post(
        f"{API}/projects", json={"name": "Bundle me / ccRCC", "packs": ["ccrcc"]}
    ).json()["project_id"]
    import_root(client, pid, data_root)
    wait_job(client, client.post(f"{API}/projects/{pid}/hash-jobs").json()["job_id"])
    forbid_source_writes(monkeypatch, data_root)
    pdir: Path = client.app.state.ctx.workspace.project_dir(pid)  # type: ignore[attr-defined]
    (pdir / "cache" / "junk.bin").write_bytes(b"x")
    (pdir / ".lock").write_bytes(b"")
    (pdir / "exports" / "stray.nii.gz").write_bytes(b"not really")
    (pdir / "exports" / ".x.json.123.tmp").write_bytes(b"{")
    (pdir / "exports" / "queue.csv").write_text("item_id\n")
    data = _export(client, pid)
    zf = zipfile.ZipFile(io.BytesIO(data))
    staging = client.app.state.ctx.workspace.staging_dir  # type: ignore[attr-defined]
    assert not list(staging.iterdir())  # the temp zip is removed once sent
    assert sha_tree(data_root) == before  # R1
    return pid, data, {n: zf.read(n).decode() for n in zf.namelist() if n.endswith(".json")}


def test_export_contents(exported: tuple[str, bytes, dict[str, str]]) -> None:
    pid, data, _ = exported
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert all(n.startswith(f"{pid}/") for n in names)
    rel = {n.split("/", 1)[1] for n in names}
    assert {
        "project.json",
        "index/items.jsonl",
        "index/hashes.json",
        "sources/imports.jsonl",
    } <= rel
    assert "exports/queue.csv" in rel
    assert not [r for r in rel if r.startswith("cache/")]
    assert ".lock" not in rel and "exports/stray.nii.gz" not in rel
    assert not [r for r in rel if r.endswith(".tmp")]
    assert not [r for r in rel if r.endswith((".nii", ".nii.gz", ".npy"))]  # never image data


def test_import_into_another_workspace_keeps_id(
    exported: tuple[str, bytes, dict[str, str]], tmp_path: Path, data_root: Path
) -> None:
    pid, data, _ = exported
    other = make_settings(tmp_path / "other", [data_root])
    with TestClient(create_app(other, inline_jobs=True)) as c:
        r = _import(c, data)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["project"]["project_id"] == body["source_project_id"] == pid
        assert body["id_changed"] is False and body["needs_relink"] is False
        [root] = body["roots"]
        assert root["root"]["alias"] == "DATA" and root["root"]["exists"]
        assert root["verify"]["matched"] == root["verify"]["sampled"] > 0
        assert body["project"]["name"] == "Bundle me / ccRCC"
        assert [p["project_id"] for p in c.get(f"{API}/projects").json()] == [pid]
        cases = c.get(f"{API}/projects/{pid}/cases?limit=2000").json()
        assert cases["total"] > 0
        item = c.get(f"{API}/projects/{pid}/items/case_00001.01.complete.-").json()
        assert item["image"]["sha256"]  # hashes travel with the bundle
        pdir = other.workspace_root / "projects" / pid
        assert (pdir / "cache").is_dir() and not list((pdir / "cache").iterdir())
        assert not (other.workspace_root / ".staging").exists() or not list(
            (other.workspace_root / ".staging").iterdir()
        )


def test_import_into_same_workspace_gets_new_id(
    client: TestClient, exported: tuple[str, bytes, dict[str, str]]
) -> None:
    pid, data, _ = exported
    body = _import(client, data).json()
    new = body["project"]["project_id"]
    assert body["id_changed"] is True and new != pid and body["source_project_id"] == pid
    assert client.get(f"{API}/projects/{new}").json()["project_id"] == new
    assert len(client.get(f"{API}/projects").json()) == 2


def test_import_with_unresolvable_root_needs_relink(
    exported: tuple[str, bytes, dict[str, str]], tmp_path: Path, data_root: Path
) -> None:
    _, data, _ = exported
    moved = tmp_path / "moved"
    shutil.copytree(data_root, moved)
    other: Settings = make_settings(tmp_path / "other", [moved])  # old root is not allowed
    with TestClient(create_app(other, inline_jobs=True)) as c:
        body = _import(c, data).json()
        assert body["needs_relink"] is True
        [root] = body["roots"]
        assert root["root"]["exists"] is False and root["verify"]["missing"] > 0
        pid = body["project"]["project_id"]
        r = c.put(f"{API}/projects/{pid}/roots/DATA", json={"path": str(moved)})
        assert r.status_code == 200 and r.json()["verify"]["mismatched"] == 0


def test_rejects_bad_bundles(
    client: TestClient, exported: tuple[str, bytes, dict[str, str]]
) -> None:
    pid, _, jsons = exported
    cfg = json.loads(jsons[f"{pid}/project.json"])
    assert_problem(_import(client, b"not a zip"), "validation")
    assert_problem(_import(client, _zip({"x/readme.txt": b""})), "validation")  # no project.json
    good = json.dumps(cfg).encode()
    assert_problem(_import(client, _zip({"a/project.json": good, "b/x": b""})), "validation")
    assert_problem(_import(client, _zip({"a/project.json": good, "a/../../x": b""})), "validation")
    assert_problem(_import(client, _zip({"/abs/project.json": good})), "validation")
    newer = json.dumps({**cfg, "format_version": 99}).encode()
    assert_problem(_import(client, _zip({"a/project.json": newer})), "format-version-unsupported")
    foreign = json.dumps({**cfg, "format": "other"}).encode()
    assert_problem(_import(client, _zip({"a/project.json": foreign})), "format-version-unsupported")
    assert len(client.get(f"{API}/projects").json()) == 1  # nothing half-imported
    assert_problem(client.post(f"{API}/projects/01JAAAAAAAAAAAAAAAAAAAAAAA/bundle"), "not-found")


def test_export_scrubs_unanonymized_dicom_rows(tmp_path: Path) -> None:
    """DCM-05, NFR-17: converter rows leave with `basic` applied; the rest stays as is."""
    from app.projects.bundle import write_bundle

    pid = "01JTESTPROJECT0000000000AB"
    folder = tmp_path / pid
    dicom = {
        "case_id": "case_00000",
        "scan_idx": "01",
        "patient_id": "MRN-4711",
        "case_identity_key": "MRN-4711",
        "patient_folder": "DOE^JANE",
        "institution": "St. Example",
        "study_date": "20240102",
        "protocol_name": "ABD CT",
        "study_uid": "1.2.3.4",
        "series_uid": "1.2.3.4.5",
        "source_kind": "dicom",
        "modality": "CT",
    }
    anon = dict(
        dicom,
        case_id="case_00001",
        patient_id="case_00001",
        anonymized="basic",
        case_identity_key="sha256:0123456789abcdef01234567",
        patient_folder="",
        institution="",
        study_date="",
        study_uid="2.25.1",
        series_uid="2.25.2",
    )
    nifti = {
        "case_id": "case_00002",
        "patient_id": "P2",
        "study_date": "20240102",
        "source_kind": "nifti",
    }
    item = {
        "item_id": "case_00000.01.complete.-",
        "case_id": "case_00000",
        "patient_id": "MRN-4711",
        "extra": {"source_kind": "dicom", "institution": "St. Example", "series_uid": "1.2.3.4.5"},
    }
    files: dict[str, str] = {
        "project.json": json.dumps({"project_id": pid}),
        "sources/01JIMPORT/metadata.jsonl": "".join(
            json.dumps(r) + "\n" for r in (dicom, anon, nifti)
        ),
        "index/items.jsonl": json.dumps(item) + "\n",
        "index/cases.jsonl": json.dumps({"case_id": "case_00000", "patient_id": "MRN-4711"})
        + "\n"
        + json.dumps({"case_id": "case_00002", "patient_id": "P2"})
        + "\n",
        "sources/identity.json": json.dumps(
            {
                "strategy": "dicom_patient_id",
                "cases": {"MRN-4711": 0},
                "scans": {"MRN-4711|1.2.3.4.5": "01"},
            }
        ),
    }
    for rel, text in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text)
    before = sha_tree(folder)

    out = tmp_path / "b.zip"
    write_bundle(folder, pid, out)

    assert sha_tree(folder) == before  # the project itself is untouched
    with zipfile.ZipFile(out) as zf:
        blob = b"".join(zf.read(n) for n in zf.namelist())
        rows = [
            json.loads(x) for x in zf.read(f"{pid}/sources/01JIMPORT/metadata.jsonl").splitlines()
        ]
        items = [json.loads(x) for x in zf.read(f"{pid}/index/items.jsonl").splitlines()]
        cases = [json.loads(x) for x in zf.read(f"{pid}/index/cases.jsonl").splitlines()]
        reg = json.loads(zf.read(f"{pid}/sources/identity.json"))
    for secret in (b"MRN-4711", b"DOE^JANE", b"St. Example", b"1.2.3.4.5"):
        assert secret not in blob
    assert rows[0]["patient_id"] == "case_00000" and rows[0]["anonymized"] == "basic"
    assert rows[0]["study_date"] == "" and rows[0]["modality"] == "CT"
    assert rows[1] == anon  # anonymized at conversion: as is
    assert rows[2] == nifti  # not DICOM-derived: as is
    assert items[0]["patient_id"] == "case_00000" and items[0]["extra"]["institution"] == ""
    assert items[0]["extra"]["series_uid"] == rows[0]["series_uid"]  # same replacement everywhere
    assert [c["patient_id"] for c in cases] == ["case_00000", "P2"]
    assert list(reg["cases"]) == [rows[0]["case_identity_key"]]
    assert all(k.startswith("sha256:") for k in reg["scans"])


def test_export_leaves_out_variable_values_and_run_source_paths(tmp_path: Path) -> None:
    """AUD-A5-02, NFR-17: `index/variables.parquet` stays home (rebuilt on open, VAR-01), the
    catalog keeps its overrides but not its profile values, run records lose the input path."""
    from app.projects.bundle import write_bundle

    pid = "01JTESTPROJECT0000000000AC"
    folder = tmp_path / pid
    source = "/data/incoming/DOE^JANE/CT"
    var = {
        "name": "patient_folder",
        "tags": ["sensitive"],
        "profile": {"n_units": 1, "top": [{"value": "DOE^JANE", "n": 1}], "examples": ["DOE^JANE"]},
    }
    files: dict[str, str] = {
        "project.json": json.dumps({"project_id": pid}),
        "index/variables.parquet": "DOE^JANE",
        "variables/catalog.json": json.dumps({"variables": [var]}),
        "tasks/runs/01JRUN/run.json": json.dumps({"task_id": "dicom.convert",
                                                   "selection": {"source": source}}),
    }  # fmt: skip
    for rel, text in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text)

    out = tmp_path / "b.zip"
    write_bundle(folder, pid, out)

    with zipfile.ZipFile(out) as zf:
        names = {n.split("/", 1)[1] for n in zf.namelist()}
        blob = b"".join(zf.read(n) for n in zf.namelist())
        cat = json.loads(zf.read(f"{pid}/variables/catalog.json"))
        run = json.loads(zf.read(f"{pid}/tasks/runs/01JRUN/run.json"))
    assert "index/variables.parquet" not in names
    assert b"DOE^JANE" not in blob
    assert cat["variables"][0]["tags"] == ["sensitive"]  # user overrides travel (VAR-11)
    assert run["task_id"] == "dicom.convert" and run["selection"]["source"] is None
