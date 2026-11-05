"""CTFlow console: the command catalog, line evaluation and script runs (API-72, CTF-*)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.v1.deps import Ctx, Reviewer
from app.ctflow.library import SCRIPT_MAX, ScriptInfo, ScriptText
from app.ctflow.models import CommandInfo, EvalRequest, EvalResult
from app.ctflow.runs import ScriptRun, ScriptRunDetail, ScriptRunStart
from app.ctflow.service import Console

router = APIRouter(tags=["ctflow"])


class ScriptBody(BaseModel):
    text: str = Field(min_length=1, max_length=SCRIPT_MAX)


def console(ctx: Ctx) -> Console:
    return Console(ctx.source_operations, ctx.ctflow_runs, ctx.source_batches)


@router.get("/ctflow/commands", response_model=list[CommandInfo])
def commands(ctx: Ctx) -> list[CommandInfo]:
    return console(ctx).commands()


@router.post("/ctflow/eval", response_model=EvalResult)
async def evaluate(ctx: Ctx, body: EvalRequest, x_reviewer: Reviewer = None) -> EvalResult:
    session = ctx.ctflow_sessions.get(body.session)
    return await console(ctx).eval(body, x_reviewer, session)


@router.post("/ctflow/script-runs", response_model=ScriptRun, status_code=202)
async def start_script_run(
    ctx: Ctx, body: ScriptRunStart, x_reviewer: Reviewer = None
) -> ScriptRun:
    return await ctx.ctflow_runs.start(body, x_reviewer)


@router.get("/ctflow/script-runs", response_model=list[ScriptRun])
def list_script_runs(ctx: Ctx) -> list[ScriptRun]:
    return ctx.ctflow_runs.all()


@router.get("/ctflow/script-runs/{rid}", response_model=ScriptRunDetail)
def get_script_run(ctx: Ctx, rid: str) -> ScriptRunDetail:
    return ctx.ctflow_runs.detail(rid)


@router.post("/ctflow/script-runs/{rid}/cancel", response_model=ScriptRun)
async def cancel_script_run(ctx: Ctx, rid: str) -> ScriptRun:
    return await ctx.ctflow_runs.control(rid, "cancel")


@router.post("/ctflow/script-runs/{rid}/pause", response_model=ScriptRun)
async def pause_script_run(ctx: Ctx, rid: str) -> ScriptRun:
    return await ctx.ctflow_runs.control(rid, "pause")


@router.post("/ctflow/script-runs/{rid}/resume", response_model=ScriptRun, status_code=202)
async def resume_script_run(ctx: Ctx, rid: str) -> ScriptRun:
    return await ctx.ctflow_runs.resume(rid)


@router.get("/ctflow/scripts", response_model=list[ScriptInfo])
def list_scripts(ctx: Ctx, project: str | None = None) -> list[ScriptInfo]:
    return console(ctx).library.list(project)


@router.get("/ctflow/scripts/{name}", response_model=ScriptText)
def read_script(ctx: Ctx, name: str, project: str | None = None) -> ScriptText:
    return console(ctx).library.read(name, project)


@router.put("/ctflow/scripts/{name}", response_model=ScriptInfo)
def save_script(ctx: Ctx, name: str, body: ScriptBody, project: str | None = None) -> ScriptInfo:
    return console(ctx).library.save(name, body.text, project)


@router.delete("/ctflow/scripts/{name}", status_code=204)
def delete_script(ctx: Ctx, name: str, project: str | None = None) -> None:
    console(ctx).library.delete(name, project)
