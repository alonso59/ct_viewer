from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import nibabel as nib
import numpy as np

from app.api import slices as slices_api
from app.main import app
from app.services.slice_cache import slice_cache
from app.services.volume_cache import volume_cache


def test_volume_metadata_endpoint_is_authenticated_and_uses_etag(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RADIOLOGY_UI_TOKEN", "secret-token")
    volume_cache.reset()
    image_path, mask_path, _ct, _mask = _write_case(tmp_path)
    info = _load_case(image_path, mask_path)
    client = TestClient(app)

    unauthenticated = client.get(f"/api/volumes/{info.load_handle}/metadata")
    assert unauthenticated.status_code == 401

    headers = {"Authorization": "Bearer secret-token"}
    response = client.get(f"/api/volumes/{info.load_handle}/metadata", headers=headers)
    assert response.status_code == 200
    assert response.headers["etag"]
    assert response.json()["fingerprint"] == info.metadata.fingerprint
    assert response.json()["geometry"]["dimensions"] == [2, 3, 4]
    assert response.json()["alignment"]["cornerstone_compatible"] is True

    not_modified = client.get(
        f"/api/volumes/{info.load_handle}/metadata",
        headers={**headers, "If-None-Match": response.headers["etag"]},
    )
    assert not_modified.status_code == 304


def test_volume_binary_endpoints_return_current_array_contract_and_etags(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("RADIOLOGY_UI_TOKEN", raising=False)
    volume_cache.reset()
    image_path, mask_path, ct, mask = _write_case(tmp_path)
    info = _load_case(image_path, mask_path)
    client = TestClient(app)

    ct_response = client.get(f"/api/volumes/{info.load_handle}/ct")
    assert ct_response.status_code == 200
    assert ct_response.headers["content-type"] == "application/octet-stream"
    assert ct_response.headers["x-volume-dimensions"] == "2,3,4"
    assert ct_response.headers["x-volume-dtype"] == "float32"
    assert ct_response.headers["x-volume-byte-order"] == "little"
    ct_payload = np.frombuffer(ct_response.content, dtype=np.float32).reshape((2, 3, 4))
    np.testing.assert_array_equal(ct_payload, ct.astype(np.float32))

    ct_not_modified = client.get(
        f"/api/volumes/{info.load_handle}/ct",
        headers={"If-None-Match": ct_response.headers["etag"]},
    )
    assert ct_not_modified.status_code == 304

    segmentation_response = client.get(f"/api/volumes/{info.load_handle}/segmentation")
    assert segmentation_response.status_code == 200
    assert segmentation_response.headers["content-type"] == "application/octet-stream"
    assert segmentation_response.headers["x-volume-dtype"] == "uint8"
    segmentation_payload = np.frombuffer(segmentation_response.content, dtype=np.uint8).reshape(
        (2, 3, 4)
    )
    np.testing.assert_array_equal(segmentation_payload, mask)


def test_shape_mismatch_keeps_ct_endpoint_and_rejects_segmentation_payload(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("RADIOLOGY_UI_TOKEN", raising=False)
    volume_cache.reset()
    image_path = tmp_path / "ct.nii.gz"
    mask_path = tmp_path / "seg.nii.gz"
    _write_nifti(image_path, np.zeros((2, 3, 4), dtype=np.float32), np.eye(4))
    mask = np.zeros((2, 3, 3), dtype=np.uint8)
    mask[1, 2, 2] = 1
    _write_nifti(mask_path, mask, np.eye(4))
    info = _load_case(image_path, mask_path)
    client = TestClient(app)

    ct_response = client.get(f"/api/volumes/{info.load_handle}/ct")
    assert ct_response.status_code == 200

    segmentation_response = client.get(f"/api/volumes/{info.load_handle}/segmentation")
    assert segmentation_response.status_code == 409
    assert "segmentation overlays are disabled" in segmentation_response.json()["detail"]


def test_slice_endpoint_reuses_png_cache_across_reload_handles(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("RADIOLOGY_UI_TOKEN", raising=False)
    volume_cache.reset()
    slice_cache.reset()
    image_path, mask_path, _ct, _mask = _write_case(tmp_path)
    first_info = _load_case(image_path, mask_path)
    client = TestClient(app)
    render_calls: list[int] = []

    def fake_render_slice(**kwargs):
        render_calls.append(int(kwargs["index"]))
        return b"cached-png"

    monkeypatch.setattr(slices_api, "render_slice", fake_render_slice)

    first_response = client.get(
        f"/api/slice/axial/1?load_handle={first_info.load_handle}&ww=400&wl=50&layers=1"
    )
    second_info = _load_case(image_path, mask_path)
    second_response = client.get(
        f"/api/slice/axial/1?load_handle={second_info.load_handle}&ww=400&wl=50&layers=1"
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.content == b"cached-png"
    assert second_response.content == b"cached-png"
    assert render_calls == [1]


def _load_case(image_path: Path, mask_path: Path | None):
    return volume_cache.load_case_source(
        dataset_id="Dataset",
        case_id="case-1",
        series_id="series-1",
        image_path=str(image_path),
        mask_path=str(mask_path) if mask_path is not None else None,
        source_type="nifti",
        cache_key_suffix=f"{image_path.name}:{mask_path.name if mask_path else ''}",
    )


def _write_case(tmp_path: Path):
    image_path = tmp_path / "ct.nii.gz"
    mask_path = tmp_path / "seg.nii.gz"
    ct = np.arange(2 * 3 * 4, dtype=np.float32).reshape((2, 3, 4))
    mask = np.zeros((2, 3, 4), dtype=np.uint8)
    mask[1, 2, 3] = 2
    _write_nifti(image_path, ct, np.eye(4))
    _write_nifti(mask_path, mask, np.eye(4))
    return image_path, mask_path, ct, mask


def _write_nifti(path: Path, data: np.ndarray, affine: np.ndarray) -> None:
    nib.save(nib.Nifti1Image(data, affine), str(path))
