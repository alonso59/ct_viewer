"""`workspace.json` and `project.json` schemas (PROJECT_FORMAT.md, format_version 3)."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.paths import validate_alias
from app.projects.presets import UNKNOWN_PHASE

FORMAT: Final = "radiology-workbench-project"
FORMAT_VERSION = 3
SEG_ID_RE = r"^[a-z0-9][a-z0-9_-]{0,63}$"
IMPORTED_SEG: Final = "imported"
DERIVED_ALIAS: Final = "DERIVED"

RootRole = Literal["source", "derived"]


class PathRoot(BaseModel):
    alias: str
    path: str  # absolute server path
    role: RootRole = "source"  # ADR-0014; `derived` roots are written only by task runs

    @field_validator("alias")
    @classmethod
    def _alias(cls, v: str) -> str:
        return validate_alias(v)


class LabelEntry(BaseModel):
    value: int = Field(ge=0, le=65535)
    name: str
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    opacity: float = Field(ge=0.0, le=1.0)
    visible: bool = True


Modality = Literal["CT", "MR", "mixed"]
Layout = Literal[
    "four-up",
    "conventional",
    "three-mpr",
    "one-up-axial",
    "one-up-sagittal",
    "one-up-coronal",
    "one-up-3d",
]


class WindowLevel(BaseModel):
    ww: float = Field(gt=0)
    wl: float


class WlPreset(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    ww: float = Field(gt=0)
    wl: float


def _default_wl() -> dict[str, WindowLevel | Literal["percentile"]]:
    return {"CT": WindowLevel(ww=400, wl=50), "MR": "percentile"}


class Display(BaseModel):
    """`project.json.display` (PRJ-18, VW-25); was `viewer_defaults` before format 3."""

    layout: Layout = "four-up"
    # Initial window per modality: HU numbers, or `percentile` (1st-99th, VW-05).
    wl: dict[str, WindowLevel | Literal["percentile"]] = Field(default_factory=_default_wl)
    use_dicom_window: bool = True  # the DICOM `WindowCenter/Width` first when present (VW-22)
    wl_presets: list[WlPreset] | None = None  # null = the built-in presets (VW-05)
    interpolation: Literal["linear", "nearest"] = "linear"
    convention: Literal["radiological", "neurological"] = "radiological"

    def ct_window(self) -> tuple[float, float]:
        w = self.wl.get("CT")
        return (w.ww, w.wl) if isinstance(w, WindowLevel) else (400.0, 50.0)


class SegProducer(BaseModel):
    """The task run that produced a segmentation set (ADR-0015)."""

    task_id: str
    version: str
    run_id: str
    settings_hash: str | None = None


class SegmentationSet(BaseModel):
    """`project.json.segmentations[]` (ADR-0015): one mask per item, per set."""

    seg_id: str = Field(pattern=SEG_ID_RE)
    name: str = ""  # display name; empty = seg_id (API-27 rename)
    kind: Literal["imported", "task", "manual"] = "imported"
    producer: SegProducer | None = None
    # Set value (as a string key) → project label value (PRJ-07).
    label_mapping: dict[str, int] = Field(default_factory=dict)
    # Set values auto-named `label_{value}` at registration, flagged for review (ADR-0015 §4).
    unmatched: list[int] = Field(default_factory=list)
    created_at: str = ""


def imported_set(label_map: list[LabelEntry], created_at: str) -> SegmentationSet:
    """The `imported` set with the identity mapping over the label map (PRJ-11 migration)."""
    return SegmentationSet(
        seg_id=IMPORTED_SEG,
        kind="imported",
        label_mapping={str(e.value): e.value for e in label_map},
        created_at=created_at,
    )


class ProjectConfig(BaseModel):
    """`project.json` (source of truth for config)."""

    format: Literal["radiology-workbench-project"] = FORMAT
    format_version: int = FORMAT_VERSION
    project_id: str
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    created_at: str
    updated_at: str
    path_roots: list[PathRoot] = Field(default_factory=list)
    # Neutral by default (PRJ-14): no labels (auto-named from masks, PRJ-07), raw phases.
    label_map: list[LabelEntry] = Field(default_factory=list)
    default_modality: Modality = "CT"  # PRJ-14: viewer default for items without one (VW-05)
    packs: list[str] = Field(default_factory=list)  # applied study packs (PRJ-16)
    view_token: str | None = None  # PRJ-17
    phase_vocabulary: list[str] = Field(default_factory=list)
    # RAW (upper-case) -> canonical; see INPUT_METADATA.md §Phase resolution.
    phase_mapping: dict[str, str] = Field(default_factory=dict)
    phase_priority: list[str] = Field(default_factory=lambda: [UNKNOWN_PHASE])
    display: Display = Field(default_factory=Display)
    segmentations: list[SegmentationSet] = Field(default_factory=list)  # ADR-0015
    default_seg: str = IMPORTED_SEG
    # Active analyzer run per field (ANZ-04); null = none active.
    annotation_sources: dict[str, str | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _segmentations(self) -> ProjectConfig:
        if not self.segmentations:
            self.segmentations = [imported_set(self.label_map, self.created_at)]
        ids = [s.seg_id for s in self.segmentations]
        if len(set(ids)) != len(ids):
            raise ValueError("segmentations: duplicate seg_id")
        if self.default_seg not in ids:
            raise ValueError(f"default_seg {self.default_seg!r} is not a segmentation set")
        if sum(1 for r in self.path_roots if r.role == "derived") > 1:
            raise ValueError("path_roots: at most one derived root (PRJ-13)")
        return self

    def derived_root(self) -> PathRoot | None:
        """PRJ-13: the project's single `derived` root, if registered."""
        return next((r for r in self.path_roots if r.role == "derived"), None)

    def segmentation(self, seg_id: str) -> SegmentationSet | None:
        return next((s for s in self.segmentations if s.seg_id == seg_id), None)


class ProjectPatch(BaseModel):
    """API-03 PATCH body: only provided fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    label_map: list[LabelEntry] | None = None
    phase_vocabulary: list[str] | None = None  # applies at the next import (re-index)
    phase_mapping: dict[str, str] | None = None
    phase_priority: list[str] | None = None
    default_modality: Modality | None = None  # PRJ-14
    display: Display | None = None  # PRJ-18
    default_seg: str | None = None  # must name an existing segmentation set (ADR-0015)


class WorkspaceEntry(BaseModel):
    project_id: str
    name: str
    created_at: str
    last_opened_at: str | None = None
    archived: bool = False


class ProjectSummary(BaseModel):
    """PRJ-02 workspace home row."""

    project_id: str
    name: str
    created_at: str
    last_opened_at: str | None = None
    archived: bool = False
    n_cases: int = 0  # cases with an item not excluded upstream (AUD-A2-08)
    n_cases_excluded: int = 0  # cases whose every item is excluded upstream
    curation_progress: float = 0.0  # 0..1; filled by curation (lane P4)
    share_url: str  # PRJ-03


class ProjectDetail(ProjectConfig):
    """API-03 response: project.json + share link (PRJ-03) + the `ETag` value (PRJ-15)."""

    share_url: str
    etag: str
    # PRJ-17: the view-only link when a token exists; true on the read-only mirror (API-60).
    view_url: str | None = None
    read_only: bool = False


class RootInfo(BaseModel):
    """API-05 alias row."""

    alias: str
    path: str
    exists: bool
    role: RootRole = "source"
