from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from fastapi import Path as PathParam

from app.api.v1.deps import Ctx
from app.tasks import compute
from app.tasks.compute import CheckRequested, ComputeProfileBody, ComputeState

router = APIRouter(tags=["compute"])
ProfileId = Annotated[str, PathParam(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]


def _state(ctx: Ctx) -> ComputeState:
    root = ctx.workspace.root
    return compute.state(root, root / "queue")


@router.get("/compute", response_model=ComputeState)
def get_compute(ctx: Ctx) -> ComputeState:
    return _state(ctx)


@router.put("/compute/profiles/{profile_id}", response_model=ComputeState)
def put_profile(ctx: Ctx, profile_id: ProfileId, body: ComputeProfileBody) -> ComputeState:
    """Stores the profile; the runner validates it against the scheduler and reports the verdict."""
    compute.put(ctx.workspace.root, profile_id, body)
    return _state(ctx)


@router.delete("/compute/profiles/{profile_id}", response_model=ComputeState)
def delete_profile(ctx: Ctx, profile_id: ProfileId) -> ComputeState:
    compute.delete(ctx.workspace.root, profile_id)
    return _state(ctx)


@router.post("/compute/check", response_model=CheckRequested, status_code=202)
def check_compute(ctx: Ctx) -> CheckRequested:
    return CheckRequested(request=compute.request_check(ctx.workspace.root))
