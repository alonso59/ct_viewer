"""CTFlow console: the command catalog, line evaluation and script runs (API-72, CTF-*)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.deps import Ctx, Reviewer
from app.ctflow.models import CommandInfo, EvalRequest, EvalResult
from app.ctflow.runs import ScriptRun, ScriptRunDetail, ScriptRunStart
from app.ctflow.service import Console

router = APIRouter(tags=["ctflow"])


def console(ctx: Ctx) -> Console:
    return Console(ctx.source_operations, ctx.ctflow_runs)


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
