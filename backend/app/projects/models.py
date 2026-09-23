"""`workspace.json` and `project.json` schemas (PROJECT_FORMAT.md, format_version 1)."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.paths import validate_alias

FORMAT: Final = "radiology-workbench-project"
FORMAT_VERSION = 1


class PathRoot(BaseModel):
    alias: str
    path: str  # absolute server path

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


class ViewerDefaults(BaseModel):
    ww: float = 400
    wl: float = 50
    layout: str = "four-up"


DEFAULT_LABEL_MAP = [  # PRJ-07 ccRCC seed
    LabelEntry(value=1, name="kidney", color="#00FFFF", opacity=0.15, visible=True),
    LabelEntry(value=2, name="tumor", color="#FFFF00", opacity=0.20, visible=True),
    LabelEntry(value=3, name="cyst", color="#FF00FF", opacity=0.15, visible=False),
]
DEFAULT_PHASE_VOCABULARY = ["NC", "CMP", "NP", "EP", "UNK"]
DEFAULT_PHASE_PRIORITY = ["NP", "CMP", "NC", "EP", "UNK"]


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
    label_map: list[LabelEntry] = Field(default_factory=lambda: list(DEFAULT_LABEL_MAP))
    phase_vocabulary: list[str] = Field(default_factory=lambda: list(DEFAULT_PHASE_VOCABULARY))
    phase_priority: list[str] = Field(default_factory=lambda: list(DEFAULT_PHASE_PRIORITY))
    viewer_defaults: ViewerDefaults = Field(default_factory=ViewerDefaults)


class ProjectPatch(BaseModel):
    """API-03 PATCH body: only provided fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    label_map: list[LabelEntry] | None = None
    phase_priority: list[str] | None = None
    viewer_defaults: ViewerDefaults | None = None


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
    n_cases: int = 0
    curation_progress: float = 0.0  # 0..1; filled by curation (lane P4)
    share_url: str  # PRJ-03


class ProjectDetail(ProjectConfig):
    """API-03 response: project.json + share link (PRJ-03)."""

    share_url: str


class RootInfo(BaseModel):
    """API-05 alias row."""

    alias: str
    path: str
    exists: bool
