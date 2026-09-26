"""Open-mode service (AUD-A6-05) through API-07/08: attach from the usual layouts next to a single
opened file (SRC-10, ADR-0027, AUD-A2-03), refusals with next actions (SRC-11, UI-18,
AUD-A2-07) and the modality of an opened dataset folder (VW-05, SRC-16, AUD-A2-10)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_contract import assert_problem
from tests.test_sources import ct, lab, nii

API = "/api/v1"


@pytest.fixture
def data(tmp_path: Path) -> Path:
    """The usual layouts under one data root: `nifti/` + `seg/` (with `metadata.jsonl`) and
    nnU-Net `imagesTr/` + `labelsTr/`; plus a mask in a folder that is not shared."""
    root = tmp_path / "data"
    nii(root / "ds" / "nifti" / "01_case_00001_0000.nii.gz", ct())
    nii(root / "ds" / "seg" / "01_case_00001.nii.gz", lab())
    nii(root / "nn" / "imagesTr" / "case_001_0000.nii.gz", ct())
    nii(root / "nn" / "labelsTr" / "case_001.nii.gz", lab())
    nii(tmp_path / "private" / "mask.nii.gz", lab())
    rows = [{"case_id": "case_00001", "scan_idx": "01", "modality": "MR",
             "relative_path": "nifti/01_case_00001_0000.nii.gz"}]  # fmt: skip
    (root / "ds" / "metadata.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return root


@pytest.fixture
def oc(tmp_path: Path, data: Path) -> Iterator[TestClient]:
    s = Settings(
        workspace_root=tmp_path / "ws",
        allowed_data_roots=str(data.resolve()),
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(s, inline_jobs=True)) as c:
        yield c


def open_(c: TestClient, path: Path) -> dict[str, object]:
    r = c.post(f"{API}/open", json={"path": str(path)})
    assert r.status_code == 201, r.text
    return dict(r.json())


@pytest.mark.parametrize(
    ("image", "mask"),
    [
        ("ds/nifti/01_case_00001_0000.nii.gz", "ds/seg/01_case_00001.nii.gz"),
        ("nn/imagesTr/case_001_0000.nii.gz", "nn/labelsTr/case_001.nii.gz"),
    ],
)
def test_attach_from_a_sibling_folder_of_a_single_file(
    oc: TestClient, data: Path, image: str, mask: str
) -> None:
    """SRC-10 (ADR-0027): a mask outside the opened file's folder attaches when the geometry
    matches; its bytes are served from where it is (read-only, R1)."""
    s = open_(oc, data / image)
    assert s["kind"] == "file" and s["root"] == str((data / image).parent.resolve())
    r = oc.post(f"{API}/open/{s['sid']}/items/0/attach", json={"path": str(data / mask)})
    assert r.status_code == 200, r.text
    label = r.json()["items"][-1]
    assert label["kind"] == "label" and label["attached_to"] == 0
    assert label["rel"] == str((data / mask).resolve())  # outside the root: absolute
    got = oc.get(f"{API}/open/{s['sid']}/items/{label['n']}/image")
    assert got.status_code == 200 and got.content == (data / mask).read_bytes()


def test_attach_is_still_guarded(oc: TestClient, data: Path, tmp_path: Path) -> None:
    s = open_(oc, data / "ds" / "nifti" / "01_case_00001_0000.nii.gz")
    url = f"{API}/open/{s['sid']}/items/0/attach"
    # outside ALLOWED_DATA_ROOTS: refused with the next steps, without naming server settings
    r = oc.post(url, json={"path": str(tmp_path / "private" / "mask.nii.gz")})
    assert_problem(r, "path-outside-root")
    assert r.json()["actions"] == ["choose_another_path", "home"]
    assert "ALLOWED_DATA_ROOTS" not in r.json()["detail"]
    # the geometry check stays the guard (SRC-10)
    nii(data / "ds" / "seg" / "small.nii.gz", lab((4, 4, 4)))
    assert_problem(
        oc.post(url, json={"path": str(data / "ds" / "seg" / "small.nii.gz")}),
        "geometry-mismatch",
    )


def test_open_refusals_carry_actions(oc: TestClient, data: Path, tmp_path: Path) -> None:
    """UI-18 (AUD-A2-07): not found, outside the shared folders, nothing to open."""
    r = oc.post(f"{API}/open", json={"path": str(data / "nope.nii.gz")})
    assert_problem(r, "not-found")
    assert "nope.nii.gz" in r.json()["detail"]
    assert r.json()["actions"] == ["choose_another_path", "home"]
    r = oc.post(f"{API}/open", json={"path": str(tmp_path / "private")})
    assert_problem(r, "path-outside-root")
    assert r.json()["actions"] == ["choose_another_path", "home"]
    (data / "empty").mkdir()
    r = oc.post(f"{API}/open", json={"path": str(data / "empty")})
    assert_problem(r, "unsupported-format")
    assert r.json()["actions"] == ["choose_another_path", "home"]


def test_modality_from_the_dataset_rows(oc: TestClient, data: Path) -> None:
    """VW-05 / SRC-16 (AUD-A2-10): a known modality is not "assumed"."""
    folder = open_(oc, data / "ds")
    by_name = {i["name"]: i for i in folder["items"]}  # type: ignore[attr-defined]
    assert by_name["01_case_00001_0000.nii.gz"]["modality"] == "MR"
    assert by_name["01_case_00001.nii.gz"]["modality"] is None  # no row: unknown
    single = open_(oc, data / "ds" / "nifti" / "01_case_00001_0000.nii.gz")
    assert single["items"][0]["modality"] == "MR"  # type: ignore[index]
    plain = open_(oc, data / "nn" / "imagesTr" / "case_001_0000.nii.gz")
    assert plain["items"][0]["modality"] is None  # type: ignore[index]
