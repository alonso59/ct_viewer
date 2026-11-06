"""DCM-35: one MR series UID holding several acquisitions is split into stacks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rw_dicom import scan
from rw_dicom.pipeline import Settings, decide_conversion


def _header(z: float, **tags: object) -> SimpleNamespace:
    base = {
        "Modality": "MR",
        "ImageOrientationPatient": [1, 0, 0, 0, 1, 0],
        "ImagePositionPatient": [0, 0, z],
        "PixelSpacing": [1, 1],
        "Rows": 4,
        "Columns": 4,
        "ImageType": ["ORIGINAL", "PRIMARY", "M_FFE", "M", "FFE"],
    }
    return SimpleNamespace(**{**base, **tags})


def _series(headers: list[SimpleNamespace]) -> scan.Series:
    files = tuple(Path(f"f{i}.dcm") for i in range(len(headers)))
    return scan.Series(Path("."), "1.2.3", files, tuple(headers))


def test_two_echoes_at_the_same_positions_become_two_stacks() -> None:
    series = _series([_header(float(z), EchoNumbers=str(e)) for e in (2, 1) for z in range(5)])
    parts = scan.split_series(series)
    assert [(p.series_id, p.part, len(p.files)) for p in parts] == [
        ("1.2.3", "e1", 5),
        ("1.2.3#e2", "e2", 5),
    ]
    assert all(scan.inspect(p, p.headers[0], []).geometry_codes == [] for p in parts)
    assert scan.select_part(series, "e2").files == parts[1].files


def test_b_values_and_dynamics_split_by_every_varying_tag() -> None:
    series = _series(
        [
            _header(float(z), TemporalPositionIdentifier=str(t), DiffusionBValue=str(b))
            for t in (1, 2)
            for b in (0, 800)
            for z in range(3)
        ]
    )
    assert [p.part for p in scan.split_series(series)] == ["t1b0", "t1b800", "t2b0", "t2b800"]


def test_a_series_nothing_explains_stays_whole() -> None:
    same = _series([_header(float(z % 3)) for z in range(6)])
    single_position = _series([_header(0.0, TemporalPositionIdentifier=str(t)) for t in range(6)])
    uneven = _series(
        [_header(float(z), EchoNumbers="1") for z in range(5)] + [_header(0.0, EchoNumbers="2")]
    )
    assert all(len(scan.split_series(s)) == 1 for s in (same, single_position, uneven))


def test_ct_and_clean_series_are_never_split() -> None:
    ct = _series([_header(float(z % 2), Modality="CT", EchoNumbers=str(z % 2)) for z in range(6)])
    clean = _series([_header(float(z), EchoNumbers=str(z)) for z in range(6)])
    assert scan.split_series(ct) == [ct] and scan.split_series(clean) == [clean]


def test_real_and_imaginary_parts_are_labelled_by_component() -> None:
    types = {
        "real": ["ORIGINAL", "PRIMARY", "OTHER", "REAL"],
        "imaginary": ["ORIGINAL", "PRIMARY", "OTHER", "IMAGINARY"],
    }
    series = _series([_header(float(z), ImageType=t) for t in types.values() for z in range(4)])
    assert [p.part for p in scan.split_series(series)] == ["iimaginary", "ireal"]


def test_remaining_repeats_and_projections_are_not_volumes() -> None:
    settings = Settings.from_dict({})
    row = {"modality": "MR", "geometry_warning_codes": "DUPLICATE_SLICE_POSITION"}
    assert decide_conversion(row, "PRIMARY", "", settings) == (False, "not_volumetric")
    assert (
        decide_conversion(
            {**row, "geometry_warning_codes": "ORIENTATION_CONFLICT"}, "PRIMARY", "", settings
        )[1]
        == "not_volumetric"
    )
    assert decide_conversion({**row, "modality": "CT"}, "PRIMARY", "", settings) == (True, "")


def test_image_types_without_a_complex_component_are_not_unknown() -> None:
    dixon = [SimpleNamespace(ImageType=["DERIVED", "PRIMARY", "W", "W", "DERIVED"])]
    assert scan.mri_component(dixon) == ("", "not_complex")
    assert scan.mri_component([SimpleNamespace()]) == ("UNKNOWN", "unknown")


def test_zero_b_value_and_one_dynamic_are_not_indicators() -> None:
    inspection = scan.Inspection()
    scan._advanced(
        [
            _header(float(z), DiffusionBValue="0.0", TemporalPositionIdentifier="1")
            for z in range(3)
        ],
        inspection,
    )
    assert inspection.advanced_codes == []


def test_image_types_that_name_no_component_get_distinct_labels() -> None:
    types = (["DERIVED", "PRIMARY", "W", "W"], ["DERIVED", "PRIMARY", "F", "F"])
    series = _series([_header(float(z), ImageType=t) for t in types for z in range(4)])
    parts = scan.split_series(series)
    assert len({p.series_id for p in parts}) == 2
