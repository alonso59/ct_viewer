"""Curation records (CURATION.md §Status, §Targets, §Event schema v1, §Correction queue CSV)."""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal[
    "rejected",
    "needs_major_correction",
    "wrong_phase_suspected",
    "wrong_side_suspected",
    "needs_minor_correction",
    "missing",
    "cannot_assess",
    "accepted",
    "not_reviewed",
]
Priority = Literal["low", "medium", "high"]
Source = Literal["ui", "v2_import", "api"]
ProposedSide = Literal["L", "R"]

# CURATION.md §Status: rollup severity (high → low) and the correction-queue set (CUR-08/09).
SEVERITY: Final[dict[str, int]] = {
    "rejected": 8,
    "needs_major_correction": 7,
    "wrong_phase_suspected": 6,
    "wrong_side_suspected": 6,
    "needs_minor_correction": 5,
    "missing": 4,
    "cannot_assess": 3,
    "accepted": 1,
    "not_reviewed": 0,
}
QUEUE_STATUSES: Final = frozenset(
    {
        "rejected",
        "needs_major_correction",
        "wrong_phase_suspected",
        "wrong_side_suspected",
        "needs_minor_correction",
        "missing",
    }
)
NOT_REVIEWED: Final = "not_reviewed"
CASE_TARGET: Final = "case"
TARGET_PATTERN: Final = r"^(seg|voi_mask|phase|side|case|label:[0-9]+)$"  # §Targets
Target = Annotated[str, Field(pattern=TARGET_PATTERN, examples=["seg", "label:2", "case"])]

QUEUE_COLUMNS: Final = (
    "case_id",
    "item_id",
    "scope",
    "side",
    "phase",
    "target",
    "status",
    "priority",
    "comment",
    "reviewer",
    "at",
    "image_path_abs",
    "mask_path_abs",
)


class CurationEvent(BaseModel):
    """One append-only decision in `curation/events.jsonl` (CUR-02, schema v1)."""

    event_id: str
    schema_version: Literal[1] = 1
    at: str
    reviewer: str
    session_id: str | None = None
    item_id: str | None = None  # null when target = case (CUR-03)
    case_id: str
    target: str
    status: Status
    priority: Priority = "medium"
    comment: str = ""
    proposed_phase: str | None = None
    proposed_side: ProposedSide | None = None
    add_to_queue: bool = False
    context: dict[str, Any] = Field(default_factory=dict)  # audit snapshot; not used for logic
    source: Source = "ui"


class EventIn(BaseModel):
    """API-50 POST body. The server sets `event_id`, `at`, `reviewer`, `schema_version`."""

    model_config = ConfigDict(extra="forbid")

    item_id: str | None = None
    case_id: str | None = Field(
        default=None, description="Required when target = case; else derived from the item"
    )
    target: Target
    status: Status
    priority: Priority = "medium"
    comment: str = Field(default="", max_length=10_000)
    proposed_phase: str | None = None  # CUR-06, from phase_vocabulary
    proposed_side: ProposedSide | None = None  # CUR-07
    add_to_queue: bool = False  # CUR-09
    context: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = Field(default=None, max_length=200)
    source: Literal["ui", "api"] = "ui"  # `v2_import` only via API-54


class TargetState(BaseModel):
    """Latest event for one `(item_id, target)` (or case-target) key (CUR-08)."""

    target: str
    status: Status
    priority: Priority
    comment: str
    reviewer: str
    at: str
    event_id: str
    add_to_queue: bool = False
    proposed_phase: str | None = None
    proposed_side: ProposedSide | None = None


class ItemState(BaseModel):
    """Item status = worst over its targets; reviewer/at/event_id of the deciding event."""

    item_id: str
    case_id: str
    status: Status
    reviewer: str
    at: str
    event_id: str
    targets: list[TargetState]


class CaseState(BaseModel):
    """Case rollup = worst over its items and case-target events (CUR-08)."""

    case_id: str
    status: Status
    reviewer: str
    at: str
    event_id: str
    last_reviewed_at: str
    n_items_reviewed: int
    targets: list[TargetState] = Field(default_factory=list, description="Case-target keys")


class CurationState(BaseModel):
    """API-51 response and the `curation/state.json` snapshot (derived, PRJ-10)."""

    schema_version: Literal[1] = 1
    updated_at: str
    n_events: int
    items: list[ItemState]
    cases: list[CaseState]


class QueueRow(BaseModel):
    """Correction queue row (CUR-09); fields = CURATION.md §Correction queue CSV columns."""

    case_id: str
    item_id: str
    scope: str | None = None
    side: str | None = None
    phase: str | None = None
    target: str
    status: Status
    priority: Priority
    comment: str
    reviewer: str
    at: str
    image_path_abs: str | None = None  # resolved at export time; null when unresolvable
    mask_path_abs: str | None = None


class ExportResult(BaseModel):
    """API-53: files written under the project folder's `dir` (CUR-10)."""

    dir: str = "exports"
    files: list[str]
    at: str


class V2Skipped(BaseModel):
    line: int  # CSV line number (header = 1)
    review_id: str | None = None
    reason: str


class V2ImportReport(BaseModel):
    """API-54 result (CUR-13)."""

    n_rows: int
    imported: int
    skipped: list[V2Skipped]
