"""API-42..47 tasks and task runs (TSK-*). `radiomics.pyradiomics` is served by the radiomics
service behind the same endpoints; API-30..37 remain its aliases during P7b (RAD-13)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header

from app.api.v1.deps import Ctx
from app.context import AppContext
from app.tasks.models import (
    PreflightRequest,
    PreflightResult,
    TaskEstimate,
    TaskInfo,
    TaskItemError,
    TaskList,
    TaskRunDetail,
    TaskRunOutput,
    TaskRunRequest,
    TaskRunStarted,
    TaskRunSummary,
    TaskValidateRequest,
    TaskValidateResult,
)
from app.tasks.service import TaskService

router = APIRouter(tags=["tasks"])
Reviewer = Annotated[str | None, Header(alias="X-Reviewer")]


def svc(ctx: AppContext) -> TaskService:
    return TaskService(
        ctx.settings, ctx.registry, ctx.workspace, ctx.index, ctx.jobs, ctx.bus, ctx.locks
    )


@router.get("/tasks", response_model=TaskList)
def list_tasks(ctx: Ctx) -> TaskList:
    return svc(ctx).list_tasks()


@router.get("/tasks/{tid}", response_model=TaskInfo)
def get_task(ctx: Ctx, tid: str) -> TaskInfo:
    return svc(ctx).get(tid)


@router.post("/tasks/{tid}/validate", response_model=TaskValidateResult)
def validate_task(ctx: Ctx, tid: str, body: TaskValidateRequest) -> TaskValidateResult:
    return svc(ctx).validate(tid, body.settings)


@router.post("/projects/{pid}/tasks/{tid}/preflight", response_model=PreflightResult)
async def preflight(ctx: Ctx, pid: str, tid: str, body: PreflightRequest) -> PreflightResult:
    return await svc(ctx).preflight(pid, tid, body)


@router.post("/projects/{pid}/tasks/{tid}/estimate", response_model=TaskEstimate)
async def estimate(ctx: Ctx, pid: str, tid: str, body: PreflightRequest) -> TaskEstimate:
    return await svc(ctx).estimate(pid, tid, body)


@router.post("/projects/{pid}/task-runs", response_model=TaskRunStarted, status_code=202)
async def start_run(
    ctx: Ctx, pid: str, body: TaskRunRequest, x_reviewer: Reviewer = None
) -> TaskRunStarted:
    return await svc(ctx).start(pid, body, x_reviewer)


@router.get("/projects/{pid}/task-runs", response_model=list[TaskRunSummary])
async def list_runs(ctx: Ctx, pid: str, task: str | None = None) -> list[TaskRunSummary]:
    return await svc(ctx).list_runs(pid, task)


@router.get("/projects/{pid}/task-runs/{rid}", response_model=TaskRunDetail)
async def get_run(ctx: Ctx, pid: str, rid: str) -> TaskRunDetail:
    return await svc(ctx).get_run(pid, rid)


@router.post("/projects/{pid}/task-runs/{rid}/cancel", response_model=TaskRunDetail)
async def cancel_run(ctx: Ctx, pid: str, rid: str) -> TaskRunDetail:
    return await svc(ctx).cancel(pid, rid)


@router.post(
    "/projects/{pid}/task-runs/{rid}/resume", response_model=TaskRunStarted, status_code=202
)
async def resume_run(ctx: Ctx, pid: str, rid: str) -> TaskRunStarted:
    return await svc(ctx).resume(pid, rid)


@router.get("/projects/{pid}/task-runs/{rid}/errors", response_model=list[TaskItemError])
def run_errors(ctx: Ctx, pid: str, rid: str) -> list[TaskItemError]:
    return svc(ctx).errors(pid, rid)


@router.get("/projects/{pid}/task-runs/{rid}/outputs", response_model=list[TaskRunOutput])
def run_outputs(ctx: Ctx, pid: str, rid: str) -> list[TaskRunOutput]:
    return svc(ctx).outputs(pid, rid)
