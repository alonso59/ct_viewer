from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


class DatasetSummary(BaseModel):
    dataset_id: str
    patient_count: int = 0
    has_nifti: bool = False
    has_seg: bool = False
    has_voi: bool = False
    has_metadata: bool = False
    has_voi_catalog: bool = False


class PatientSummary(BaseModel):
    patient_id: str
    source_patient_id: str | None = None
    group: str | None = None
    phases: list[str] = Field(default_factory=list)
    series_count: int = 0
    seg_count: int = 0
    voi_count: int = 0
    has_deleted: bool = False
    deleted_series_count: int = 0


class SeriesInfo(BaseModel):
    series_id: str
    patient_id: str
    type: str
    case_id: str | None = None
    scan_idx: str | None = None
    voi_id: str | None = None
    group: str | None = None
    phase: str | None = None
    phase_source: str | None = None
    laterality: str | None = None
    side: str | None = None
    filename: str
    image_path: str | None = None
    mask_path: str | None = None
    has_seg: bool = False
    deleted: bool = False
    storage_path: str | None = None


@dataclass(frozen=True)
class SeriesSource:
    series_id: str
    patient_id: str
    type: str
    case_id: str | None
    scan_idx: str | None
    voi_id: str | None
    group: str | None
    phase: str | None
    phase_source: str | None
    laterality: str | None
    side: str | None
    filename: str
    image_path: str
    mask_path: str | None
    has_seg: bool
    deleted: bool
    storage_path: str | None


class VolumeWarning(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"


class VolumeGeometry(BaseModel):
    dimensions: list[int] = Field(default_factory=list)
    spacing: list[float] = Field(default_factory=list)
    origin: list[float] = Field(default_factory=list)
    direction: list[list[float]] = Field(default_factory=list)
    index_to_world: list[list[float]] | None = None
    dtype: str
    byte_order: str
    scalar_range: list[float] = Field(default_factory=list)


class SegmentationMetadata(BaseModel):
    source_format: str
    source_path: str
    source_fingerprint: str
    geometry: VolumeGeometry
    labels: list[int] = Field(default_factory=list)


class GeometryValidation(BaseModel):
    status: Literal["aligned", "mismatch", "not_applicable"]
    tolerance_mm: float
    shape_matches: bool
    affine_matches: bool | None = None
    cornerstone_compatible: bool
    warnings: list[VolumeWarning] = Field(default_factory=list)


class VolumeMetadata(BaseModel):
    source_type: str
    source_format: str
    source_path: str
    source_fingerprint: str
    geometry_fingerprint: str
    fingerprint: str
    geometry: VolumeGeometry
    segmentation: SegmentationMetadata | None = None
    alignment: GeometryValidation
    warnings: list[VolumeWarning] = Field(default_factory=list)


class VolumeInfo(BaseModel):
    series_id: str
    load_handle: str
    shape: list[int] = Field(default_factory=list)
    spacing: list[float] = Field(default_factory=list)
    has_mask: bool = False
    labels: list[int] = Field(default_factory=list)
    warnings: list[VolumeWarning] = Field(default_factory=list)
    metadata: VolumeMetadata | None = None
