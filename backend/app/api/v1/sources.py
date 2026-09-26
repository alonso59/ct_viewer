"""API-19 source detection and API-07/08/09 Open mode (SRC-01..14): validate → call → map.

Open-mode logic lives in `app.sources.open_service` (AUD-A6-05)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.api.v1.deps import Ctx
from app.imaging import streaming
from app.sources import open as open_mode
from app.sources.detect import DetectResult, detect
from app.sources.open_service import OpenService, SaveBody, Saved

router = APIRouter(tags=["sources"])

_VOLUME: dict[int | str, dict[str, Any]] = {
    200: {"content": {streaming.VOLUME_MEDIA_TYPE: {}}, "description": "NIfTI bytes"},
    206: {"description": "Partial content (HTTP Range)"},
}
_PNG: dict[int | str, dict[str, Any]] = {
    200: {"content": {"image/png": {}}, "description": "Middle axial slice"}
}


class PathBody(BaseModel):
    path: str = Field(min_length=1)


@router.post("/sources/detect", response_model=DetectResult)
async def detect_source(ctx: Ctx, body: PathBody) -> DetectResult:
    """API-19: candidate adapters with reasons, counts and confidence (SRC-01/02)."""
    real = svc(ctx).guarded(body.path)
    available = "dicom.convert" in ctx.registry.tasks
    return await asyncio.to_thread(detect, real, dicom_available=available)


def svc(ctx: Ctx) -> OpenService:
    return OpenService(
        guard=ctx.guard,
        derived_guard=ctx.workspace.derived_guard,
        reserved_derived=ctx.workspace.reserved_derived,
        jobs=ctx.jobs,
        sessions=ctx.open_sessions,
        workspace_root=ctx.settings.workspace_root,
        cache_max_gb=ctx.settings.cache_max_gb,
    )


@router.post("/open", response_model=open_mode.OpenSession, status_code=201)
async def open_path(ctx: Ctx, body: PathBody) -> open_mode.OpenSession:
    """API-07: a file or folder → an ephemeral session, headers only (SRC-09)."""
    return await svc(ctx).open(body.path)


@router.get("/open/{sid}", response_model=open_mode.OpenSession)
def get_open(ctx: Ctx, sid: str) -> open_mode.OpenSession:
    return ctx.open_sessions.get(sid)


@router.delete("/open/{sid}", status_code=204)
def close_open(ctx: Ctx, sid: str) -> Response:
    ctx.open_sessions.drop(sid)
    return Response(status_code=204)


@router.get(
    "/open/{sid}/items/{n}/image",
    response_class=Response,
    responses=_VOLUME,
    summary="Open-mode volume bytes (NIfTI; NumPy converted into .scratch/)",
)
async def open_image(
    ctx: Ctx,
    sid: str,
    n: int,
    request: Request,
    axis_order: Literal["xyz", "zyx"] | None = None,
) -> Response:
    """API-08. NumPy without a decisive order → `ambiguous-axis-order` (SRC-12)."""
    path, etag = await svc(ctx).volume(sid, n, axis_order)
    name = path.name if path.name != "volume.nii.gz" else f"open-{n}.nii.gz"
    return streaming.volume_response(path, etag, name, request)


@router.get("/open/{sid}/items/{n}/dicom-tags", response_model=dict[str, Any])
async def open_dicom_tags(ctx: Ctx, sid: str, n: int) -> dict[str, Any]:
    """Header info for a DICOM item (VW-22): its first file's DICOM JSON, never PixelData."""
    return await svc(ctx).dicom_tags(sid, n)


@router.get(
    "/open/{sid}/items/{n}/preview",
    response_class=Response,
    responses=_PNG,
    summary="NumPy middle slice in one axis order (the Open dialog, SRC-12)",
)
async def open_preview(
    ctx: Ctx, sid: str, n: int, axis_order: Literal["xyz", "zyx"] = "xyz"
) -> Response:
    png = await svc(ctx).preview_png(sid, n, axis_order)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.post("/open/{sid}/items/{n}/attach", response_model=open_mode.OpenSession)
async def open_attach(ctx: Ctx, sid: str, n: int, body: PathBody) -> open_mode.OpenSession:
    """API-08 attach (SRC-10, ADR-0027): a segmentation for item n from anywhere under
    ALLOWED_DATA_ROOTS, only if the geometry matches."""
    return await svc(ctx).attach(sid, n, body.path)


@router.post("/open/{sid}/items/{n}/save", response_model=Saved, status_code=201)
async def open_save(ctx: Ctx, sid: str, n: int, body: SaveBody) -> Saved:
    """SRC-14: write the open volume as a new `.nii.gz` under ALLOWED_DERIVED_ROOTS, once."""
    return await svc(ctx).save(sid, n, body)
