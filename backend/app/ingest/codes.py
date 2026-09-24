"""QC warning codes (contract: docs/domain/INPUT_METADATA.md §QC warning codes, IMP-08)."""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class QcCode(StrEnum):
    MISSING_PATH = "missing_path"
    UNREADABLE_FILE = "unreadable_file"
    OUTSIDE_ROOT = "outside_root"
    MISSING_SEG = "missing_seg"
    MISSING_VOI_IMAGE = "missing_voi_image"
    MISSING_VOI_MASK = "missing_voi_mask"
    MISSING_AFFINE = "missing_affine"
    AFFINE_MISMATCH = "affine_mismatch"
    SHAPE_MISMATCH = "shape_mismatch"
    AMBIGUOUS_PHASE = "ambiguous_phase"
    AMBIGUOUS_SIDE = "ambiguous_side"
    DUPLICATE_ROW_IDENTITY = "duplicate_row_identity"
    FINGERPRINT_CHANGED = "fingerprint_changed"
    UNSUPPORTED_FORMAT = "unsupported_format"
    AMBIGUOUS_AXIS_ORDER = "ambiguous_axis_order"


SEVERITY: dict[QcCode, Severity] = {
    QcCode.MISSING_PATH: Severity.ERROR,
    QcCode.UNREADABLE_FILE: Severity.ERROR,
    QcCode.OUTSIDE_ROOT: Severity.ERROR,
    QcCode.MISSING_SEG: Severity.WARNING,
    QcCode.MISSING_VOI_IMAGE: Severity.WARNING,
    QcCode.MISSING_VOI_MASK: Severity.WARNING,
    QcCode.MISSING_AFFINE: Severity.WARNING,
    QcCode.AFFINE_MISMATCH: Severity.ERROR,
    QcCode.SHAPE_MISMATCH: Severity.ERROR,
    QcCode.AMBIGUOUS_PHASE: Severity.WARNING,
    QcCode.AMBIGUOUS_SIDE: Severity.WARNING,
    QcCode.DUPLICATE_ROW_IDENTITY: Severity.ERROR,
    QcCode.FINGERPRINT_CHANGED: Severity.WARNING,
    QcCode.UNSUPPORTED_FORMAT: Severity.INFO,
    QcCode.AMBIGUOUS_AXIS_ORDER: Severity.ERROR,
}
