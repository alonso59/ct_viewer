"""TST-16 analyzers (ANZ-01..08): phase text/timing/conflict cases, target profiles, readiness
codes, vocabulary mapping. Pure functions over rows (no pixels)."""

from __future__ import annotations

from typing import Any

import pytest
from plugins.analyzers import phase, readiness, target

CCRCC = ["NC", "CMP", "NP", "EP", "UNK"]
GENERIC = ["NC", "ART", "PV", "DELAYED", "UNK"]


def row(**kw: Any) -> dict[str, Any]:
    return {"item_id": "c.01.complete.-", "modality": "CT", **kw}


@pytest.mark.parametrize(
    ("fields", "vocab", "value", "confidence"),
    [
        ({"series_description": "ABD NON-CONTRAST"}, CCRCC, "NC", "high"),
        ({"series_description": "corticomedullary 1.5mm"}, CCRCC, "CMP", "high"),
        ({"protocol_name": "Nephrographic phase"}, CCRCC, "NP", "high"),
        ({"series_description": "EXCRETORY"}, CCRCC, "EP", "high"),
        ({"series_description": "EXCRETORY"}, GENERIC, "DELAYED", "high"),
        ({"series_description": "corticomedullary"}, GENERIC, "ART", "high"),
        ({"series_description": "delayed", "study_description": "x"}, CCRCC, "EP", "high"),
        ({"series_description": "PORTAL VENOUS", "body_part": "ABDOMEN"}, CCRCC, "NP", "high"),
        ({"series_description": "PORTAL VENOUS", "body_part": "ABDOMEN"}, GENERIC, "PV", "high"),
        ({"series_description": "ARTERIAL"}, CCRCC, "UNK", "low"),  # compound guess (ANZ-06)
        ({"series_description": "ABDOMEN 3MM"}, CCRCC, "UNK", "unknown"),
    ],
)
def test_phase_text(fields: dict[str, Any], vocab: list[str], value: str, confidence: str) -> None:
    [a] = phase.analyze([row(**fields)], {"phase_vocabulary": vocab})
    assert (a["value"], a["confidence"]) == (value, confidence)
    assert a["field"] == "phase" and a["key"] == "c.01.complete.-"
    assert a["rules_version"] == phase.RULES_VERSION and a["evidence"]


def timing(start: str, acq: str, **kw: Any) -> dict[str, Any]:
    return row(contrast_start_time=start, acquisition_time=acq, contrast_agent="IOMERON", **kw)


def test_phase_timing_and_conflicts() -> None:
    [nph] = phase.analyze([timing("100000", "100140")], {"phase_vocabulary": CCRCC})
    assert (nph["value"], nph["confidence"]) == ("NP", "medium") and "delay 100 s" in nph[
        "evidence"
    ]
    [ex] = phase.analyze([timing("100000", "100500")], {"phase_vocabulary": CCRCC})
    assert ex["value"] == "EP"
    [cmp_weak] = phase.analyze([timing("100000", "100032")], {"phase_vocabulary": CCRCC})
    assert (cmp_weak["value"], cmp_weak["confidence"]) == ("UNK", "low")
    [conflict] = phase.analyze(
        [timing("100000", "100140", series_description="NON CONTRAST")], {"phase_vocabulary": CCRCC}
    )
    assert conflict["value"] == "UNK" and "conflict" in conflict["evidence"]
    [agree] = phase.analyze(
        [timing("100000", "100140", series_description="NEPHROGRAPHIC")],
        {"phase_vocabulary": CCRCC},
    )
    assert (agree["value"], agree["confidence"]) == ("NP", "high")
    [mr] = phase.analyze([timing("100000", "100140", modality="MR")], {"phase_vocabulary": CCRCC})
    assert mr["value"] == "UNK" and mr["evidence"] == "contrast without phase evidence"
    # midnight crossing within 6 h counts; a negative delay beyond that is ignored
    [mid] = phase.analyze([timing("235930", "000110")], {"phase_vocabulary": CCRCC})
    assert mid["value"] == "NP"


def test_phase_open_vocabulary_keeps_canonical() -> None:
    [a] = phase.analyze([row(series_description="nephrographic")], {"phase_vocabulary": []})
    assert a["value"] == "NP"


@pytest.mark.parametrize(
    ("profile", "fields", "level"),
    [
        ("generic", {}, "strong"),
        ("kidneys", {"study_description": "CT RENAL MASS"}, "strong"),
        ("kidneys", {"body_part": "ABDOMEN"}, "compatible"),
        ("kidneys", {"series_description": "HEAD WO"}, "excluded"),
        ("kidneys", {"series_description": "misc"}, "none"),
        ("kidneys", {}, "none"),
        ("pancreas", {"body_part": "CHEST"}, "weak"),
        ("lung", {"series_description": "HRCT"}, "strong"),
    ],
)
def test_target_profiles(profile: str, fields: dict[str, Any], level: str) -> None:
    [a] = target.analyze([row(**fields)], {"target_profile": profile})
    assert a["field"] == "target_match" and a["value"] == level
    assert a["confidence"] == target.CONFIDENCE[level]


def test_unknown_profile_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown target profile"):
        target.analyze([row()], {"target_profile": "liver"})


AXIAL = {"dicom_category": "ORIGINAL", "scan_type": "AXIAL", "num_slices": "120"}


@pytest.mark.parametrize(
    ("fields", "role", "reason"),
    [
        (AXIAL, "PRIMARY", "original axial"),
        ({**AXIAL, "image_type": "ORIGINAL\\PRIMARY\\LOCALIZER"}, "EXCLUDED", "localizer"),
        ({**AXIAL, "series_description": "CT BIOPSY"}, "EXCLUDED", "intervention_scan"),
        ({**AXIAL, "num_slices": "3"}, "EXCLUDED", "insufficient_slices"),
        ({**AXIAL, "scan_type": "CORONAL"}, "SECONDARY", "coronal"),
        ({**AXIAL, "dicom_category": "DERIVED"}, "SECONDARY", "axial"),
        ({**AXIAL, "modality": "US"}, "EXCLUDED", "wrong_modality"),
    ],
)
def test_output_role(fields: dict[str, Any], role: str, reason: str) -> None:
    anns = readiness.analyze([row(**fields)], {"target_profile": "generic"})
    by = {a["field"]: a for a in anns}
    assert by["output_role"]["value"] == role
    assert reason in by["output_role"]["evidence"]


@pytest.mark.parametrize(
    ("fields", "value", "evidence"),
    [
        ({"spacing_x": "0.8", "spacing_y": "0.8", "spacing_z": "0.8"}, "ready", "no issues"),
        (
            {"spacing_x": "0.7", "spacing_y": "0.7", "spacing_z": "5"},
            "ready_with_warning",
            "anisotropic_spacing",
        ),
        ({"geometry_warning_codes": "LARGE_SLICE_GAP"}, "review_required", "LARGE_SLICE_GAP"),
        (
            {"geometry_warning_codes": "POSSIBLE_MULTIPLE_STACKS;LARGE_SLICE_GAP"},
            "unsuitable",
            "POSSIBLE_MULTIPLE_STACKS",
        ),
        ({"status": "failed"}, "unsuitable", "conversion_failed"),
        (
            {"modality": "MR", "mri_component_status": "heterogeneous"},
            "review_required",
            "mri_component_heterogeneous",
        ),
    ],
)
def test_readiness(fields: dict[str, Any], value: str, evidence: str) -> None:
    anns = readiness.analyze([row(**fields)], {})
    ready = next(a for a in anns if a["field"] == "readiness")
    assert ready["value"] == value and evidence in ready["evidence"]


def test_deterministic_and_keyed_in_converter_mode() -> None:
    rows = [{"case_identity_key": "P1", "series_uid": "1.2", "series_description": "NC"}]
    a = phase.analyze(rows, {"phase_vocabulary": CCRCC})
    assert a == phase.analyze(rows, {"phase_vocabulary": CCRCC}) and a[0]["key"] == "P1|1.2"
