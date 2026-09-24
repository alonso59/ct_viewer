"""`analyzer.readiness` (ANZ-*): output role (PRIMARY/SECONDARY/EXCLUDED) and analysis readiness.

Localizer/scout and intervention → EXCLUDED; unsafe geometry (DCM-03) → `unsuitable` or
`review_required` with the codes as evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from plugins.analyzers import Annotation, annotation, row_key
from plugins.analyzers import target as target_rules
from plugins.text import geometry_codes, int_or_none, value_to_text

RULES_VERSION = "readiness-1"
UNSUITABLE = {
    "DUPLICATE_SLICE_POSITION",
    "ORIENTATION_CONFLICT",
    "IN_PLANE_SPACING_CONFLICT",
    "MATRIX_SIZE_CONFLICT",
    "POSSIBLE_MULTIPLE_STACKS",
}
REVIEW = {"IRREGULAR_SLICE_SPACING", "LARGE_SLICE_GAP"}
UNSAFE = UNSUITABLE | REVIEW


def _text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    return " ".join(value_to_text(row.get(k, "")) for k in keys).upper()


def is_localizer(row: dict[str, Any]) -> bool:
    t = _text(row, ("image_type", "study_description", "series_description", "protocol_name"))
    return any(k in t for k in ("LOCALIZER", "SCOUT", "TOPOGRAM", "SURVIEW"))


def is_intervention(row: dict[str, Any]) -> bool:
    t = _text(row, ("study_description", "series_description", "protocol_name"))
    return any(
        k in t
        for k in (
            "PUNCTURE",
            "BIOPSY",
            "DRAIN",
            "INTERVENTION",
            "ABLATION",
            "DRAINAGE",
            "ASPIRATION",
        )
    )


def output_role(row: dict[str, Any], target_level: str) -> tuple[str, str]:
    """(PRIMARY | SECONDARY | EXCLUDED, reason). `num_slices` < 10 is excluded (legacy rule)."""
    modality = value_to_text(row.get("modality", "")).upper()
    if modality not in {"CT", "MR", "MRI"}:
        return "EXCLUDED", "wrong_modality"
    if is_localizer(row):
        return "EXCLUDED", "localizer"
    n = int_or_none(row.get("num_slices", ""))
    if n is not None and n < 10:
        return "EXCLUDED", "insufficient_slices"
    if is_intervention(row):
        return "EXCLUDED", "intervention_scan"
    if target_level == "excluded":
        return "EXCLUDED", "wrong_anatomy"
    category = value_to_text(row.get("dicom_category", ""))
    scan_type = value_to_text(row.get("scan_type", ""))
    if scan_type in {"CORONAL", "SAGITTAL", "OBLIQUE"} or category in {"DERIVED", "RECONSTRUCTION"}:
        return "SECONDARY", f"{scan_type or category}".lower()
    if category == "ORIGINAL" and scan_type == "AXIAL":
        if target_level in {"none", "weak"}:
            return "SECONDARY", f"target {target_level}"
        return "PRIMARY", "original axial"
    return "SECONDARY", "not original axial"


def readiness(row: dict[str, Any]) -> tuple[str, list[str]]:
    """ready | ready_with_warning | review_required | unsuitable | unknown, with reasons."""
    status = value_to_text(row.get("status", "")) or "converted"
    if status == "failed":
        return "unsuitable", ["conversion_failed"]
    if status not in {"converted", "already_converted", "would_convert"}:
        return "unknown", ["not_converted"]
    codes = geometry_codes(row)
    if codes & UNSUITABLE:
        return "unsuitable", sorted(codes & UNSUITABLE)
    if codes & REVIEW:
        return "review_required", sorted(codes & REVIEW)
    reasons = ["geometry_metadata_missing"] if "GEOMETRY_METADATA_MISSING" in codes else []
    if value_to_text(row.get("modality", "")).upper() in {"MR", "MRI"}:
        st = value_to_text(row.get("mri_component_status", ""))
        if st == "heterogeneous":
            return "review_required", ["mri_component_heterogeneous"]
        if st == "unknown" or value_to_text(row.get("mri_image_component", "")) == "UNKNOWN":
            return "review_required", ["mri_component_unknown"]
    if _anisotropic(row):
        reasons.append("anisotropic_spacing")
    return ("ready_with_warning", reasons) if reasons else ("ready", [])


def _anisotropic(row: dict[str, Any]) -> bool:
    if value_to_text(row.get("geometry_status", "")) not in {"ok", ""}:
        return False
    sp: list[float] = []
    for k in ("spacing_x", "spacing_y", "spacing_z"):
        try:
            v = abs(float(value_to_text(row.get(k, ""))))
        except ValueError:
            return False
        if v <= 0:
            return False
        sp.append(v)
    return max(sp) / min(sp) >= 2.0


def has_unsafe_geometry(row: dict[str, Any]) -> bool:
    return bool(geometry_codes(row) & UNSAFE)


ROLE_CONFIDENCE = {"PRIMARY": "high", "SECONDARY": "medium", "EXCLUDED": "high"}


def analyze(rows: Sequence[dict[str, Any]], config: dict[str, Any]) -> list[Annotation]:
    p = target_rules.profile(config.get("target_profile"))
    out: list[Annotation] = []
    for row in rows:
        key = row_key(row)
        level = value_to_text(row.get("target_match", "")) or target_rules.match(row, p)[0]
        role, reason = output_role(row, level)
        out.append(
            annotation(key, "output_role", role, ROLE_CONFIDENCE[role], reason, RULES_VERSION)
        )
        ready, reasons = readiness(row)
        conf = (
            "high"
            if ready in {"ready", "unsuitable"}
            else "medium"
            if ready != "unknown"
            else "unknown"
        )
        out.append(
            annotation(
                key, "readiness", ready, conf, ", ".join(reasons) or "no issues", RULES_VERSION
            )
        )
    return out
