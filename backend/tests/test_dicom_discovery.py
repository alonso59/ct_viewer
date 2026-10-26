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


@pytest.mark.parametrize(
    "syntax",
    [
        "1.2.840.10008.1.2",
        "1.2.840.10008.1.2.1",
        "1.2.840.10008.1.2.2",
        "1.2.840.10008.1.2.1.99",
        "1.2.840.10008.1.2.5",
        "1.2.840.10008.1.2.4.90",
    ],
)
@pytest.mark.parametrize("suffix", ["", ".ima"])
def test_encoded_mixed_uid_membership_and_geometry_match_independent_gdcm(
    tmp_path: Path, syntax: str, suffix: str
) -> None:
    """D03/D06/D28 / SRC-02, DCM-02/10: no suffix or InstanceNumber ordering assumption."""
    import SimpleITK as sitk
    from pydicom.uid import UID

    from app.tasks.source_inventory import SourceInventory

    source = tmp_path / "source"
    folder = source / "deep/study/series"
    folder.mkdir(parents=True)
    expected = set()
    for index in range(2):
        temporary = tmp_path / f"staging{index}"
        facts = write_series(
            temporary,
            patient_id=f"ENCODING{index}",
            shape=(64, 64, 5),
            marker=(1, 2, 3),
            seed="gdcm-encoding-oracle",
        )
        expected.add(str(facts["series_uid"]))
        for position, path in enumerate(sorted(temporary.iterdir())):
            ds = pydicom.dcmread(path)
            pixels = ds.pixel_array
            ds.InstanceNumber = 100 - position
            if syntax == "1.2.840.10008.1.2.5":
                ds.compress(UID(syntax), generate_instance_uid=False)
            else:
                ds.file_meta.TransferSyntaxUID = UID(syntax)
            if syntax == "1.2.840.10008.1.2.2":
                ds.PixelData = pixels.astype(">i2").tobytes()
            elif syntax == "1.2.840.10008.1.2.4.90":
                from io import BytesIO

                from PIL import Image
                from pydicom.encaps import encapsulate

                encoded = BytesIO()
                Image.fromarray((pixels.astype(np.int32) + 1024).astype(np.uint16)).save(
                    encoded,
                    format="JPEG2000",
                    no_jp2=True,
                    irreversible=False,
                    num_resolutions=1,
                )
                ds.PixelData = encapsulate([encoded.getvalue()])
                ds["PixelData"].is_undefined_length = True
                ds.PixelRepresentation, ds.RescaleIntercept = 0, -1024
            target = folder / f"{index}-{5 - position:03d}{suffix}"
            pydicom.dcmwrite(
                target,
                ds,
                implicit_vr=syntax == "1.2.840.10008.1.2",
                little_endian=syntax != "1.2.840.10008.1.2.2",
                enforce_file_format=True,
            )
    before = {path: path.read_bytes() for path in folder.iterdir()}
    native_ids = sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(folder))
    assert set(native_ids) == expected
    native_members = {
        uid: tuple(
            Path(path) for path in sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(folder), uid)
        )
        for uid in native_ids
    }
    assert sum(map(len, native_members.values())) == 10
    assert len(formats.scan(source).files["dicom"]) == 10
    discovered = scan.discover(source, [])
    assert {series.series_id: series.files for series in discovered} == native_members
    with SourceInventory(tmp_path / "workspace/inventory.sqlite", source) as inventory:
        assert inventory.scan()["complete"]
        assert {
            series.series_id: series.files for series in inventory.discover(source)
        } == native_members
    for index, series in enumerate(discovered):
        reader = sitk.ImageSeriesReader()
        reader.SetImageIO("GDCMImageIO")
        reader.SetFileNames([str(path) for path in native_members[series.series_id]])
        reference = sitk.DICOMOrient(reader.Execute(), "RAS")
        output = tmp_path / f"derived/{index}.nii.gz"
        assert (
            dicom_stage.convert_series(
                str(source), [str(path.relative_to(source)) for path in series.files], str(output)
            )
            is None
        )
        image = nib.load(output)
        np.testing.assert_array_equal(
            np.asanyarray(image.dataobj), sitk.GetArrayFromImage(reference).transpose(2, 1, 0)
        )
        [marker] = np.argwhere(np.asanyarray(image.dataobj) == MARKER)
        np.testing.assert_allclose(image.affine @ [*marker, 1], [19.3, 28.2, 107.5, 1], atol=1e-4)
    assert before == {path: path.read_bytes() for path in before}


@pytest.mark.parametrize(
    "modality,sop", [("CT", "1.2.840.10008.5.1.4.1.1.2.1"), ("MR", "1.2.840.10008.5.1.4.1.1.4.1")]
)
def test_enhanced_multiframe_geometry_matches_native_reader_and_known_landmark(
    tmp_path: Path, modality: str, sop: str
) -> None:
    """D03/D28/D31 / SRC-02, DCM-02/10: one enhanced object retains every frame."""
    import SimpleITK as sitk
    from pydicom.dataset import Dataset
    from pydicom.sequence import Sequence

    staging = tmp_path / "staging"
    write_series(
        staging, shape=(4, 3, 5), marker=(1, 2, 3), modality=modality, seed="enhanced-oracle"
    )
    slices = [pydicom.dcmread(path) for path in sorted(staging.iterdir())]
    ds = slices[0]
    pixels = b"".join(part.PixelData for part in slices)
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID = sop
    ds.NumberOfFrames = len(slices)
    ds.PixelData = pixels
    ds.VolumetricProperties = "VOLUME"
    measures = Dataset()
    measures.PixelSpacing, measures.SliceThickness = ds.PixelSpacing, ds.SliceThickness
    measures.SpacingBetweenSlices = ds.SliceThickness
    orientation = Dataset()
    orientation.ImageOrientationPatient = ds.ImageOrientationPatient
    shared = Dataset()
    shared.PixelMeasuresSequence = Sequence([measures])
    shared.PlaneOrientationSequence = Sequence([orientation])
    ds.SharedFunctionalGroupsSequence = Sequence([shared])
    frames = []
    for index, part in enumerate(slices):
        position = Dataset()
        position.ImagePositionPatient = part.ImagePositionPatient
        content = Dataset()
        content.StackID, content.InStackPositionNumber = "1", index + 1
        frame = Dataset()
        frame.PlanePositionSequence = Sequence([position])
        frame.FrameContentSequence = Sequence([content])
        frames.append(frame)
    ds.PerFrameFunctionalGroupsSequence = Sequence(frames)
    source = tmp_path / "source/deep/series"
    source.mkdir(parents=True)
    path = source / "enhanced"
    ds.save_as(path, enforce_file_format=True)
    before = path.read_bytes()
    reference = sitk.DICOMOrient(sitk.ReadImage(str(path), imageIO="GDCMImageIO"), "RAS")
    assert reference.GetSize() == (4, 3, 5)
    assert formats.classify(path) == "dicom"
    [series] = scan.discover(source, [])
    assert series.files == (path,)
    assert "MULTIFRAME_OBJECT" in scan.inspect(series, scan.first_header(series), []).advanced_codes
    output = tmp_path / "derived/enhanced.nii.gz"
    assert dicom_stage.convert_series(str(source), [path.name], str(output)) is None
    image = nib.load(output)
    np.testing.assert_array_equal(
        np.asanyarray(image.dataobj), sitk.GetArrayFromImage(reference).transpose(2, 1, 0)
    )
    [marker] = np.argwhere(np.asanyarray(image.dataobj) == MARKER)
    np.testing.assert_allclose(image.affine @ [*marker, 1], [19.3, 28.2, 107.5, 1], atol=1e-4)
    assert path.read_bytes() == before


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
