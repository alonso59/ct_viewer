"""D09/U08, SRC-09/10/13/14/18: later pages retain selected metadata, overlays and saves."""

from __future__ import annotations

import gzip
import hashlib
import os
from pathlib import Path

import nibabel as nib
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_sources import ct, lab, nii
from tools.dicom_fixtures import write_series

API = "/api/v1/open"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_later_page_selection_retains_its_overlay_without_changing_default_preview(
    tmp_path: Path,
) -> None:
    source, derived = tmp_path / "source", tmp_path / "derived"
    images = source / "images"
    first = nii(images / "0000.nii.gz", ct())
    for i in range(1, 503):
        os.link(first, images / f"{i:04}.nii.gz")
    mask = nii(source / "masks" / "mask.nii.gz", lab())
    before = {p: digest(p) for p in source.rglob("*") if p.is_file()}
    derived.mkdir()
    config = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        allowed_derived_roots=str(derived),
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(config, inline_jobs=True)) as client:
        response = client.post(API, json={"path": str(images)})
        assert response.status_code == 201, response.text
        session = response.json()
        assert len(session["items"]) == 500 and session["truncated"] is True
        sid = session["sid"]
        later = client.get(
            f"{API}/{sid}/items", params={"cursor": "500", "limit": 50, "kind": "image"}
        ).json()
        assert [r["n"] for r in later["items"]] == [500, 501, 502]
        assert later["total"] == 503 and later["next_cursor"] is None
        response = client.post(f"{API}/{sid}/items/502/attach", json={"path": str(mask)})
        assert response.status_code == 200, response.text
        focus = client.get(f"{API}/{sid}", params={"item": 502})
        assert focus.status_code == 200, focus.text
        selected = focus.json()["items"]
        assert [r["n"] for r in selected] == [502, 503]
        assert selected[1]["attached_to"] == 502
        assert client.get(f"{API}/{sid}/items", params={"kind": "image"}).json()["total"] == 503
        assert client.get(f"{API}/{sid}/items", params={"kind": "label"}).json()["total"] == 1
        assert len(client.get(f"{API}/{sid}").json()["items"]) == 500
        assert client.get(f"{API}/{sid}/items/503/image").content == mask.read_bytes()
        response = client.post(f"{API}/{sid}/items/502/save", json={"dest_dir": str(derived)})
        assert response.status_code == 201, response.text
        assert Path(response.json()["path"]).read_bytes() == first.read_bytes()
        assert client.get(f"{API}/{sid}", params={"item": 999}).status_code == 404
        assert client.get(f"{API}/{sid}", params={"item": -1}).status_code == 422
        assert before == {p: digest(p) for p in source.rglob("*") if p.is_file()}


def test_a_dicom_series_after_500_other_series_keeps_every_slice(tmp_path: Path) -> None:
    source = tmp_path / "source"
    for i in range(503):
        write_series(source / f"{i:04}", patient_id=f"P{i}", shape=(3, 3, 3), marker=(1, 1, 2))
    before = {p: digest(p) for p in source.rglob("*") if p.is_file()}
    config = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        dicom_memory_mb=1024,
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(config, inline_jobs=True)) as client:
        response = client.post(API, json={"path": str(source)})
        assert response.status_code == 201, response.text
        sid = response.json()["sid"]
        page = client.get(
            f"{API}/{sid}/items", params={"cursor": "500", "limit": 50, "kind": "image"}
        ).json()
        assert page["total"] == 503 and len(page["items"]) == 3
        focus = client.get(f"{API}/{sid}", params={"item": 502}).json()
        selected = focus["items"][0]
        assert selected["n"] == 502 and len(selected["files"]) == 3
        assert selected["geometry"]["shape"] == [3, 3, 3]
        volume = client.get(f"{API}/{sid}/items/502/image")
        assert volume.status_code == 200, volume.text[:100] if volume.status_code != 200 else ""
        image = nib.Nifti1Image.from_bytes(gzip.decompress(volume.content))
        assert image.shape == (3, 3, 3)
        assert before == {p: digest(p) for p in source.rglob("*") if p.is_file()}


def test_dicom_presence_survives_a_nifti_only_initial_preview(tmp_path: Path) -> None:
    source = tmp_path / "source"
    first = nii(source / "0000.nii.gz", ct())
    for i in range(1, 501):
        os.link(first, source / f"{i:04}.nii.gz")
    write_series(source / "dicom", shape=(3, 3, 3), marker=(1, 1, 2))
    config = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(config, inline_jobs=True)) as client:
        session = client.post(API, json={"path": str(source)}).json()
        assert len(session["items"]) == 500 and all(
            i["format"] == "nifti" for i in session["items"]
        )
        assert session["has_dicom"] is True
        assert client.get(f"{API}/{session['sid']}", params={"item": 0}).json()["has_dicom"] is True
