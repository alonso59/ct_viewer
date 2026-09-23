"""`workspace.json` and `project.json` schemas (PROJECT_FORMAT.md, format_version 1)."""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.paths import validate_alias
from app.projects.presets import DEFAULT_PRESET, PRESETS, PresetName

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


def preset_fields(name: PresetName) -> dict[str, Any]:
    """`project.json` fields seeded by a study preset (PRJ-12)."""
    p = PRESETS[name]
    return {
        "preset": name,
        "label_map": [
            LabelEntry(
                value=s.value, name=s.name, color=s.color, opacity=s.opacity, visible=s.visible
            )
            for s in p.label_map
        ],
        "phase_vocabulary": list(p.phase_vocabulary),
        "phase_mapping": dict(p.phase_mapping),
        "phase_priority": list(p.phase_priority),
    }


_DEFAULTS = preset_fields(DEFAULT_PRESET)
DEFAULT_LABEL_MAP: list[LabelEntry] = _DEFAULTS["label_map"]  # PRJ-07 ccRCC seed
DEFAULT_PHASE_VOCABULARY: list[str] = _DEFAULTS["phase_vocabulary"]
DEFAULT_PHASE_MAPPING: dict[str, str] = _DEFAULTS["phase_mapping"]
DEFAULT_PHASE_PRIORITY: list[str] = _DEFAULTS["phase_priority"]


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
    preset: PresetName = DEFAULT_PRESET  # PRJ-12; files without it predate presets (= ccrcc)
    phase_vocabulary: list[str] = Field(default_factory=lambda: list(DEFAULT_PHASE_VOCABULARY))
    # RAW (upper-case) -> canonical; see INPUT_METADATA.md §Phase resolution.
    phase_mapping: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_PHASE_MAPPING))
    phase_priority: list[str] = Field(default_factory=lambda: list(DEFAULT_PHASE_PRIORITY))
    viewer_defaults: ViewerDefaults = Field(default_factory=ViewerDefaults)


class ProjectPatch(BaseModel):
    """API-03 PATCH body: only provided fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    label_map: list[LabelEntry] | None = None
    phase_vocabulary: list[str] | None = None  # applies at the next import (re-index)
    phase_mapping: dict[str, str] | None = None
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
