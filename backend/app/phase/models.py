from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PhaseEventSource = Literal["manual", "analyzer_accept", "v2_import", "converter_import"]


class PhaseEvent(BaseModel):
    """One append-only selection in `events/phase.jsonl`."""

    event_id: str
    at: str
    reviewer: str
    session_id: str | None = None
    case_id: str
    scan_idx: str
    value: str
    source: PhaseEventSource = "manual"
    accepted_run_id: str | None = None  # the `analyzer.phase` run whose guess was accepted


class PhaseIn(BaseModel):
    """The server sets `event_id`, `at`, `reviewer`; imports use their own routes."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    scan_idx: str
    value: str = Field(min_length=1, max_length=64, description="A `phase_vocabulary` value")
    source: Literal["manual", "analyzer_accept"] = "manual"
    accepted_run_id: str | None = Field(
        default=None, description="Required with `analyzer_accept`: the active phase run"
    )
    session_id: str | None = Field(default=None, max_length=200)


class PhaseSelection(BaseModel):
    """Latest event for one scan, with the index-time value it overrides."""

    case_id: str
    scan_idx: str
    value: str
    source: PhaseEventSource
    accepted_run_id: str | None = None
    reviewer: str
    at: str
    event_id: str
    resolved: str | None = None
    resolved_source: str | None = None


class PhaseState(BaseModel):
    n_events: int
    selections: list[PhaseSelection]


class PhaseExportResult(BaseModel):
    """Files written under the project folder's `dir`."""

    dir: str = "exports"
    files: list[str]
    at: str
