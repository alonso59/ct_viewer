from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Region = Literal["kidney", "lung", "liver", "pancreas", "stomach", "heart", "custom"]
Size3 = list[float]


class VoiRegion(BaseModel):
    id: Region
    lateral: bool
    max_components: int
    min_volume_ml: float
    organ: list[str]  # one of these must be in the project unless labels are chosen
    labels: list[str]
    protect: list[str]
    margin_mm: float
    min_size_mm: Size3


class VoiRequest(BaseModel):
    seg_id: str | None = None  # default: the project's default set
    region: Region = "kidney"
    labels: list[str] = Field(default_factory=list)  # empty: the region's labels
    margin_mm: float | None = Field(default=None, ge=0, le=100)
    min_size_mm: Size3 | None = Field(default=None, min_length=3, max_length=3)


class VoiCandidate(BaseModel):
    id: str  # the side (L, R) or V1 when the region has no laterality
    side: Literal["L", "R", ""]
    voxels: int
    volume_ml: float
    centroid_mm: list[float]  # RAS world coordinates
    tight: list[list[int]]  # [start, stop) on the RAS grid
    crop: list[list[int]]
    tight_size_mm: Size3  # x (right-left), y (anterior-posterior), z (superior-inferior)
    crop_size_mm: Size3
    z_mid: int
    warnings: list[str]
    label_ml: dict[str, float]  # label name → mL inside the label box
    # sides: verified (labels or anatomy agree) | probable (coordinates only) | uncertain; "" = none
    confidence: Literal["verified", "probable", "uncertain", ""] = ""
    preview: str  # token for the axial preview


class VoiCandidates(BaseModel):
    item_id: str
    seg_id: str
    region: Region
    lateral: bool
    labels: list[str]
    missing_labels: list[str]
    margin_mm: float
    min_size_mm: Size3
    shape: list[int] = Field(default_factory=list)
    spacing_mm: list[float] = Field(default_factory=list)
    candidates: list[VoiCandidate]


class VoiResult(BaseModel):
    n: int  # row in the run's catalog; addresses the preview
    item_id: str
    case_id: str | None = None
    side: str  # L, R or "" (no laterality)
    candidate: str
    side_swapped: bool = False
    region: str
    labels: list[str]
    image: str  # relative to the run's output folder
    mask: str
    shape: list[int]
    spacing: list[float]
    crop_size_mm: Size3
    volume_ml: float
    warnings: list[str]
    side_confidence: str = ""  # as for a candidate, or `reviewer` when the reviewer swapped it


class VoiScanRow(BaseModel):
    """One scan of a run with all its written VOIs."""

    item_id: str
    case_id: str | None = None
    phase: str | None = None
    vois: list[VoiResult]


class VoiCaseRow(BaseModel):
    """One case of a run, counted over the VOIs that match the filters."""

    case_id: str
    n_scans: int
    n_vois: int
    n_review: int  # VOIs with an uncertain side or a warning


class VoiSummary(BaseModel):
    """The whole run, whatever the filters."""

    n_cases: int
    n_scans: int
    n_vois: int
    by_confidence: dict[str, int]  # lateral VOIs: verified, probable, uncertain, reviewer
    n_warnings: int
    n_review: int


class VoiRunResults(BaseModel):
    run_id: str
    status: str
    reviewer: str | None = None
    finished_at: str | None = None
    output_dir: str | None = None  # absolute; where the files are
    settings: dict[str, Any]
    summary: VoiSummary
    view: Literal["scans", "cases"]
    total: int  # rows of the filtered view
    offset: int
    limit: int
    scans: list[VoiScanRow]  # a page, when view is `scans`
    cases: list[VoiCaseRow]  # a page, when view is `cases`
