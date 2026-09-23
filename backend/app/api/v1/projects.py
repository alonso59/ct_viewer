"""API-02..05 projects, roots (PRJ-*)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.v1.deps import Ctx
from app.projects.models import PathRoot, ProjectDetail, ProjectPatch, ProjectSummary, RootInfo
from app.projects.relink import VerifyReport, verify_root

router = APIRouter(tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class RootBody(BaseModel):
    path: str = Field(min_length=1)


class RelinkResult(BaseModel):
    root: RootInfo
    verify: VerifyReport


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(ctx: Ctx, archived: bool = False) -> list[ProjectSummary]:
    return ctx.workspace.list(archived=archived)


@router.post("/projects", response_model=ProjectDetail, status_code=201)
async def create_project(ctx: Ctx, body: ProjectCreate) -> ProjectDetail:
    cfg = await ctx.workspace.create(body.name, body.description)
    return ctx.workspace.detail(cfg.project_id)


@router.get("/projects/{pid}", response_model=ProjectDetail)
async def get_project(ctx: Ctx, pid: str) -> ProjectDetail:
    detail = ctx.workspace.detail(pid)
    await ctx.workspace.touch_opened(pid)
    return detail


@router.patch("/projects/{pid}", response_model=ProjectDetail)
async def patch_project(ctx: Ctx, pid: str, patch: ProjectPatch) -> ProjectDetail:
    before = ctx.workspace.get(pid)
    after = await ctx.workspace.update(pid, patch)
    fields = [f for f in sorted(patch.model_fields_set) if getattr(before, f) != getattr(after, f)]
    if fields:
        ctx.bus.publish(pid, "project.updated", {"fields": fields})
    return ctx.workspace.detail(pid)


@router.post("/projects/{pid}/archive", response_model=ProjectSummary)
async def archive_project(ctx: Ctx, pid: str) -> ProjectSummary:
    await ctx.workspace.archive(pid)
    ctx.index.invalidate(pid)
    return ctx.workspace.summary(pid)


@router.post("/projects/{pid}/unarchive", response_model=ProjectDetail)
async def unarchive_project(ctx: Ctx, pid: str) -> ProjectDetail:
    await ctx.workspace.unarchive(pid)
    ctx.index.invalidate(pid)
    return ctx.workspace.detail(pid)


@router.get("/projects/{pid}/roots", response_model=list[RootInfo])
def list_roots(ctx: Ctx, pid: str) -> list[RootInfo]:
    return ctx.workspace.roots(pid)


@router.put("/projects/{pid}/roots/{alias}", response_model=RelinkResult)
async def put_root(ctx: Ctx, pid: str, alias: str, body: RootBody) -> RelinkResult:
    ctx.workspace.project_dir(pid)  # 404 before validating the body against the filesystem
    root = PathRoot(alias=alias, path=body.path)
    await ctx.workspace.set_root(pid, root)
    ctx.index.invalidate(pid)
    items = ctx.index.load(pid).items
    report = await run_in_threadpool(verify_root, ctx.workspace.resolver(pid), items, alias)
    info = next(r for r in ctx.workspace.roots(pid) if r.alias == alias)
    return RelinkResult(root=info, verify=report)
