"""The reviewer stamp (ADR-0004, CUR-01): free text from `X-Reviewer`, at most 100 characters.

One rule for every writer (AUD-A6-06): curation, phase and labeling events, radiomics runs
(RAD-09, required) and task runs (TSK-10, optional).
"""

from __future__ import annotations

from typing import Final

from app.core.errors import ReviewerRequired, ValidationProblem

REVIEWER_MAX: Final = 100


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
