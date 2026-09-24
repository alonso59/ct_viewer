"""Header rows (contract v1 + converter extras, DICOM_CONVERTER.md §Row fields).
Ported from `legacy/convert/metadata.py` (row building, scan timing, geometry updates)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from plugins.dicom.scan import Inspection, Series
from plugins.text import (
    combine_date_time,
    int_or_none,
    parse_dicom_date,
    split_multi_value,
    value_to_text,
)

MODALITY_CODES = {"MRI": "MR"}  # DCM-12: DICOM codes


def _t(ds: Any, keyword: str) -> str:
    return value_to_text(getattr(ds, keyword, ""))


def dicom_category(image_type: str) -> str:
    tokens = {t.upper() for t in split_multi_value(image_type)}
    if not tokens:
        return "UNKNOWN"
    if tokens & {"MPR", "MIP", "MINIP", "REFORMAT", "RECON", "RECONSTRUCTION", "PROJECTION"}:
        return "RECONSTRUCTION"
    if tokens & {"DERIVED", "SECONDARY"}:
        return "DERIVED"
    return "ORIGINAL" if "ORIGINAL" in tokens else "UNKNOWN"


def scan_type(orientation: str) -> str:
    v = split_multi_value(orientation)
    if len(v) < 6:
        return "UNKNOWN"
    try:
        r, c = [float(x) for x in v[:3]], [float(x) for x in v[3:6]]
    except ValueError:
        return "UNKNOWN"
    n = [
        abs(r[1] * c[2] - r[2] * c[1]),
        abs(r[2] * c[0] - r[0] * c[2]),
        abs(r[0] * c[1] - r[1] * c[0]),
    ]
    m = max(n)
    if m < 0.8:
        return "OBLIQUE"
    return ("SAGITTAL", "CORONAL", "AXIAL")[n.index(m)]


def header_row(ds: Any, series: Series, patient_folder: str, insp: Inspection) -> dict[str, Any]:
    """One row per series from its first header; `patient_id` falls back to the folder name."""
    image_type = _t(ds, "ImageType")
    orientation = _t(ds, "ImageOrientationPatient")
    spacing = split_multi_value(_t(ds, "PixelSpacing"))
    frames = int_or_none(_t(ds, "NumberOfFrames"))
    n_slices = frames if len(series.files) == 1 and frames and frames > 1 else len(series.files)
    modality = _t(ds, "Modality").strip().upper()
    row: dict[str, Any] = {
        "patient_folder": patient_folder,
        "patient_id": _t(ds, "PatientID") or patient_folder,
        "study_uid": _t(ds, "StudyInstanceUID"),
        "series_uid": _t(ds, "SeriesInstanceUID") or series.series_id,
        "series_number": _t(ds, "SeriesNumber"),
        "acquisition_number": _t(ds, "AcquisitionNumber"),
        "modality": MODALITY_CODES.get(modality, modality),
        "sop_class_uid": _t(ds, "SOPClassUID"),
        "dicom_category": dicom_category(image_type),
        "image_type": image_type,
        "scan_type": scan_type(orientation),
        "body_part": _t(ds, "BodyPartExamined"),
        "study_description": _t(ds, "StudyDescription"),
        "series_description": _t(ds, "SeriesDescription"),
        "protocol_name": _t(ds, "ProtocolName"),
        "manufacturer": _t(ds, "Manufacturer"),
        "manufacturer_model": _t(ds, "ManufacturerModelName"),
        "institution": _t(ds, "InstitutionName"),
        "kvp": _t(ds, "KVP"),
        "xray_tube_current": _t(ds, "XRayTubeCurrent"),
        "exposure": _t(ds, "Exposure"),
        "convolution_kernel": _t(ds, "ConvolutionKernel"),
        "slice_thickness": _t(ds, "SliceThickness"),
        "spacing_between_slices": _t(ds, "SpacingBetweenSlices"),
        "rescale_intercept": _t(ds, "RescaleIntercept"),
        "rescale_slope": _t(ds, "RescaleSlope"),
        "rescale_type": _t(ds, "RescaleType"),
        "repetition_time": _t(ds, "RepetitionTime"),
        "echo_time": _t(ds, "EchoTime"),
        "magnetic_field_strength": _t(ds, "MagneticFieldStrength"),
        "contrast_agent": _t(ds, "ContrastBolusAgent"),
        "contrast_route": _t(ds, "ContrastBolusRoute"),
        "contrast_volume": _t(ds, "ContrastBolusVolume"),
        "contrast_start_time": _t(ds, "ContrastBolusStartTime"),
        "contrast_stop_time": _t(ds, "ContrastBolusStopTime"),
        "contrast_flow_rate": _t(ds, "ContrastFlowRate"),
        "contrast_flow_duration": _t(ds, "ContrastFlowDuration"),
        "study_date": _t(ds, "StudyDate"),
        "study_time": _t(ds, "StudyTime"),
        "series_date": _t(ds, "SeriesDate"),
        "series_time": _t(ds, "SeriesTime"),
        "acquisition_date": _t(ds, "AcquisitionDate"),
        "acquisition_time": _t(ds, "AcquisitionTime"),
        "content_date": _t(ds, "ContentDate"),
        "content_time": _t(ds, "ContentTime"),
        "dim_x": _t(ds, "Columns"),
        "dim_y": _t(ds, "Rows"),
        "dim_z": str(n_slices),
        "num_slices": str(n_slices),
        "spacing_x": spacing[1] if len(spacing) > 1 else "",
        "spacing_y": spacing[0] if spacing else "",
        "image_orientation": orientation,
        "number_of_frames": _t(ds, "NumberOfFrames"),
        "geometry_status": insp.geometry_status,
        "geometry_warning_codes": ";".join(insp.geometry_codes),
        "nominal_slice_spacing": ""
        if insp.nominal_slice_spacing is None
        else str(insp.nominal_slice_spacing),
        "advanced_dicom_status": insp.advanced_status,
        "advanced_dicom_warning_codes": ";".join(insp.advanced_codes),
        "mri_image_component": insp.mri_component,
        "mri_component_status": insp.mri_component_status,
        "source_kind": "dicom",
    }
    row["spacing_z"] = row["spacing_between_slices"] or row["slice_thickness"]
    row["spacing_quality"] = "too_few_slices" if n_slices < 10 else "ok"
    return row


SCAN_TIME_SOURCES = (
    ("acquisition", "acquisition_date", "acquisition_time"),
    ("content", "content_date", "content_time"),
    ("series", "series_date", "series_time"),
    ("study", "study_date", "study_time"),
)


def apply_scan_timing(rows: Sequence[dict[str, Any]]) -> None:
    """Best scan date/time per series, days from the first scan, study order (legacy rules)."""
    for row in rows:
        row.update(
            {"scan_date": "", "scan_time": "", "scan_datetime": "", "scan_datetime_source": ""}
        )
        for source, dk, tk in SCAN_TIME_SOURCES:
            combined = combine_date_time(row.get(dk, ""), row.get(tk, ""))
            if combined:
                row["scan_datetime"], row["scan_datetime_source"] = combined, source
                row["scan_date"] = combined[:10]
                row["scan_time"] = combined.split("T", 1)[1] if "T" in combined else ""
                break
    dates = [d for d in (parse_dicom_date(r.get("scan_date", "")) for r in rows) if d]
    first = min(dates) if dates else None
    studies: dict[str, str] = {}
    for r in rows:
        uid = r.get("study_uid", "")
        if uid:
            key = r.get("scan_datetime") or "9999"
            studies[uid] = min(studies.get(uid, key), key)
    order = {uid: n for n, (_, uid) in enumerate(sorted((v, k) for k, v in studies.items()))}
    for r in rows:
        d = parse_dicom_date(r.get("scan_date", ""))
        r["days_from_first_scan"] = str((d - first).days) if first and d else ""
        r["study_index"] = str(order[r["study_uid"]]) if r.get("study_uid") in order else ""


def series_sort_key(row: dict[str, Any]) -> tuple[str, str, int, str]:
    n = int_or_none(row.get("series_number", ""))
    return (
        value_to_text(row.get("scan_datetime", "")) or "9999",
        value_to_text(row.get("study_uid", "")),
        n if n is not None else 999999,
        value_to_text(row.get("series_uid", "")),
    )


def update_geometry(
    row: dict[str, Any],
    size: Sequence[int],
    spacing: Sequence[float],
    origin: Sequence[float],
    direction: Sequence[float],
    pixel_type: str,
) -> None:
    row["dim_x"], row["dim_y"], row["dim_z"] = (
        str(size[i]) if len(size) > i else "1" for i in range(3)
    )
    row["spacing_x"], row["spacing_y"], row["spacing_z"] = (
        str(spacing[i]) if len(spacing) > i else "" for i in range(3)
    )
    row["origin_x"], row["origin_y"], row["origin_z"] = (
        str(origin[i]) if len(origin) > i else "" for i in range(3)
    )
    row["direction"] = "\\".join(str(v) for v in direction)
    row["pixel_type"] = pixel_type
    row["num_slices"] = row["dim_z"]
    row["spacing_quality"] = "too_few_slices" if int(row["dim_z"]) < 10 else "ok"
