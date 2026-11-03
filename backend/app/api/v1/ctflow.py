"""CTFlow console: the command catalog and one-line evaluation (API-72, CTF-*)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.deps import Ctx, Reviewer
from app.ctflow.models import CommandInfo, EvalRequest, EvalResult
from app.ctflow.service import Console

router = APIRouter(tags=["ctflow"])


@router.get("/ctflow/commands", response_model=list[CommandInfo])
def commands(ctx: Ctx) -> list[CommandInfo]:
    return Console(ctx.source_operations).commands()


@router.post("/ctflow/eval", response_model=EvalResult)
async def evaluate(ctx: Ctx, body: EvalRequest, x_reviewer: Reviewer = None) -> EvalResult:
    return await Console(ctx.source_operations).eval(body, x_reviewer)
