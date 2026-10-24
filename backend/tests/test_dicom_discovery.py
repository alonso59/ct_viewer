"""ADR-0035 Wave 1: D01/D02/D03/D05/D07, SRC-01/02/09/13 and DCM-02/06.

Independent tiny DICOM fixtures exercise complete membership and actual image geometry.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
import pytest
from fastapi.testclient import TestClient
from plugins.dicom import scan

from app.config import Settings
from app.main import create_app
from app.sources import formats
from app.sources import open as om
from app.tasks import dicom_stage
from tools.dicom_fixtures import MARKER, write_series


@pytest.mark.parametrize("suffix", [".dcm", ".DCM", "", ".ima", ".001", ".dicom"])
@pytest.mark.parametrize("preamble", [True, False])
def test_recognition_agrees_across_entry_points(
    tmp_path: Path, suffix: str, preamble: bool
) -> None:
    """D03: supported image headers, not suffixes, decide DICOM membership (SRC-02)."""
    root = tmp_path / "source"
    folder = root / "deep" / "study" / "series"
    write_series(folder, shape=(3, 3, 1), marker=(1, 1, 0), seed="recognition")
    original = next(folder.iterdir())
    content = original.read_bytes()
    target = folder / ("slice" + suffix)
    original.unlink()
    target.write_bytes(content if preamble else content[132:])
    assert formats.classify(target) == "dicom"
    discovered = scan.discover(root, [])
    assert len(discovered) == 1
    assert discovered[0].files == (target,)
    s = formats.scan(root)
    assert s.files["dicom"] == [target.relative_to(root).as_posix()]
    rows = om.probe(str(root), om.accepted(s))
    assert len(rows) == 1 and rows[0]["geometry"]["shape"] == [3, 3, 1]
    out = tmp_path / "derived" / "converted.nii.gz"
    assert dicom_stage.convert_series(str(root), rows[0]["files"], str(out)) is None
    image = nib.load(out)
    assert image.shape == (3, 3, 1)
    assert np.count_nonzero(np.asanyarray(image.dataobj) == MARKER) == 1
    assert target.read_bytes() == (content if preamble else content[132:])


@pytest.mark.parametrize("content", [b"", b"not a DICOM", bytes(128) + b"DICM" + bytes(10)])
def test_fake_dcm_is_not_an_image(tmp_path: Path, content: bytes) -> None:
    """D03/D04: extension and preamble alone cannot assert an image exists (SRC-02)."""
    path = tmp_path / "fake.dcm"
    path.write_bytes(content)
    assert formats.classify(path) is None
    assert formats.scan(tmp_path).files["dicom"] == []


def test_pixel_tag_bytes_inside_a_private_value_do_not_truncate_the_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D03/D07: a byte pattern inside a value is not the actual PixelData element."""
    root = tmp_path / "source"
    write_series(root, shape=(3, 3, 1), marker=(1, 1, 0))
    path = next(root.iterdir())
    ds = pydicom.dcmread(path)
    ds.add_new((0x0009, 0x1001), "OB", b"\xe0\x7f\x10\x00" + b"x" * 70_000)
    ds.save_as(path, enforce_file_format=True)
    assert formats.classify(path) == "dicom"
    found = scan.discover(root, [])
    assert len(found) == 1
    assert len(scan.first_header(found[0])[(0x0009, 0x1001)].value) == 70_004
    monkeypatch.setattr(scan, "MAX_HEADER_BYTES", 32_768)
    with pytest.raises(ValueError, match="budget"):
        scan.image_info(path, root)


def test_open_keeps_every_slice_before_conversion(tmp_path: Path) -> None:
    """D02 / TST-13: the old 500-file prefix loses both the z extent and final marker."""
    root = tmp_path / "source"
    info = write_series(
        root / "patient" / "study" / "series",
        shape=(3, 3, 750),
        marker=(1, 1, 749),
        seed="complete-series",
    )
    s = formats.scan(root)
    rows = om.probe(str(root), om.accepted(s))
    assert len(rows) == 1
    assert len(rows[0]["files"]) == 750
    assert rows[0]["geometry"]["shape"] == [3, 3, 750]
    out = tmp_path / "derived" / "volume.nii.gz"
    assert dicom_stage.convert_series(str(root), rows[0]["files"], str(out)) is None
    image = nib.load(out)
    assert image.shape == (3, 3, 750)
    marker = np.argwhere(np.asanyarray(image.dataobj) == MARKER)
    assert marker.shape == (1, 3)
    expected = np.asarray(info["marker_lps"]) * [-1, -1, 1]
    np.testing.assert_allclose(
        nib.affines.apply_affine(image.affine, marker[0]), expected, atol=0.01
    )


def test_discovery_never_follows_a_source_escape(tmp_path: Path) -> None:
    """D05: accepted file symlinks must not expose a sibling outside the chosen source."""
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "private"
    write_series(outside, shape=(3, 3, 1), marker=(1, 1, 0))
    (root / "escaped.dcm").symlink_to(next(outside.iterdir()))
    (root / "nested").symlink_to(outside, target_is_directory=True)
    assert formats.scan(root).n_accepted == 0
    assert scan.discover(root, []) == []


def test_traversal_budget_counts_files_not_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D01/D07: folder depth cannot consume the accepted-file budget (SRC-01/09)."""
    root = tmp_path / "root"
    for index in range(2):
        folder = root / str(index) / "a" / "b" / "c"
        folder.mkdir(parents=True)
        (folder / "volume.nii").write_bytes(b"fixture header probed later")
    monkeypatch.setattr(formats, "MAX_FILES", 2)
    found = formats.scan(root)
    assert len(found.files["nifti"]) == 2
    assert not found.truncated


def test_excluded_tree_is_pruned_before_descent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D07: do not eagerly rglob ignored output roots (SRC-02, BE-12)."""
    root = tmp_path / "root"
    (root / "derived" / "nested").mkdir(parents=True)
    (root / "image.nii").write_bytes(b"fixture header probed later")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("discovery must stream rather than materialize rglob")

    monkeypatch.setattr(Path, "rglob", forbidden)
    assert formats.scan(root).files["nifti"] == ["image.nii"]


def test_open_pages_complete_series_and_later_items_remain_viewable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D09 / SRC-18: item paging replaces a file prefix; API-07 shape stays compatible."""
    root = tmp_path / "source"
    for index in range(3):
        write_series(
            root / f"series-{index}",
            shape=(3, 3, 2),
            marker=(1, 1, 1),
            series_number=index,
            seed="paging",
        )
    settings = Settings(
        dicom_memory_mb=1024,
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(root),
        _env_file=None,  # type: ignore[call-arg]
    )
    monkeypatch.setattr(om, "MAX_ITEMS", 1)
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        response = client.post("/api/v1/open", json={"path": str(root)})
        assert response.status_code == 201, response.text
        opened = response.json()
        assert len(opened["items"]) == 1
        assert len(opened["items"][0]["files"]) == 2
        sid = opened["sid"]
        first = client.get(f"/api/v1/open/{sid}/items", params={"limit": 2})
        assert first.status_code == 200, first.text
        page = first.json()
        assert page["total"] == 3 and page["next_cursor"]
        last = client.get(
            f"/api/v1/open/{sid}/items", params={"limit": 2, "cursor": page["next_cursor"]}
        ).json()
        assert last["next_cursor"] is None
        members = page["items"] + last["items"]
        assert [item["n"] for item in members] == [0, 1, 2]
        assert all(len(item["files"]) == 2 for item in members)
        image = client.get(f"/api/v1/open/{sid}/items/2/image")
        assert image.status_code == 200
        assert nib.Nifti1Image.from_bytes(gzip.decompress(image.content)).shape == (3, 3, 2)
