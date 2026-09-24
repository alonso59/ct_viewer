"""API-25 surface mesh per mask label (VW-09, BE-04/06/12).

Not mounted here: the integrator adds `mesh_api` to `app/api/v1/__init__.py`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from app.api.v1.deps import Ctx
from app.core.errors import NotFound, SourceMissing
from app.imaging import mesh, streaming
from app.imaging.fingerprint import quick_fingerprint
from app.jobs.types import JobInfo

router = APIRouter(tags=["volumes"])

MESH_MEDIA_TYPE = "application/octet-stream"
JOBS_PATH = "/api/v1/jobs/{job_id}"

_MESH_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"content": {MESH_MEDIA_TYPE: {}}, "description": "gzip MZ3 mesh (world mm)"},
    202: {"model": JobInfo, "description": "Mesh job queued or running (`Location` = job)"},
    304: {"description": "Not modified (If-None-Match)"},
}


@router.get(
    "/projects/{pid}/items/{iid}/mesh/{label}",
    response_class=Response,
    responses=_MESH_RESPONSES,
    summary="Surface mesh of one mask label (202 + job if not cached)",
)
async def get_mesh(
    pid: str,
    iid: str,
    label: int,
    request: Request,
    ctx: Ctx,
    smooth: int = 1,
    seg: str | None = None,
) -> Response:
    """`seg` = segmentation set (ADR-0015); default `default_seg`."""
    mesh.check_params(label, smooth)
    item = ctx.index.get_item(pid, iid)
    seg_id = seg or ctx.workspace.get(pid).default_seg
    vol = item.masks.get(seg_id)
    if vol is None:
        raise NotFound(f"item has no mask in segmentation set {seg_id!r}")
    if seg_id == "imported" and item.labels_present and label not in item.labels_present:
        raise NotFound(f"label {label} is not present in the mask")
    path = ctx.workspace.resolver(pid).resolve(vol.ref)
    if not path.is_file():
        raise SourceMissing("mask file is missing")
    fp = vol.fp
    if fp is None:
        fp = await asyncio.to_thread(quick_fingerprint, path)
    key = mesh.cache_key(fp, label, smooth)
    etag = streaming.quote_etag(key)
    if streaming.is_not_modified(request, key):
        return streaming.not_modified(etag)
    spacing = item.geometry.spacing if item.geometry is not None else None
    result = mesh.ensure_mesh(
        ctx.jobs,
        pid,
        ctx.workspace.project_dir(pid),
        path,
        fp,
        label,
        smooth,
        fmt=vol.format,
        spacing=spacing,
    )
    if isinstance(result, JobInfo):
        return JSONResponse(
            result.model_dump(mode="json"),
            status_code=202,
            headers={"Location": JOBS_PATH.format(job_id=result.job_id)},
        )
    return FileResponse(
        result,
        media_type=MESH_MEDIA_TYPE,
        filename=f"{iid}_label{label}.mz3",
        content_disposition_type="inline",
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )
