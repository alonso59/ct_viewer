"""The reviewer stamp: free text from `X-Reviewer`, one rule for every writer; and the origin of
a run or operation. Both are advisory attribution, not identity."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel

from app.core.errors import ReviewerRequired, ValidationProblem

REVIEWER_MAX: Final = 100


class Origin(BaseModel):
    """Which client asked for a run or operation. Records written before origins existed have
    none (unknown); requests through the HTTP API are `gui`."""

    client: Literal["gui", "console", "terminal", "script"] = "gui"
    session: str | None = None
    script_run_id: str | None = None


def optional(raw: str | None) -> str | None:
    """The trimmed name, or None when empty; 422 when too long."""
    name = (raw or "").strip()
    if len(name) > REVIEWER_MAX:
        raise ValidationProblem(
            "Reviewer name too long",
            errors=[{"loc": ["header", "X-Reviewer"], "msg": f"max {REVIEWER_MAX} chars"}],
        )
    return name or None


def require(raw: str | None) -> str:
    """The trimmed name; 428 `reviewer-required` when empty, 422 when too long."""
    name = optional(raw)
    if name is None:
        raise ReviewerRequired("Set the X-Reviewer header (reviewer name or initials)")
    return name
