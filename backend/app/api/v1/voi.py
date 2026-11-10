from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response

from app.api.v1.deps import Ctx
from app.api.v1.tasks import svc as task_svc
from app.api.v1.volumes import local_volume
from app.context import AppContext
from app.core.errors import NotFound
from app.imaging import streaming
from app.tasks.models import TaskRunDetail
from app.voi import catalog
from app.voi.models import VoiCandidates, VoiRegion, VoiRequest, VoiRunResults
from app.voi.service import VoiService, regions

router = APIRouter(prefix="/plugins/voi", tags=["voi"])

_WEBP: dict[int | str, dict[str, Any]] = {
    200: {"content": {streaming.WEBP_MEDIA_TYPE: {}}, "description": "WebP preview"},
    304: {"description": "Not modified (If-None-Match)"},
}


def svc(ctx: AppContext, pid: str) -> VoiService:
    return VoiService(ctx.jobs, ctx.workspace.project_dir(pid))


@router.get("/regions", response_model=list[VoiRegion])
def list_regions() -> list[VoiRegion]:
    return regions()


@router.post("/projects/{pid}/items/{iid}/candidates", response_model=VoiCandidates)
async def candidates(ctx: Ctx, pid: str, iid: str, body: VoiRequest) -> VoiCandidates:
    """VOI boxes for one scan; the first call reads the volumes, later ones are cached."""
    cfg = ctx.workspace.get(pid)
    seg_id = body.seg_id or cfg.default_seg
    image_path, image_key, _ = await local_volume(ctx, pid, iid, "image")
    mask_path, mask_key, _ = await local_volume(ctx, pid, iid, "mask", seg_id)
    segmentation = cfg.segmentation(seg_id)
    out, wrote = await svc(ctx, pid).candidates(
        iid,
        seg_id,
        body,
        (image_path, image_key),
        (mask_path, mask_key),
        {e.name: e.value for e in cfg.label_map},
        segmentation.label_mapping if segmentation is not None else {},
    )
    if wrote:
        ctx.cache_budget.request()
    return out


@router.get(
    "/projects/{pid}/previews/{token}",
    response_class=Response,
    responses=_WEBP,
    summary="Axial WebP preview of a candidate's middle slice",
)
async def preview(ctx: Ctx, pid: str, token: str, request: Request) -> Response:
    ctx.workspace.get(pid)
    path = await svc(ctx, pid).preview(token)
    return streaming.webp_response(path, token, request)


async def _voi_run(ctx: AppContext, pid: str, rid: str) -> TaskRunDetail:
    run = await task_svc(ctx).get_run(pid, rid)
    if run.task.id != "voi.extract":
        raise NotFound("not a VOI extraction run")
    return run


@router.get("/projects/{pid}/runs/{rid}/results", response_model=VoiRunResults)
async def run_results(
    ctx: Ctx,
    pid: str,
    rid: str,
    view: Literal["scans", "cases"] = "scans",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=catalog.MAX_PAGE)] = catalog.MAX_PAGE,
    q: str = "",
    confidence: Literal["verified", "probable", "uncertain", "reviewer"] | None = None,
    review: bool = False,
    warning: str | None = None,
    side: Literal["L", "R"] | None = None,
    case: str | None = None,
) -> VoiRunResults:
    """A page of the VOIs a `voi.extract` run wrote (its `voi_catalog.jsonl`), by scan or by case.

    The summary covers the whole run; the filters (`q` matches case and scan ids; `review` is an
    uncertain side or a warning) cut the rows; a scan or case is listed when a VOI matches.
    """
    run = await _voi_run(ctx, pid, rid)
    rows = catalog.load(Path(run.output_dir)) if run.output_dir else ()
    total, scans, cases = catalog.query(
        rows,
        view=view,
        offset=offset,
        limit=limit,
        q=q,
        confidence=confidence,
        review=review,
        warning=warning,
        side=side,
        case=case,
    )
    return VoiRunResults(
        run_id=run.run_id,
        status=run.status,
        reviewer=run.reviewer,
        finished_at=run.finished_at,
        output_dir=run.output_dir,
        settings=run.settings,
        summary=catalog.summary(rows),
        view=view,
        total=total,
        offset=offset,
        limit=limit,
        scans=scans,
        cases=cases,
    )


@router.get(
    "/projects/{pid}/runs/{rid}/results/{n}/preview",
    response_class=Response,
    responses=_WEBP,
    summary="WebP of a written VOI: middle axial slice with its label box",
)
async def result_preview(ctx: Ctx, pid: str, rid: str, n: int, request: Request) -> Response:
    run = await _voi_run(ctx, pid, rid)
    if not run.output_dir:
        raise NotFound("the run has no output folder")
    path = await svc(ctx, pid).result_preview(rid, Path(run.output_dir), n)
    return streaming.webp_response(path, path.stem, request)  # changes with the renderer
