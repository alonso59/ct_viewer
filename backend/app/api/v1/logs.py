"""Redacted output of source operations, workspace runs and project runs, read by cursor."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from app.api.v1.deps import Ctx
from app.core.errors import ValidationProblem
from app.tasks.logs import LIMIT, LogKind, LogPage, read_logs, read_project_run

router = APIRouter(tags=["logs"])


@router.get("/logs/{kind}/{ref}", response_model=LogPage)
async def read(
    ctx: Ctx,
    kind: LogKind,
    ref: str,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = LIMIT,
    project: Annotated[str | None, Query(description="The project of a project-run")] = None,
) -> LogPage:
    if kind == "project-run":
        if project is None:
            raise ValidationProblem("A project run's log needs ?project=")
        return await read_project_run(ctx.source_operations.tasks, project, ref, cursor, limit)
    if kind == "script-run":
        return ctx.ctflow_runs.logs(ref, cursor, limit)
    # these readers stay off the event loop, as before
    return await run_in_threadpool(read_logs, ctx.source_operations, kind, ref, cursor, limit)
