"""API-23/24/26 image/mask bytes, thumbnails (BE-04, IMP-10, IMP-12)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Request, Response

from app.api.v1.deps import Ctx
from app.context import AppContext
from app.core.cache_budget import touch
from app.core.errors import NotFound, SourceMissing
from app.imaging import npy_convert, streaming, thumbnails
from app.imaging.fingerprint import quick_fingerprint

router = APIRouter(tags=["volumes"])

_VOLUME_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"content": {streaming.VOLUME_MEDIA_TYPE: {}}, "description": "Original file bytes"},
    206: {"description": "Partial content (HTTP Range)"},
    304: {"description": "Not modified (If-None-Match)"},
}
_THUMB_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"content": {streaming.WEBP_MEDIA_TYPE: {}}, "description": "WebP thumbnail"},
    304: {"description": "Not modified (If-None-Match)"},
}


async def _serve(
    ctx: AppContext,
    pid: str,
    iid: str,
    kind: Literal["image", "mask"],
    request: Request,
    seg: str | None = None,
) -> Response:
    item = ctx.index.get_item(pid, iid)
    if kind == "image":
        vol = item.image
        if vol is None:
            raise NotFound("item has no image")
    else:
        seg_id = seg or ctx.workspace.get(pid).default_seg  # ADR-0015
        vol = item.masks.get(seg_id)
        if vol is None:
            raise NotFound(f"item has no mask in segmentation set {seg_id!r}")
    path = ctx.workspace.resolver(pid).resolve(vol.ref)
    if not path.is_file():
        raise SourceMissing(f"{kind} file is missing")
    fp = await asyncio.to_thread(quick_fingerprint, path)
    name = path.name
    if vol.format == "npy":
        name = npy_convert.nifti_name(name)
        if streaming.is_not_modified(request, fp):
            return streaming.not_modified(streaming.quote_etag(fp))
        spacing = item.geometry.spacing if item.geometry is not None else [1.0, 1.0, 1.0]
        order = npy_convert.axis_order_of(item.extra.get("axis_order")) or "xyz"  # IMP-10
        dst = npy_convert.cache_path(ctx.workspace.project_dir(pid), fp, order)
        cached = dst.is_file()
        path = await npy_convert.ensure_nifti(ctx.jobs, path, dst, spacing, order)
        if not cached:
            ctx.cache_written()
    return streaming.volume_response(path, fp, name, request)


@router.get(
    "/projects/{pid}/items/{iid}/image",
    response_class=Response,
    responses=_VOLUME_RESPONSES,
    summary="Image bytes (Range, ETag)",
)
async def get_image(pid: str, iid: str, request: Request, ctx: Ctx) -> Response:
    return await _serve(ctx, pid, iid, "image", request)


@router.head("/projects/{pid}/items/{iid}/image", include_in_schema=False)
async def head_image(pid: str, iid: str, request: Request, ctx: Ctx) -> Response:
    return await _serve(ctx, pid, iid, "image", request)


@router.get(
    "/projects/{pid}/items/{iid}/mask",
    response_class=Response,
    responses=_VOLUME_RESPONSES,
    summary="Mask bytes of one segmentation set (Range, ETag; default `default_seg`)",
)
async def get_mask(
    pid: str, iid: str, request: Request, ctx: Ctx, seg: str | None = None
) -> Response:
    return await _serve(ctx, pid, iid, "mask", request, seg)


@router.head("/projects/{pid}/items/{iid}/mask", include_in_schema=False)
async def head_mask(
    pid: str, iid: str, request: Request, ctx: Ctx, seg: str | None = None
) -> Response:
    return await _serve(ctx, pid, iid, "mask", request, seg)


@router.get(
    "/projects/{pid}/items/{iid}/thumbnail",
    response_class=Response,
    responses=_THUMB_RESPONSES,
    summary="WebP thumbnail (404 until generated)",
)
async def get_thumbnail(pid: str, iid: str, request: Request, ctx: Ctx) -> Response:
    item = ctx.index.get_item(pid, iid)
    fp = item.image.fp if item.image is not None else None
    if fp is None:
        raise NotFound("thumbnail not generated")
    path = thumbnails.thumb_path(ctx.workspace.project_dir(pid), fp)
    if not path.is_file():
        # evicted by CACHE_MAX_GB (or never made): the next thumbnail pass renders it again
        await thumbnails.regenerate_soon(ctx.workspace, ctx.index, ctx.jobs, pid)
        raise NotFound("thumbnail not generated")
    touch(path)  # LRU use (AUD-A4-16)
    return streaming.webp_response(path, fp, request)
