"""API-41 jobs panel (BE-06)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.deps import Ctx
from app.jobs.types import JobInfo

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobInfo])
def list_jobs(ctx: Ctx, project: str | None = None) -> list[JobInfo]:
    """Newest first; `?project=` filters by project id."""
    return ctx.jobs.list(project)


@router.get("/jobs/{job_id}", response_model=JobInfo)
def get_job(ctx: Ctx, job_id: str) -> JobInfo:
    return ctx.jobs.get(job_id)


@router.post("/jobs/{job_id}/cancel", response_model=JobInfo)
async def cancel_job(ctx: Ctx, job_id: str) -> JobInfo:
    return ctx.jobs.cancel(job_id)  # loop thread: the manager is not thread-safe
