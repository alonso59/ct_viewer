"""DCM-03 / DCM-06 (AUD-A6-08): the header checks that decide skip / convert, one in-memory
pydicom series per warning code, and the per-series conversion decision (TST-13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from plugins.dicom import scan
from plugins.dicom.pipeline import Settings, decide_conversion
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

AXIAL = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
KEEP = object()
Tag = Any  # (index, dataset) -> value | KEEP | None (None removes the tag)


def at(k: int, value: Any) -> Tag:
    """`value` on slice `k` only"""
    return lambda i, ds: value if i == k else KEEP


def every(value: Any) -> Tag:
    return lambda i, ds: value


def slices(n: int = 5, spacing: float = 2.5, **over: Any) -> list[Dataset]:
    """A clean axial CT series; `over` maps a tag to a function (index, dataset) → value."""
    out = []
    for i in range(n):
        ds = Dataset()
        ds.Modality = "CT"
        ds.ImageOrientationPatient = list(AXIAL)
        ds.ImagePositionPatient = [0.0, 0.0, i * spacing]
        ds.PixelSpacing = [0.7, 0.7]
        ds.Rows, ds.Columns = 512, 512
        for tag, fn in over.items():
            value = fn(i, ds)
            if value is KEEP:
                continue
            if value is None:
                if tag in ds:
                    delattr(ds, tag)
            else:
                setattr(ds, tag, value)
        out.append(ds)
    return out


def geometry(datasets: list[Dataset]) -> scan.Inspection:
    out = scan.Inspection()
    scan._geometry(datasets, out)
    return out


def test_a_clean_series_has_no_code_and_its_spacing() -> None:
    g = geometry(slices())
    assert (g.geometry_status, g.geometry_codes) == ("ok", [])
    assert g.nominal_slice_spacing == pytest.approx(2.5) and g.maximum_spacing_deviation == 0


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"PixelSpacing": at(2, None)}, "GEOMETRY_METADATA_MISSING"),
        ({"ImageOrientationPatient": at(3, [1, 0, 0, 0, 0.9, 0.1])}, "ORIENTATION_CONFLICT"),
        ({"PixelSpacing": at(1, [0.8, 0.8])}, "IN_PLANE_SPACING_CONFLICT"),
        ({"Rows": at(4, 256)}, "MATRIX_SIZE_CONFLICT"),
        ({"ImagePositionPatient": at(2, [0.0, 0.0, 2.5])}, "DUPLICATE_SLICE_POSITION"),
    ],
)
def test_each_header_check_adds_its_code(over: dict[str, Any], code: str) -> None:
    g = geometry(slices(**over))
    assert code in g.geometry_codes and g.geometry_status == "warning"


@pytest.mark.parametrize(
    ("z", "codes"),
    [
        ([0, 2.5, 5.0, 7.6, 10.0], set()),  # within 5 % of the nominal spacing
        ([0, 2.5, 5.0, 8.0, 10.5], {"IRREGULAR_SLICE_SPACING"}),
        ([0, 2.5, 5.0, 7.5, 12.5, 15.0], {"IRREGULAR_SLICE_SPACING", "LARGE_SLICE_GAP"}),
        (
            [0, 2.5, 5.0, 25.0, 27.5, 30.0],
            {"IRREGULAR_SLICE_SPACING", "LARGE_SLICE_GAP", "POSSIBLE_MULTIPLE_STACKS"},
        ),
    ],
)
def test_slice_spacing_irregular_gaps_and_stacks(z: list[float], codes: set[str]) -> None:
    ds = slices(len(z), ImagePositionPatient=lambda i, _: [0.0, 0.0, z[i]])
    assert set(geometry(ds).geometry_codes) == codes


def test_only_duplicates_keeps_the_spacing_unknown() -> None:
    g = geometry(slices(3, ImagePositionPatient=every([0.0, 0.0, 0.0])))
    assert g.geometry_codes == ["DUPLICATE_SLICE_POSITION"]
    assert g.nominal_slice_spacing is None and g.maximum_spacing_deviation is None


def test_a_tilted_stack_measures_along_its_own_normal() -> None:
    """Oblique orientation: positions step along the slice normal, so the spacing is regular."""
    o = [1.0, 0.0, 0.0, 0.0, 0.8, 0.6]  # normal (0, -0.6, 0.8)
    ds = slices(
        4,
        ImageOrientationPatient=lambda i, _: o,
        ImagePositionPatient=lambda i, _: [0.0, -0.6 * 3 * i, 0.8 * 3 * i],
    )
    g = geometry(ds)
    assert g.geometry_codes == [] and g.nominal_slice_spacing == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"NumberOfFrames": every(40)}, "MULTIFRAME_OBJECT"),
        ({"SOPClassUID": every(scan.ENHANCED_CT_SOP_CLASS_UID)}, "ENHANCED_CT"),
        ({"SOPClassUID": every(scan.ENHANCED_MR_SOP_CLASS_UID)}, "ENHANCED_MR"),
        (
            {"SharedFunctionalGroupsSequence": every(Sequence([Dataset()]))},
            "SHARED_FUNCTIONAL_GROUPS_PRESENT",
        ),
        (
            {"PerFrameFunctionalGroupsSequence": every(Sequence([Dataset()]))},
            "PER_FRAME_FUNCTIONAL_GROUPS_PRESENT",
        ),
        ({"EchoNumbers": lambda i, ds: 1 + i % 2}, "MULTI_ECHO_INDICATORS"),
        ({"TemporalPositionIdentifier": lambda i, ds: i + 1}, "TEMPORAL_POSITION_INDICATORS"),
        ({"DiffusionBValue": every(800)}, "DIFFUSION_INDICATORS"),
        ({"GantryDetectorTilt": every(12.0)}, "GANTRY_TILT_INDICATOR"),
    ],
)
def test_advanced_dicom_indicators(over: dict[str, Any], code: str) -> None:
    out = scan.Inspection()
    scan._advanced(slices(**over), out)
    assert code in out.advanced_codes and out.advanced_status == "detected"


def test_standard_series_has_no_advanced_code_and_zero_tilt_is_none() -> None:
    out = scan.Inspection()
    scan._advanced(slices(GantryDetectorTilt=every(0.0), EchoNumbers=every(1)), out)
    assert (out.advanced_status, out.advanced_codes) == ("standard", [])


@pytest.mark.parametrize(
    ("components", "expected"),
    [
        (["M", "MAGNITUDE"], ("MAGNITUDE", "ok")),
        (["MAGNITUDE", "PHASE"], ("UNKNOWN", "heterogeneous")),
        (["", ""], ("UNKNOWN", "unknown")),
    ],
)
def test_mri_component(components: list[str], expected: tuple[str, str]) -> None:
    ds = slices(
        len(components),
        Modality=lambda i, _: "MR",
        ComplexImageComponent=lambda i, _: components[i] or None,
    )
    out = scan.Inspection()
    scan._mri(ds, out)
    assert (out.mri_component, out.mri_component_status) == expected


def test_mri_component_from_image_type() -> None:
    ds = slices(2, Modality=every("MR"), ImageType=every(["ORIGINAL", "PRIMARY", "P"]))
    out = scan.Inspection()
    scan._mri(ds, out)
    assert (out.mri_component, out.mri_component_status) == ("PHASE", "ok")


def test_inspect_reports_unreadable_headers_and_skips_multiframe_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series = scan.Series(Path("/in/s1"), "s1", (Path("/in/s1/a"), Path("/in/s1/b")))

    def broken(path: Path) -> Any:
        raise OSError("truncated file")

    monkeypatch.setattr(scan, "read_header", broken)
    diags: list[scan.Diagnostic] = []
    out = scan.inspect(series, slices(1)[0], diags)
    assert out.geometry_status == "unknown"
    assert [d.code for d in diags] == ["GEOMETRY_INSPECTION_FAILED"]
    # a single enhanced multi-frame file: no per-slice geometry to compare, advanced codes only
    one = scan.Series(Path("/in/s2"), "s2", (Path("/in/s2/a"),))
    mf = slices(1, NumberOfFrames=every(60), ImagePositionPatient=every(None))[0]
    diags = []
    out = scan.inspect(one, mf, diags)
    assert out.geometry_codes == [] and "MULTIFRAME_OBJECT" in out.advanced_codes and diags == []


def test_inspect_turns_geometry_codes_into_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    ds = slices(3, Rows=at(1, 256))
    by_path = dict(zip((Path(f"/in/s/{i}") for i in range(3)), ds, strict=True))
    monkeypatch.setattr(scan, "read_header", lambda p: by_path[p])
    diags: list[scan.Diagnostic] = []
    out = scan.inspect(scan.Series(Path("/in/s"), "s", tuple(by_path)), ds[0], diags)
    assert out.geometry_codes == ["MATRIX_SIZE_CONFLICT"]
    assert [(d.stage, d.code, d.series_id) for d in diags] == [
        ("geometry_validation", "MATRIX_SIZE_CONFLICT", "s")
    ]


UNSAFE = {"geometry_warning_codes": "LARGE_SLICE_GAP"}
MISSING = {"geometry_warning_codes": "GEOMETRY_METADATA_MISSING"}
SKIP = {"skip_unsafe_geometry": True}
AXIAL_R = "original axial"


@pytest.mark.parametrize(
    ("role", "reason", "row", "settings", "expected"),
    [
        ("PRIMARY", AXIAL_R, {}, {}, (True, "")),
        ("SECONDARY", "coronal", {}, {}, (True, "")),
        ("SECONDARY", "coronal", {}, {"convert_secondary": False}, (False, "secondary_disabled")),
        ("PRIMARY", AXIAL_R, {}, {"convert_primary": False}, (False, "primary_disabled")),
        ("EXCLUDED", "localizer", {}, {}, (False, "localizer")),
        ("EXCLUDED", "localizer", {}, {"convert_excluded": True}, (True, "")),
        ("PRIMARY", AXIAL_R, UNSAFE, {}, (True, "")),  # geometry only warns by default
        ("PRIMARY", AXIAL_R, UNSAFE, SKIP, (False, "unsafe_geometry")),
        ("EXCLUDED", "localizer", UNSAFE, SKIP, (False, "localizer")),
        ("PRIMARY", AXIAL_R, MISSING, SKIP, (True, "")),  # missing tags alone are not unsafe
    ],
)
def test_convert_or_skip_decision(
    role: str,
    reason: str,
    row: dict[str, Any],
    settings: dict[str, Any],
    expected: tuple[bool, str],
) -> None:
    assert decide_conversion(row, role, reason, Settings.from_dict(settings)) == expected
