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
from tests.test_api_ingest import ctx_of, do_import, wait
from tests.test_contract import assert_problem
from tests.test_projects_api import patch_project
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
    r = c.post(f"{API}/projects", json={"name": name, "packs": ["ccrcc"]})
    assert r.status_code == 201, r.text
    return str(r.json()["project_id"])


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
    assert body["format_version"] == 3
    assert body["path_roots"][0]["role"] == "source"
    assert body["default_seg"] == "imported" and body["annotation_sources"] == {}
    assert [s["seg_id"] for s in body["segmentations"]] == ["imported"]
    assert body["segmentations"][0]["label_mapping"] == {"1": 1, "2": 2, "3": 3}
    assert (folder / "project.json.v1.bak").is_file()
    item = dclient.get(f"{API}/projects/{pid}/items/{ITEM}").json()
    assert item["masks"]["imported"]["ref"] == "DATA:seg/01_case_00001.nii.gz"
    assert item["mask"] == item["masks"]["imported"]  # deprecated alias (ADR-0015)


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
    listing = dclient.post(f"{API}/fs/list", json={"role": "derived"}).json()
    assert [e["path"] for e in listing["entries"]] == [str(derived_dir.resolve())]


def test_no_derived_roots_configured(client: TestClient, tmp_path: Path) -> None:
    pid = new_project(client)
    r = client.put(
        f"{API}/projects/{pid}/roots/DERIVED", json={"path": str(tmp_path), "role": "derived"}
    )
    assert_problem(r, "derived-root-required")
    assert r.json()["actions"] == ["configure:ALLOWED_DERIVED_ROOTS"]
    r = client.post(f"{API}/fs/list", json={"role": "derived"})
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
    assert_problem(patch_project(dclient, pid, {"default_seg": "x"}), "validation")
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
    assert dclient.delete(f"{API}/projects/{pid}/segmentations/imported").status_code == 204
    assert dclient.get(f"{API}/projects/{pid}/segmentations").json() == []
    assert_problem(dclient.get(f"{API}/projects/{pid}/items/{ITEM}/mask"), "not-found")
    assert dclient.post(f"{API}/projects/{pid}/segmentations/imported/restore").status_code == 200


def test_import_remove_and_restore_segmentation_set(dclient: TestClient, data_root: Path) -> None:
    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    r = dclient.post(
        f"{API}/projects/{pid}/segmentations/imports",
        json={
            "seg_id": "reviewed",
            "name": "Reviewed masks",
            "root": str(data_root),
            "template": "seg/{scan_idx}_{case_id}.nii.gz",
            "mode": "combined",
        },
    )
    assert r.status_code == 202, r.text
    assert r.json()["matched"] > 0
    assert wait(dclient, r.json()["job_id"]).status == "succeeded"

    sets = {s["seg_id"]: s for s in dclient.get(f"{API}/projects/{pid}/segmentations").json()}
    assert sets["reviewed"]["kind"] == "manual"
    assert sets["reviewed"]["artifact_id"] == r.json()["import_id"]
    assert sets["reviewed"]["n_items"] > 0
    item = dclient.get(f"{API}/projects/{pid}/items/{ITEM}").json()
    assert item["masks"]["reviewed"]["ref"] == "DATA:seg/01_case_00001.nii.gz"

    removed = dclient.delete(f"{API}/projects/{pid}/segmentations/reviewed")
    assert removed.status_code == 204
    assert "reviewed" not in {
        s["seg_id"] for s in dclient.get(f"{API}/projects/{pid}/segmentations").json()
    }
    inactive = dclient.get(f"{API}/projects/{pid}/segmentations", params={"removed": True}).json()
    assert [s["seg_id"] for s in inactive] == ["reviewed"]
    assert_problem(
        dclient.get(f"{API}/projects/{pid}/items/{ITEM}/mask", params={"seg": "reviewed"}),
        "not-found",
    )

    reindexed = dclient.post(f"{API}/projects/{pid}/segmentations/reindex")
    assert reindexed.status_code == 202, reindexed.text
    assert wait(dclient, reindexed.json()["job_id"]).status == "succeeded"
    assert "reviewed" not in dclient.get(f"{API}/projects/{pid}/items/{ITEM}").json()["masks"]

    restored = dclient.post(f"{API}/projects/{pid}/segmentations/reviewed/restore")
    assert restored.status_code == 200 and restored.json()["active"] is True
    assert (
        dclient.get(
            f"{API}/projects/{pid}/items/{ITEM}/mask", params={"seg": "reviewed"}
        ).status_code
        == 200
    )

    folder = ctx_of(dclient).workspace.project_dir(pid) / "segmentations/imports"
    original_manifest = folder / r.json()["import_id"] / "masks.jsonl"
    original_bytes = original_manifest.read_bytes()
    mask_bytes = (data_root / "seg/01_case_00001.nii.gz").read_bytes()
    assert dclient.delete(f"{API}/projects/{pid}/segmentations/reviewed").status_code == 204
    reimported = dclient.post(
        f"{API}/projects/{pid}/segmentations/imports",
        json={
            "seg_id": "reviewed",
            "root": str(data_root),
            "template": "seg/{scan_idx}_{case_id}.nii.gz",
        },
    )
    assert reimported.status_code == 202, reimported.text
    assert wait(dclient, reimported.json()["job_id"]).status == "succeeded"
    assert reimported.json()["import_id"] != r.json()["import_id"]
    sets = dclient.get(f"{API}/projects/{pid}/segmentations").json()
    assert len([s for s in sets if s["seg_id"] == "reviewed"]) == 1
    assert original_manifest.read_bytes() == original_bytes
    assert (data_root / "seg/01_case_00001.nii.gz").read_bytes() == mask_bytes


def test_manual_segmentation_rejects_an_image_lost_before_probing(
    dclient: TestClient, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SRC-20 / R1: a successful mask read alone cannot certify matching image geometry."""
    from app.ingest import segmentation_imports

    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    original = segmentation_imports.probe_batch

    def external_removal(probes):
        for probe in probes:
            Path(probe.image.path).unlink()
        return original(probes)

    monkeypatch.setattr(segmentation_imports, "probe_batch", external_removal)
    started = dclient.post(
        f"{API}/projects/{pid}/segmentations/imports",
        json={
            "seg_id": "reviewed",
            "root": str(data_root / "seg/01_case_00001.nii.gz"),
            "item_id": ITEM,
        },
    )
    assert started.status_code == 202, started.text
    assert wait(dclient, started.json()["job_id"]).status == "failed"
    assert not any(
        s["seg_id"] == "reviewed" for s in dclient.get(f"{API}/projects/{pid}/segmentations").json()
    )


def test_catalog_removal_and_reimport_preserve_mask_bytes_values_and_mapping(
    dclient: TestClient, data_root: Path
) -> None:
    """PRJ-07/15: label metadata edits preserve segmentation identities and source masks."""
    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    before = dclient.get(f"{API}/projects/{pid}").json()
    mask = (data_root / "seg/01_case_00001.nii.gz").read_bytes()
    sets = dclient.get(f"{API}/projects/{pid}/segmentations").json()
    changed = patch_project(dclient, pid, {"label_map": before["label_map"][1:]})
    assert changed.status_code == 200, changed.text
    assert len(changed.json()["label_map"]) == len(before["label_map"]) - 1
    stale = dclient.patch(
        f"{API}/projects/{pid}",
        json={"label_map": before["label_map"]},
        headers={"If-Match": before["etag"]},
    )
    assert stale.status_code == 412
    restored = patch_project(dclient, pid, {"label_map": before["label_map"]})
    assert restored.status_code == 200 and restored.json()["label_map"] == before["label_map"]
    assert dclient.get(f"{API}/projects/{pid}/segmentations").json() == sets
    assert (data_root / "seg/01_case_00001.nii.gz").read_bytes() == mask


def test_catalog_save_refuses_an_update_after_http_validation_but_before_writer_lock(
    dclient: TestClient, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRJ-15: indexing or another editor cannot be overwritten between ETag check and write."""
    from app.projects.models import ProjectPatch

    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    before = dclient.get(f"{API}/projects/{pid}").json()
    workspace = ctx_of(dclient).workspace
    original = workspace.update

    async def concurrent_update(project_id, patch, **kwargs):
        await original(project_id, ProjectPatch(description="Concurrent saved edit"))
        return await original(project_id, patch, **kwargs)

    monkeypatch.setattr(workspace, "update", concurrent_update)
    response = dclient.patch(
        f"{API}/projects/{pid}",
        json={"label_map": []},
        headers={"If-Match": before["etag"]},
    )
    assert response.status_code == 412, response.text
    after = dclient.get(f"{API}/projects/{pid}").json()
    assert after["description"] == "Concurrent saved edit"
    assert after["label_map"] == before["label_map"]


def test_manual_binary_folder_keeps_structure_names_and_source_files(
    dclient: TestClient, data_root: Path
) -> None:
    """SRC-20: binary structures map by name and can be served as one segmentation."""
    import nibabel as nib
    import numpy as np

    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    source = nib.load(data_root / "seg/01_case_00001.nii.gz")
    folder = data_root / "binary/case_00001/01"
    folder.mkdir(parents=True)
    for value, name in [(1, "kidney"), (2, "tumor")]:
        pixels = (np.asanyarray(source.dataobj) == value).astype(np.uint8)
        nib.save(nib.Nifti1Image(pixels, source.affine), folder / f"{name}.nii.gz")
    before = {path: path.read_bytes() for path in folder.iterdir()}
    started = dclient.post(
        f"{API}/projects/{pid}/segmentations/imports",
        json={
            "seg_id": "binary",
            "root": str(data_root),
            "template": "binary/{case_id}/{scan_idx}",
            "mode": "binary",
            "item_id": ITEM,
        },
    )
    assert started.status_code == 202, started.text
    assert wait(dclient, started.json()["job_id"]).status == "succeeded"
    item = dclient.get(f"{API}/projects/{pid}/items/{ITEM}").json()
    assert item["masks"]["binary"]["format"] == "nifti_dir"
    assert item["masks"]["binary"]["labels"] == {"kidney": 1, "tumor": 2}
    assert dclient.get(f"{API}/projects/{pid}/items/{ITEM}/mask?seg=binary").status_code == 200
    assert before == {path: path.read_bytes() for path in before}


def test_import_after_removing_every_set_establishes_a_usable_default(
    dclient: TestClient, data_root: Path
) -> None:
    """SRC-20 / API-24: a new active set replaces an unavailable default."""
    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    assert dclient.delete(f"{API}/projects/{pid}/segmentations/imported").status_code == 204
    started = dclient.post(
        f"{API}/projects/{pid}/segmentations/imports",
        json={
            "seg_id": "reviewed",
            "root": str(data_root / "seg/01_case_00001.nii.gz"),
            "item_id": ITEM,
        },
    )
    assert started.status_code == 202, started.text
    assert wait(dclient, started.json()["job_id"]).status == "succeeded"
    assert dclient.get(f"{API}/projects/{pid}").json()["default_seg"] == "reviewed"
    assert dclient.get(f"{API}/projects/{pid}/items/{ITEM}/mask").status_code == 200


def test_reimporting_the_original_imported_id_uses_the_new_manifest(
    dclient: TestClient, data_root: Path
) -> None:
    """SRC-20: reimport of the original set must not silently keep its previous mask."""
    import nibabel as nib
    import numpy as np

    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    original = data_root / "seg/01_case_00001.nii.gz"
    original_bytes = original.read_bytes()
    image = nib.load(original)
    pixels = np.asanyarray(image.dataobj).copy()
    pixels[pixels == 1] = 8
    replacement = data_root / "replacement.nii.gz"
    nib.save(nib.Nifti1Image(pixels, image.affine), replacement)
    assert dclient.delete(f"{API}/projects/{pid}/segmentations/imported").status_code == 204
    started = dclient.post(
        f"{API}/projects/{pid}/segmentations/imports",
        json={"seg_id": "imported", "root": str(replacement), "item_id": ITEM},
    )
    assert started.status_code == 202, started.text
    assert wait(dclient, started.json()["job_id"]).status == "succeeded"
    item = dclient.get(f"{API}/projects/{pid}/items/{ITEM}").json()
    assert item["masks"]["imported"]["ref"] == "DATA:replacement.nii.gz"
    assert 8 in item["labels_present"] and 1 not in item["labels_present"]
    assert (
        dclient.get(f"{API}/projects/{pid}/items/{ITEM}/mask").content == replacement.read_bytes()
    )
    assert original.read_bytes() == original_bytes


def test_cancel_manual_import_drains_probes_and_cannot_publish_or_remove_sets(
    dclient: TestClient, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SRC-20 / PRJ-07: a cancelled import never changes sets or the label catalog."""
    import threading

    from app.ingest import segmentation_imports

    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    before = dclient.get(f"{API}/projects/{pid}").json()
    entered, release = threading.Event(), threading.Event()
    original = segmentation_imports.probe_batch

    def blocked(probes):
        entered.set()
        if not release.wait(10):
            raise TimeoutError("Probe barrier was not released")
        return original(probes)

    monkeypatch.setattr(segmentation_imports, "probe_batch", blocked)
    try:
        started = dclient.post(
            f"{API}/projects/{pid}/segmentations/imports",
            json={
                "seg_id": "reviewed",
                "root": str(data_root / "seg/01_case_00001.nii.gz"),
                "item_id": ITEM,
            },
        )
        assert started.status_code == 202, started.text
        assert entered.wait(5)
        assert dclient.get(f"{API}/health").status_code == 200
        assert dclient.delete(f"{API}/projects/{pid}/segmentations/imported").status_code == 409
        assert (
            dclient.post(f"{API}/projects/{pid}/segmentations/imported/restore").status_code == 409
        )
        cancelled = dclient.post(f"{API}/jobs/{started.json()['job_id']}/cancel")
        assert cancelled.status_code == 200, cancelled.text
    finally:
        release.set()
    assert wait(dclient, started.json()["job_id"]).status == "cancelled"
    after = dclient.get(f"{API}/projects/{pid}").json()
    assert after["label_map"] == before["label_map"]
    assert after["segmentations"] == before["segmentations"]


@pytest.mark.parametrize(
    "template", ["../{case_id}.nii.gz", "{case_id.__class__}.nii.gz", "/{case_id}.nii.gz"]
)
def test_manual_import_template_cannot_escape_or_access_attributes(
    dclient: TestClient, data_root: Path, template: str
) -> None:
    """SRC-20 / R1: template fields are identities, never arbitrary path or object access."""
    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    response = dclient.post(
        f"{API}/projects/{pid}/segmentations/imports",
        json={"seg_id": "reviewed", "root": str(data_root), "template": template},
    )
    assert response.status_code == 422, response.text


def test_import_binary_mask_folder(dclient: TestClient, data_root: Path) -> None:
    pid = new_project(dclient)
    do_import(dclient, pid, data_root)
    folder = data_root / "reviewed" / "case_00001" / "01"
    folder.mkdir(parents=True)
    source = data_root / "seg" / "01_case_00001.nii.gz"
    shutil.copyfile(source, folder / "kidney.nii.gz")
    shutil.copyfile(source, folder / "tumor.nii.gz")

    r = dclient.post(
        f"{API}/projects/{pid}/segmentations/imports",
        json={
            "seg_id": "binary-review",
            "root": str(data_root),
            "template": "reviewed/{case_id}/{scan_idx}",
            "mode": "binary",
            "item_id": ITEM,
        },
    )
    assert r.status_code == 202, r.text
    assert wait(dclient, r.json()["job_id"]).status == "succeeded"
    item = dclient.get(f"{API}/projects/{pid}/items/{ITEM}").json()
    mask = item["masks"]["binary-review"]
    assert mask["format"] == "nifti_dir"
    assert mask["labels"] == {"kidney": 1, "tumor": 2}
    seg = next(
        s
        for s in dclient.get(f"{API}/projects/{pid}/segmentations").json()
        if s["seg_id"] == "binary-review"
    )
    assert seg["label_mapping"] == {"1": 1, "2": 2}


def test_problem_actions_in_body(client: TestClient) -> None:
    from app.core.errors import problem_body

    body: dict[str, Any] = problem_body("unsupported-format", "x", "/i", None, ["import_as:a"])
    assert body["status"] == 415 and body["actions"] == ["import_as:a"]
    assert "actions" not in problem_body("validation", "x", "/i")


def test_bundle_excludes_derived_ledger_volumes(tmp_path: Path) -> None:
    """Bundles never carry derived volumes (ADR-0014): the ledger holds refs only."""
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
