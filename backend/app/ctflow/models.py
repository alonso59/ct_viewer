"""Request and result shapes of the console (API-72)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tasks.models import PreflightResult, SettingsIssue


class OptionInfo(BaseModel):
    name: str
    type: str
    help: str = ""
    enum: list[Any] | None = None
    default: Any = None
    setting: str | None = None  # the task setting it fills; None for target options


class CommandInfo(BaseModel):
    name: str
    task_id: str | None = None
    summary: str
    usage: str
    options: list[OptionInfo] = Field(default_factory=list)
    available: bool = True
    reason: str | None = None


class EvalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None
    plan: bool = False  # resolve, validate and preflight without starting anything (CTF-09)
    client: Literal["console", "terminal"] = "console"


class ResolvedTarget(BaseModel):
    kind: Literal["items", "case", "all", "path", "source"]
    project_id: str | None = None
    n_items: int = 0
    item_ids: list[str] = Field(default_factory=list)  # at most ITEMS_SHOWN
    seg_id: str | None = None
    labels: list[int] = Field(default_factory=list)


class EvalPlan(BaseModel):
    ok: bool
    issues: list[SettingsIssue] = Field(default_factory=list)
    settings: dict[str, Any] | None = None
    preflight: PreflightResult | None = None


class StartedWork(BaseModel):
    kind: Literal["task-run", "source-operation"]
    id: str
    job_id: str | None = None
    status: str
    project_id: str | None = None


class EvalResult(BaseModel):
    command: str
    task_id: str | None = None
    target: ResolvedTarget | None = None
    plan: EvalPlan | None = None
    started: StartedWork | None = None
    data: Any = None  # what a core command returns
    text: list[str] = Field(default_factory=list)  # the same, as lines for a terminal
