"""Field knowledge that is *not* study-specific.

`CONVERTER_FIELDS` is the known v2 converter/preprocessor output schema (DICOM-derived and
technical columns). Any metadata field outside it and outside the core is a **Study**
variable, which is how study labels surface without the app knowing their names.
"""

from __future__ import annotations

import re
from typing import Final

from app.variables.models import Category, ExcludeReason

# Identity, paths and phase-resolution inputs: fixed meaning, never variables.
# The resolved phase is an item attribute with its own filter.
CORE_FIELDS: Final = frozenset(
    {
        "case_id", "scan_idx", "filename", "relative_path", "nifti_file", "seg_path",
        "image_path", "mask_path", "side", "phase", "curated_phase", "canonical_phase",
    }
)  # fmt: skip
# Columns of `index/variables.parquet` that come from the item itself.
BASE_COLUMNS: Final = ("item_id", "case_id", "scan_idx", "scope", "side", "phase")
RESERVED_NAMES: Final = frozenset(BASE_COLUMNS) | CORE_FIELDS

CONVERTER_FIELDS: Final = frozenset(
    {
        "acquisition_date", "acquisition_number", "acquisition_time", "advanced_dicom_status",
        "advanced_dicom_warning_codes", "analysis_readiness", "analysis_readiness_reasons",
        "bits_allocated", "bits_stored", "body_part", "case_index", "content_date",
        "content_time", "contrast_agent", "contrast_delay_seconds", "contrast_delay_source",
        "contrast_flow_duration", "contrast_flow_rate", "contrast_route", "contrast_start_time",
        "contrast_stop_time", "contrast_total_dose", "contrast_volume", "conversion_date",
        "convolution_kernel", "ct_intensity_semantics", "ct_intensity_status",
        "ct_intensity_warnings", "curated_keep", "curated_quality", "curated_role",
        "dataset_id", "days_from_first_scan", "dicom_category", "dicom_dir",
        "diffusion_indicators", "dim_x", "dim_y", "dim_z", "direction", "echo_indicators",
        "echo_time", "exclude_reason", "exposure", "exposure_time", "first_file", "flip_angle",
        "geometry_status", "geometry_warning_codes", "has_per_frame_functional_groups",
        "has_shared_functional_groups", "high_bit", "image_orientation", "image_type",
        "include_guess", "instance_creation_date", "instance_creation_time", "institution",
        "kvp", "longitudinal_temporal_information_modified", "magnetic_field_strength",
        "manufacturer", "manufacturer_model", "maximum_spacing_deviation", "modality",
        "mr_acquisition_type", "mri_component_confidence", "mri_component_conflict",
        "mri_component_status", "mri_image_component", "mri_image_component_source",
        "nominal_slice_spacing", "notes", "num_slices", "number_of_frames",
        "observed_mri_components", "origin_x", "origin_y", "origin_z", "output_role",
        "patient_folder", "patient_id", "phase_guess", "phase_guess_confidence",
        "phase_guess_conflict", "phase_guess_evidence", "pixel_representation", "pixel_type",
        "planned_conversion", "protocol_name", "raw_metadata", "raw_metadata_error",
        "reconstruction_diameter", "repetition_time", "rescale_intercept", "rescale_slope",
        "rescale_type", "scan_date", "scan_date_folder", "scan_datetime",
        "scan_datetime_source", "scan_options", "scan_time", "scan_type", "scanning_sequence",
        "sequence_name", "sequence_variant", "series_date", "series_description",
        "series_index_in_study", "series_number", "series_time", "series_uid", "skip_reason",
        "slice_thickness", "sop_class_name", "sop_class_uid", "spacing", "spacing_between_slices",
        "spacing_quality", "spacing_x", "spacing_y", "spacing_z", "status", "study_date",
        "study_description", "study_index", "study_time", "study_uid", "target_match_level",
        "target_match_reason", "target_match_term", "temporal_indicators", "validation",
        "voi_id", "window_center", "window_width", "xray_tube_current",
    }
)  # fmt: skip
# v2 web UI bookkeeping columns written back into metadata.jsonl.
CONVERTER_PREFIXES: Final = ("webui_",)

# Default `confounder` tag.
DEFAULT_CONFOUNDERS: Final = frozenset(
    {
        "manufacturer", "manufacturer_model", "convolution_kernel", "kvp", "slice_thickness",
        "spacing_z", "contrast_agent", "modality",
    }
)  # fmt: skip
SENSITIVE_FIELDS: Final = frozenset({"patient_id"})  # plus every `date` variable

# raw_metadata tags flattened into variables; everything else in the blob is ignored.
RAW_ALLOWLIST: Final = {"PatientSex": "patient_sex", "PatientAge": "patient_age"}

# Fixed field → category for every converter field (one entry per name) and the raw
# allowlist, grouped by category. A field's category is read from here, never inferred.
CATEGORY_BY_FIELD: Final[dict[str, Category]] = {
    # Patient
    "patient_id": "patient",
    "patient_folder": "patient",
    "patient_sex": "patient",
    "patient_age": "patient",
    # Study
    "study_description": "study",
    "study_index": "study",
    "study_uid": "study",
    # Series (incl. the ImageType tag and its parsed indicators)
    "acquisition_number": "series",
    "body_part": "series",
    "dicom_category": "series",
    "diffusion_indicators": "series",
    "echo_indicators": "series",
    "image_type": "series",
    "modality": "series",
    "protocol_name": "series",
    "scan_type": "series",
    "series_description": "series",
    "series_index_in_study": "series",
    "series_number": "series",
    "series_uid": "series",
    "sop_class_name": "series",
    "sop_class_uid": "series",
    "temporal_indicators": "series",
    # Equipment
    "institution": "equipment",
    "manufacturer": "equipment",
    "manufacturer_model": "equipment",
    # Technique (CT and MR acquisition parameters)
    "convolution_kernel": "technique",
    "echo_time": "technique",
    "exposure": "technique",
    "exposure_time": "technique",
    "flip_angle": "technique",
    "has_per_frame_functional_groups": "technique",
    "has_shared_functional_groups": "technique",
    "kvp": "technique",
    "magnetic_field_strength": "technique",
    "mr_acquisition_type": "technique",
    "mri_component_confidence": "technique",
    "mri_component_conflict": "technique",
    "mri_component_status": "technique",
    "mri_image_component": "technique",
    "observed_mri_components": "technique",
    "repetition_time": "technique",
    "scanning_sequence": "technique",
    "scan_options": "technique",
    "sequence_name": "technique",
    "sequence_variant": "technique",
    "xray_tube_current": "technique",
    # Contrast
    "contrast_agent": "contrast",
    "contrast_delay_seconds": "contrast",
    "contrast_flow_duration": "contrast",
    "contrast_flow_rate": "contrast",
    "contrast_route": "contrast",
    "contrast_start_time": "contrast",
    "contrast_stop_time": "contrast",
    "contrast_total_dose": "contrast",
    "contrast_volume": "contrast",
    # Geometry (plane, spacing, dimensions, slices, orientation)
    "dim_x": "geometry",
    "dim_y": "geometry",
    "dim_z": "geometry",
    "direction": "geometry",
    "geometry_status": "geometry",
    "geometry_warning_codes": "geometry",
    "image_orientation": "geometry",
    "maximum_spacing_deviation": "geometry",
    "nominal_slice_spacing": "geometry",
    "num_slices": "geometry",
    "number_of_frames": "geometry",
    "origin_x": "geometry",
    "origin_y": "geometry",
    "origin_z": "geometry",
    "reconstruction_diameter": "geometry",
    "slice_thickness": "geometry",
    "spacing": "geometry",
    "spacing_between_slices": "geometry",
    "spacing_quality": "geometry",
    "spacing_x": "geometry",
    "spacing_y": "geometry",
    "spacing_z": "geometry",
    # Intensity (pixel and CT intensity)
    "bits_allocated": "intensity",
    "bits_stored": "intensity",
    "ct_intensity_semantics": "intensity",
    "ct_intensity_status": "intensity",
    "ct_intensity_warnings": "intensity",
    "high_bit": "intensity",
    "pixel_representation": "intensity",
    "pixel_type": "intensity",
    "rescale_intercept": "intensity",
    "rescale_slope": "intensity",
    "rescale_type": "intensity",
    "window_center": "intensity",
    "window_width": "intensity",
    # Dates & times
    "acquisition_date": "dates",
    "acquisition_time": "dates",
    "content_date": "dates",
    "content_time": "dates",
    "days_from_first_scan": "dates",
    "instance_creation_date": "dates",
    "instance_creation_time": "dates",
    "longitudinal_temporal_information_modified": "dates",
    "scan_date": "dates",
    "scan_datetime": "dates",
    "scan_time": "dates",
    "series_date": "dates",
    "series_time": "dates",
    "study_date": "dates",
    "study_time": "dates",
    # Phase & readiness (converter selection, readiness, target match, output role)
    "analysis_readiness": "phase_readiness",
    "analysis_readiness_reasons": "phase_readiness",
    "curated_role": "phase_readiness",
    "exclude_reason": "phase_readiness",
    "include_guess": "phase_readiness",
    "output_role": "phase_readiness",
    "phase_guess": "phase_readiness",
    "phase_guess_confidence": "phase_readiness",
    "phase_guess_conflict": "phase_readiness",
    "phase_guess_evidence": "phase_readiness",
    "skip_reason": "phase_readiness",
    "target_match_level": "phase_readiness",
    "target_match_reason": "phase_readiness",
    "target_match_term": "phase_readiness",
    # Provenance (converter bookkeeping, sources and paths)
    "advanced_dicom_status": "provenance",
    "advanced_dicom_warning_codes": "provenance",
    "case_index": "provenance",
    "contrast_delay_source": "provenance",
    "conversion_date": "provenance",
    "curated_keep": "provenance",
    "curated_quality": "provenance",
    "dataset_id": "provenance",
    "dicom_dir": "provenance",
    "first_file": "provenance",
    "mri_image_component_source": "provenance",
    "notes": "provenance",
    "planned_conversion": "provenance",
    "raw_metadata": "provenance",
    "raw_metadata_error": "provenance",
    "scan_date_folder": "provenance",
    "scan_datetime_source": "provenance",
    "status": "provenance",
    "validation": "provenance",
    "voi_id": "provenance",
}


def field_category(name: str) -> Category:
    """Category of a metadata/raw field: the fixed map, `webui_*` bookkeeping, else the
    study `dataset` fields that fall outside the converter schema."""
    cat = CATEGORY_BY_FIELD.get(name)
    if cat is not None:
        return cat
    return "provenance" if name.startswith("webui_") else "dataset"


UID_VALUE = re.compile(r"^\d+(\.\d+){3,}$")
ABS_PATH_VALUE = re.compile(r"^(/|[A-Za-z]:[\\/]|\\\\)")


def is_converter_field(name: str) -> bool:
    return name in CONVERTER_FIELDS or name.startswith(CONVERTER_PREFIXES)


def name_exclusion(name: str) -> ExcludeReason | None:
    """Exclusion by field name: UIDs and accession numbers."""
    low = name.lower()
    if low == "uid" or low.endswith("_uid"):
        return "uid"
    if "accession" in low:
        return "accession"
    return None
