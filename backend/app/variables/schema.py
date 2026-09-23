"""Field knowledge that is *not* study-specific (VARIABLES.md §Principle, VAR-04/05/08/09).

`CONVERTER_FIELDS` is the known v2 converter/preprocessor output schema (DICOM-derived and
technical columns). Any metadata field outside it and outside the core is a **Study**
variable, which is how study labels surface without the app knowing their names.
"""

from __future__ import annotations

import re
from typing import Final

# Identity, paths and phase-resolution inputs: fixed meaning, never variables
# (INPUT_METADATA.md §Core). The resolved phase is an item attribute with its own filter.
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
# v2 web UI bookkeeping columns written back into metadata.jsonl (legacy metadata_sync).
CONVERTER_PREFIXES: Final = ("webui_",)

# VAR-05 default `confounder` tag.
DEFAULT_CONFOUNDERS: Final = frozenset(
    {
        "manufacturer", "manufacturer_model", "convolution_kernel", "kvp", "slice_thickness",
        "spacing_z", "contrast_agent", "modality",
    }
)  # fmt: skip
SENSITIVE_FIELDS: Final = frozenset({"patient_id"})  # VAR-09 (+ every `date` variable)

# VAR-08: raw_metadata tags flattened into variables; everything else in the blob is ignored.
RAW_ALLOWLIST: Final = {"PatientSex": "patient_sex", "PatientAge": "patient_age"}

UID_VALUE = re.compile(r"^\d+(\.\d+){3,}$")
ABS_PATH_VALUE = re.compile(r"^(/|[A-Za-z]:[\\/]|\\\\)")


def is_converter_field(name: str) -> bool:
    return name in CONVERTER_FIELDS or name.startswith(CONVERTER_PREFIXES)


def name_exclusion(name: str) -> str | None:
    """VAR-09 by field name: UIDs and accession numbers."""
    low = name.lower()
    if low == "uid" or low.endswith("_uid"):
        return "uid"
    if "accession" in low:
        return "accession"
    return None
