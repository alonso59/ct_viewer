"""Redacted output of source operations and workspace runs, read incrementally by cursor."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.deps import Ctx
from app.tasks.logs import LIMIT, LogKind, LogPage, read_logs

router = APIRouter(tags=["logs"])


@router.get("/logs/{kind}/{ref}", response_model=LogPage)
def read(
    ctx: Ctx,
    kind: LogKind,
    ref: str,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = LIMIT,
) -> LogPage:
    return read_logs(ctx.source_operations, kind, ref, cursor, limit)
