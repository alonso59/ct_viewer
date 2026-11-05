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
    # one command, or a script: commands, variables, procedures and control flow (CTF-07)
    line: str = Field(min_length=1, max_length=100_000)
    session: str | None = None  # omitted: a new session (CTF-08)
    project_id: str | None = None  # omitted: the session's current project
    plan: bool = False  # resolve, validate and preflight without starting anything (CTF-09)
    client: Literal["console", "terminal", "agent"] = "console"


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


class WorkRef(BaseModel):
    """A run or source operation the client can follow (status, API-71 logs)."""

    kind: Literal["task-run", "source-operation", "workspace-run", "script-run"]
    id: str
    job_id: str | None = None
    status: str
    project_id: str | None = None


class CommandResult(BaseModel):
    """One CTFlow command the line ran."""

    command: str
    value: str = ""  # what the command returns to the script (a run id, a list of case ids, …)
    task_id: str | None = None
    target: ResolvedTarget | None = None
    plan: EvalPlan | None = None
    started: WorkRef | None = None  # work this line started
    work: WorkRef | None = None  # work this line looked at or controlled
    data: Any = None  # what a core command returns
    text: list[str] = Field(default_factory=list)  # the same, as lines for a terminal


class EvalError(BaseModel):
    """A line that stopped after earlier commands had already acted."""

    title: str
    detail: str
    line: int | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


class EvalResult(BaseModel):
    session: str
    project_id: str | None = None  # the session's current project after the line
    value: str = ""  # the script's result
    text: list[str] = Field(default_factory=list)  # every command's lines and `puts`, in order
    steps: list[CommandResult] = Field(default_factory=list)  # at most STEPS_SHOWN
    plan_stopped: str | None = None  # plan mode: why later commands could not be planned
    error: EvalError | None = None
