"""API-02..06 projects, roots, bundles (PRJ-*)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Header, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.api.v1.deps import Ctx
from app.api.v1.imports import ingest_service
from app.context import AppContext
from app.core.errors import JobConflict
from app.projects.models import (
    Modality,
    PathRoot,
    ProjectDetail,
    ProjectPatch,
    ProjectSummary,
    RootInfo,
    RootRole,
)
from app.projects.presets import load_packs
from app.projects.relink import VerifyReport, verify_root

router = APIRouter(tags=["projects"])


class ProjectCreate(BaseModel):
    """PRJ-14: a name and an optional default modality; `packs` is for scripts (PRJ-16)."""

    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    default_modality: Modality = "CT"
    packs: list[str] = Field(default_factory=list, description="Study packs to apply (API-28)")


class PackInfo(BaseModel):
    """API-28 row: a study pack contributed by a plugin (PRJ-16)."""

    pack_id: str
    plugin: str
    title: str
    description: str
    labels: list[str]
    phase_vocabulary: list[str]
    target_profile: str


class PackApply(BaseModel):
    pack_id: str = Field(min_length=1)


class PackApplied(BaseModel):
    project: ProjectDetail
    job_id: str | None = None  # the reindex job (phase rules changed)


class ViewToken(BaseModel):
    view_token: str | None
    view_url: str | None


class RootBody(BaseModel):
    path: str = Field(min_length=1)
    # `derived` (PRJ-13): the task output folder, inside ALLOWED_DERIVED_ROOTS (ADR-0014).
    role: RootRole | None = Field(
        default=None, description="Default: the alias's role, else source"
    )


class RelinkResult(BaseModel):
    root: RootInfo
    verify: VerifyReport


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(ctx: Ctx, archived: bool = False) -> list[ProjectSummary]:
    return ctx.workspace.list(archived=archived)


@router.post("/projects", response_model=ProjectDetail, status_code=201)
async def create_project(ctx: Ctx, body: ProjectCreate) -> ProjectDetail:
    cfg = await ctx.workspace.create(body.name, body.description, body.default_modality, body.packs)
    return ctx.workspace.detail(cfg.project_id)


@router.get("/projects/{pid}", response_model=ProjectDetail)
async def get_project(ctx: Ctx, pid: str, response: Response) -> ProjectDetail:
    await ctx.workspace.touch_opened(pid)
    detail = ctx.workspace.detail(pid)
    response.headers["ETag"] = detail.etag  # PRJ-15
    return detail


@router.patch(
    "/projects/{pid}",
    response_model=ProjectDetail,
    responses={
        412: {"description": "Stale If-Match (PRJ-15)"},
        428: {"description": "No If-Match"},
    },
)
async def patch_project(
    ctx: Ctx,
    pid: str,
    patch: ProjectPatch,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ProjectDetail:
    ctx.workspace.check_etag(pid, if_match)
    before = ctx.workspace.get(pid)
    after = await ctx.workspace.update(pid, patch)
    fields = [f for f in sorted(patch.model_fields_set) if getattr(before, f) != getattr(after, f)]
    if "default_seg" in fields:
        ctx.index.invalidate(pid)  # the deprecated `mask` alias follows default_seg
    if fields:
        ctx.bus.publish(pid, "project.updated", {"fields": fields})
    detail = ctx.workspace.detail(pid)
    response.headers["ETag"] = detail.etag
    return detail


@router.get("/packs", response_model=list[PackInfo])
def list_packs() -> list[PackInfo]:
    return [
        PackInfo(
            pack_id=p.id,
            plugin=p.plugin,
            title=p.title,
            description=p.description,
            labels=[s.name for s in p.label_map],
            phase_vocabulary=list(p.phase_vocabulary),
            target_profile=p.target_profile,
        )
        for p in load_packs().values()
    ]


@router.post("/projects/{pid}/packs", response_model=PackApplied)
async def apply_pack(ctx: Ctx, pid: str, body: PackApply) -> PackApplied:
    """PRJ-16: never deletes data; the index is rebuilt with the new phase rules."""
    before = ctx.workspace.get(pid)
    after = await ctx.workspace.apply_pack(pid, body.pack_id)
    job_id = None
    if (before.phase_vocabulary, before.phase_mapping) != (
        after.phase_vocabulary,
        after.phase_mapping,
    ):
        try:
            job_id = await ingest_service(ctx).reindex(pid)
        except JobConflict:
            job_id = None  # an index job is running; the next rebuild uses the new rules
    ctx.index.invalidate(pid)
    ctx.bus.publish(pid, "project.updated", {"fields": ["packs", "label_map", "phase_vocabulary"]})
    return PackApplied(project=ctx.workspace.detail(pid), job_id=job_id)


@router.post("/projects/{pid}/view-token", response_model=ViewToken)
async def create_view_token(ctx: Ctx, pid: str) -> ViewToken:
    """PRJ-17 / API-61: create or rotate; the previous link stops working at once."""
    cfg = await ctx.workspace.set_view_token(pid, create=True)
    ctx.bus.publish(pid, "project.updated", {"fields": ["view_token"]})
    token = cfg.view_token or ""
    return ViewToken(view_token=token, view_url=ctx.workspace.view_url(token))


@router.delete("/projects/{pid}/view-token", status_code=204)
async def revoke_view_token(ctx: Ctx, pid: str) -> Response:
    await ctx.workspace.set_view_token(pid, create=False)
    ctx.bus.publish(pid, "project.updated", {"fields": ["view_token"]})
    return Response(status_code=204)


@router.post("/projects/{pid}/archive", response_model=ProjectSummary)
async def archive_project(ctx: Ctx, pid: str) -> ProjectSummary:
    ctx.workspace.project_dir(pid)  # 404 first
    # AUD-A5-10: a running job would keep writing into a re-created active folder
    busy = ctx.jobs.busy(pid)
    if busy is not None:
        raise JobConflict(
            f"A {busy.kind} job is running ({busy.job_id}); wait for it or cancel it, then archive"
        )
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
    current = next((r for r in ctx.workspace.get(pid).path_roots if r.alias == alias), None)
    role = body.role or (current.role if current else "source")
    root = PathRoot(alias=alias, path=body.path, role=role)
    await ctx.workspace.set_root(pid, root)
    ctx.index.invalidate(pid)
    items = ctx.index.load(pid).items
    report = await run_in_threadpool(verify_root, ctx.workspace.resolver(pid), items, alias)
    info = next(r for r in ctx.workspace.roots(pid) if r.alias == alias)
    return RelinkResult(root=info, verify=report)


class BundleRoot(BaseModel):
    """One alias of the imported project, checked on this server (PRJ-09)."""

    root: RootInfo  # `exists`: directory exists and is inside ALLOWED_DATA_ROOTS
    verify: VerifyReport  # quick-fingerprint sample, as in relink (PRJ-05)


class BundleImportResult(BaseModel):
    project: ProjectDetail
    source_project_id: str  # `project_id` in the bundle
    id_changed: bool  # the id was already used here, so the import got a new one
    roots: list[BundleRoot]
    needs_relink: bool  # open the relink dialog (PRJ-09): some alias does not resolve


ZIP_BODY: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        "description": "Project bundle (PRJ-08)",
    }
}


@router.post("/projects/{pid}/bundle", response_class=FileResponse, responses=ZIP_BODY)
async def export_bundle(ctx: Ctx, pid: str) -> FileResponse:
    """API-06 export: `.zip` of the project folder without `cache/` and never image data."""
    path, filename = await ctx.workspace.export_bundle(pid)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(Path(path).unlink, missing_ok=True),
    )


@router.post("/projects/import-bundle", response_model=BundleImportResult, status_code=201)
async def import_bundle(
    ctx: Ctx, bundle: Annotated[UploadFile, File(description="A PRJ-08 bundle .zip")]
) -> BundleImportResult:
    """API-06 import (PRJ-09): new project from a bundle, plus a per-alias resolve report."""
    cfg, source_id = await ctx.workspace.import_bundle(bundle.file)
    roots = await run_in_threadpool(_check_roots, ctx, cfg.project_id)
    return BundleImportResult(
        project=ctx.workspace.detail(cfg.project_id),
        source_project_id=source_id,
        id_changed=cfg.project_id != source_id,
        roots=roots,
        needs_relink=any(
            not r.root.exists or r.verify.missing or r.verify.mismatched for r in roots
        ),
    )


def _check_roots(ctx: AppContext, pid: str) -> list[BundleRoot]:
    ctx.index.invalidate(pid)
    items = ctx.index.load(pid).items
    resolver = ctx.workspace.resolver(pid)
    out: list[BundleRoot] = []
    for info in ctx.workspace.roots(pid):
        guard = ctx.workspace.derived_guard if info.role == "derived" else ctx.guard
        exists = info.exists and guard.is_allowed(Path(info.path))
        out.append(
            BundleRoot(
                root=info.model_copy(update={"exists": exists}),
                verify=verify_root(resolver, items, info.alias),
            )
        )
    return out
