"""API-42..47 tasks and task runs (TSK-*). `radiomics.pyradiomics` is served by the radiomics
service behind the same endpoints, its RAD-* records attached as `radiomics` (RAD-13)."""

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
    TaskRunListItem,
    TaskRunOutput,
    TaskRunRequest,
    TaskRunStarted,
    TaskValidateRequest,
    TaskValidateResult,
)
from app.tasks.service import TaskService
from app.tasks.workspace_runs import (
    WorkspaceEstimateRequest,
    WorkspaceRun,
    WorkspaceRunRequest,
    WorkspaceTasks,
)

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
    return svc(ctx).validate(tid, body.settings, body.labels, body.n_items)


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


@router.get("/projects/{pid}/task-runs", response_model=list[TaskRunListItem])
async def list_runs(ctx: Ctx, pid: str, task: str | None = None) -> list[TaskRunListItem]:
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


# -- API-62 workspace tasks (TSK-13): `scope: workspace` tasks without a project ------------------


def wsvc(ctx: AppContext) -> WorkspaceTasks:
    return WorkspaceTasks(ctx.settings, ctx.registry, ctx.guard, ctx.jobs, ctx.plugins.task_owner())


@router.post("/tasks/{tid}/estimate", response_model=TaskEstimate)
async def workspace_estimate(ctx: Ctx, tid: str, body: WorkspaceEstimateRequest) -> TaskEstimate:
    """The converter's dry run without a project (DCM-06, UI-25 step 3)."""
    return await wsvc(ctx).estimate(tid, body)


@router.post("/task-runs", response_model=TaskRunStarted, status_code=202)
async def start_workspace_run(ctx: Ctx, body: WorkspaceRunRequest) -> TaskRunStarted:
    return await wsvc(ctx).start(body)


@router.get("/task-runs", response_model=list[WorkspaceRun])
def list_workspace_runs(ctx: Ctx) -> list[WorkspaceRun]:
    return wsvc(ctx).list()


@router.get("/task-runs/{rid}", response_model=WorkspaceRun)
def get_workspace_run(ctx: Ctx, rid: str) -> WorkspaceRun:
    return wsvc(ctx).get(rid)


@router.post("/task-runs/{rid}/cancel", response_model=WorkspaceRun)
def cancel_workspace_run(ctx: Ctx, rid: str) -> WorkspaceRun:
    return wsvc(ctx).cancel(rid)
