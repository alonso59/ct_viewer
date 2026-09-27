"""Radiomics payloads and records (RADIOMICS.md, DATA_MODEL.md; API-30/32/36, API-43..47).

Settings are engine-agnostic in shape: `image_types` (filter → params), `features`
(class → feature names) and `settings` (engine option → value). Option names inside are the
engine's own (PyRadiomics names for the default engine, RAD-12).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.ids import Scope, Side

IbsiStatus = Literal["compliant", "deviates", "not_defined"]
OptionType = Literal["bool", "int", "float", "str", "enum", "float_list", "int_list"]
Severity = Literal["error", "warning"]
RunStatus = Literal[
    "queued", "running", "completed", "completed_with_errors", "failed", "cancelled", "interrupted"
]
TERMINAL_RUN: frozenset[str] = frozenset(
    {"completed", "completed_with_errors", "failed", "cancelled", "interrupted"}
)
RESUMABLE_RUN: frozenset[str] = frozenset({"interrupted", "cancelled", "failed"})
Cell = str | int | float | None

# -- schema (API-30, RAD-01/02) -------------------------------------------------------------


class Constraints(BaseModel):
    """For list types, `min`/`max`/`enum` apply to each element."""

    min: float | None = None
    max: float | None = None
    exclusive_min: bool = False
    exclusive_max: bool = False
    enum: list[str] | None = None
    min_items: int | None = None
    max_items: int | None = None


class OptionSpec(BaseModel):
    name: str
    group: str
    type: OptionType
    default: Any = None
    nullable: bool = False
    constraints: Constraints = Field(default_factory=Constraints)
    description: str = ""


class IbsiInfo(BaseModel):
    """Metadata only: never shown in the GUI (RADIOMICS.md §Principles)."""

    code: str | None = None
    status: IbsiStatus = "not_defined"


class FeatureSpec(BaseModel):
    name: str
    default_enabled: bool
    deprecated: bool = False
    ibsi: IbsiInfo


class FeatureClassSpec(BaseModel):
    name: str
    default_enabled: bool
    requires_2d: bool = False
    features: list[FeatureSpec]


class FilterSpec(BaseModel):
    name: str
    default_enabled: bool
    available: bool = True
    unavailable_reason: str | None = None
    requires_2d: bool = False
    params: list[OptionSpec] = Field(default_factory=list)


class GroupSpec(BaseModel):
    id: str
    label: str


class EngineInfo(BaseModel):
    name: str
    version: str


class RadiomicsSettings(BaseModel):
    """Input: omitted sections/keys take engine defaults. Output (normalized): all filled."""

    image_types: dict[str, dict[str, Any]] | None = None
    features: dict[str, list[str] | None] | None = None
    settings: dict[str, Any] | None = None


class SettingsSchema(BaseModel):
    engine: EngineInfo
    ibsi_map_version: str
    groups: list[GroupSpec]
    options: list[OptionSpec]
    filters: list[FilterSpec]
    feature_classes: list[FeatureClassSpec]
    defaults: RadiomicsSettings


# -- validation (API-43, RAD-04) ------------------------------------------------------------


class Issue(BaseModel):
    loc: list[str | int]
    msg: str
    severity: Severity = "error"
    rule: str


class ValidateRequest(BaseModel):
    settings: RadiomicsSettings = Field(default_factory=RadiomicsSettings)
    labels: list[int] | None = Field(None, description="Selected labels (optional)")
    n_items: int | None = Field(None, ge=0, description="Selected item count (optional)")


class ValidateResult(BaseModel):
    ok: bool
    issues: list[Issue]
    settings: RadiomicsSettings | None = None  # normalized, when coercion succeeded
    profile_hash: str | None = None  # when `ok`


# -- profiles (API-32, RAD-03) --------------------------------------------------------------


class ProfileEngine(BaseModel):
    name: str
    version: str
    major: str


class Profile(BaseModel):
    profile_hash: str
    name: str
    created_at: str
    updated_at: str
    engine: ProfileEngine
    settings: RadiomicsSettings


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    settings: RadiomicsSettings = Field(default_factory=RadiomicsSettings)


class ProfilePatch(BaseModel):
    name: str = Field(min_length=1, max_length=120)


# -- selection / estimate / runs (API-44..47, RAD-05..11) -----------------------------------


class SelectionFilter(BaseModel):
    """RAD-05 filter: values OR within a field, AND across fields; `var` as VAR-10."""

    phase: list[str] | None = None
    side: list[Side] | None = None
    var: dict[str, list[str]] | None = None


class Selection(BaseModel):
    """All active items (default) / explicit `item_ids` / `filter`; plus scope and labels."""

    item_ids: list[str] | None = None
    filter: SelectionFilter | None = None
    scope: Scope | None = None
    labels: list[int] = Field(default_factory=list)
    # RAD-05 / ADR-0015: the segmentation set whose masks are read (default `default_seg`)
    seg_id: str | None = None


class EstimateRequest(BaseModel):
    profile_hash: str | None = None
    settings: RadiomicsSettings | None = None
    selection: Selection


class EstimateResult(BaseModel):
    n_items: int
    n_labels: int
    n_units: int  # (item, label) extractions after skipping absent labels
    n_skipped: int
    # skipped (item, label) units per cause code (TSK-04, AUD-A2-05), e.g. {"missing_seg": 3}
    skipped_by: dict[str, int] = Field(default_factory=dict)
    sample_item_ids: list[str]
    time_per_item_s: float | None
    time_per_unit_s: float | None
    workers: int
    estimated_total_s: float | None
    sample_errors: list[str] = Field(default_factory=list)


class RunRequest(BaseModel):
    name: str | None = Field(None, max_length=200)
    profile_hash: str | None = None
    settings: RadiomicsSettings | None = None
    selection: Selection


class RunEngine(BaseModel):
    name: str
    version: str
    deps: dict[str, str]


class RunSelection(BaseModel):
    scope: Scope | None = None
    labels: list[int]
    filter: str | None = None
    item_ids: list[str]
    seg_id: str = "imported"  # recorded in run.json (RAD-05, NFR-15); older runs: imported


class RunInput(BaseModel):
    item_id: str
    image_fp: str | None = None
    seg_id: str = "imported"
    mask_fp: str | None = None


class RunCounts(BaseModel):
    items: int = 0
    ok: int = 0
    failed: int = 0
    features: int = 0
    skipped: int = 0  # (item, label) pairs not ready (TSK-04): no mask, blocking code, label


class RunRecord(BaseModel):
    """`radiomics/runs/{run_id}/run.json` (RAD-09)."""

    run_id: str
    name: str
    status: RunStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    reviewer: str
    engine: RunEngine
    ibsi_map_version: str
    profile_hash: str
    settings: RadiomicsSettings
    selection: RunSelection
    inputs: list[RunInput]
    counts: RunCounts
    job_id: str | None = None
    error: str | None = None


class RunProgress(BaseModel):
    done: int
    total: int
    eta_s: float | None = None


class RunDetail(RunRecord):
    progress: RunProgress | None = None


class RunSummary(BaseModel):
    run_id: str
    name: str
    status: RunStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    reviewer: str
    profile_hash: str
    selection: RunSelection
    counts: RunCounts
    job_id: str | None = None


class RunError(BaseModel):
    """One `errors.jsonl` row (RAD-07). `skipped` rows do not make a run fail.

    `code` names the cause (`radiomics/causes.py`, AUD-A2-05), `error` says it in plain words,
    `detail` keeps the engine's own text for failures. Rows written before FB5 have no code.
    """

    item_id: str
    label: int
    kind: Literal["failed", "skipped"]
    error: str
    at: str
    code: str | None = None
    detail: str | None = None


class FeaturesTable(BaseModel):
    """API-36 JSON: long rows follow the features.parquet schema; wide rows one per item+label."""

    run_id: str
    shape: Literal["long", "wide"]
    columns: list[str]
    rows: list[dict[str, Cell]]
    total: int
