"""Cursor paging for list endpoints (API.md §Conventions): `{items, next_cursor, total}`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel

from app.core.errors import ValidationProblem

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None
    total: int


class PageParams(BaseModel):
    cursor: str | None = None
    limit: int = DEFAULT_LIMIT


def page_params(
    cursor: Annotated[str | None, Query(description="Opaque cursor from `next_cursor`")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> PageParams:
    return PageParams(cursor=cursor or None, limit=limit)


Paging = Annotated[PageParams, Depends(page_params)]


def offset_of(cursor: str | None) -> int:
    if not cursor:
        return 0
    if not cursor.isdigit():
        raise ValidationProblem(
            "Invalid cursor", errors=[{"loc": ["query", "cursor"], "msg": "invalid cursor"}]
        )
    return int(cursor)


def paginate[T](rows: Sequence[T], params: PageParams) -> Page[T]:
    start = offset_of(params.cursor)
    end = start + params.limit
    nxt = str(end) if end < len(rows) else None
    return Page[T](items=list(rows[start:end]), next_cursor=nxt, total=len(rows))
