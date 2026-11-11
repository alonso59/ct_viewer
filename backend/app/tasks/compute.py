"""Compute profiles: the user's named scheduler requests, and what the runner reports about them.

The runner alone talks to the scheduler and decides whether a profile is valid. This module
stores the profiles, checks their shape, and joins them with the runner's latest report."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.errors import NotFound, ValidationProblem
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import new_ulid
from app.tasks.registry import runners

PROFILES_FILE = "compute-profiles.json"
CHECK_REQUEST = "compute-check.json"
MAX_PROFILES = 8
MAX_GPUS = 2
NAME = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"


class ComputeProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    account: str | None = Field(default=None, pattern=NAME, max_length=64)
    partition: str | None = Field(default=None, pattern=NAME, max_length=64)
    gpus: int = Field(ge=1, le=MAX_GPUS)
    cpus: int = Field(ge=1, le=1024)
    memory_mb: int = Field(ge=1, le=1048576)
    seconds: int = Field(ge=60, le=604800)


class ComputeProfile(ComputeProfileBody):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    status: Literal["valid", "rejected", "unchecked"] = "unchecked"
    reason: str = ""
    checked_at: str | None = None
    # The scheduler's prediction for a request made now; never a guarantee.
    estimated_start: str | None = None
    # The operator file's own values, shown when the user has defined no profile.
    implicit: bool = False


class ComputeLimits(BaseModel):
    """The operator's per-run bounds."""

    cpus: int
    memory_mb: int
    tasks: int
    seconds: int
    gpus: int


class Partition(BaseModel):
    name: str
    up: bool
    max_seconds: int | None = None
    gpus: bool = False
    gpu_types: list[str] = Field(default_factory=list)


class ComputeState(BaseModel):
    """`backend` is None while no runner reports one; unknown scheduler facts are None."""

    backend: str | None = None
    limits: ComputeLimits | None = None
    read_at: str | None = None
    error: str | None = None
    accounts: list[str] | None = None
    partitions: list[Partition] | None = None
    # The check request the runner has answered; compare with the id a check returned.
    answered: str | None = None
    profiles: list[ComputeProfile] = Field(default_factory=list)


class CheckRequested(BaseModel):
    request: str


def stored(workspace: Path) -> list[dict[str, Any]]:
    try:
        raw = read_json(workspace / PROFILES_FILE)
        return [p for p in raw["profiles"] if isinstance(p, dict)]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def report(queue: Path) -> dict[str, Any]:
    """The `execution` block of the freshest runner that has one."""
    fresh = [r for r in runners(queue) if r.fresh and r.execution]
    return max(fresh, key=lambda r: r.at).execution or {} if fresh else {}


def state(workspace: Path, queue: Path) -> ComputeState:
    execution = report(queue)
    site = execution.get("scheduler") or {}
    verdicts = [p for p in site.get("profiles") or [] if isinstance(p, dict)]
    saved = stored(workspace)
    profiles = []
    for profile in saved:
        verdict = next((v for v in verdicts if {**v, **profile} == v), {})
        profiles.append(ComputeProfile.model_validate({**profile, **verdict}))
    if not saved:
        profiles = [ComputeProfile.model_validate({**v, "implicit": True}) for v in verdicts]
    return ComputeState(
        backend=execution.get("backend"),
        limits=execution.get("limits"),
        read_at=site.get("at"),
        error=site.get("error"),
        accounts=site.get("accounts"),
        partitions=site.get("partitions"),
        answered=site.get("request"),
        profiles=profiles,
    )


def _write(workspace: Path, profiles: list[dict[str, Any]]) -> None:
    atomic_write_json(workspace / PROFILES_FILE, {"format_version": 1, "profiles": profiles})


def put(workspace: Path, profile_id: str, body: ComputeProfileBody) -> None:
    profile = ComputeProfile(id=profile_id, **body.model_dump())
    saved = [p for p in stored(workspace) if p.get("id") != profile_id]
    if len(saved) >= MAX_PROFILES:
        raise ValidationProblem(f"At most {MAX_PROFILES} compute profiles")
    fields = {"id", *ComputeProfileBody.model_fields}
    _write(workspace, [*saved, profile.model_dump(include=fields)])


def delete(workspace: Path, profile_id: str) -> None:
    saved = stored(workspace)
    kept = [p for p in saved if p.get("id") != profile_id]
    if len(kept) == len(saved):
        raise NotFound(f"Compute profile {profile_id!r} not found")
    _write(workspace, kept)


def request_check(workspace: Path) -> str:
    """Ask the runner to read the scheduler and test every profile again."""
    request = new_ulid()
    atomic_write_json(workspace / CHECK_REQUEST, {"id": request})
    return request
