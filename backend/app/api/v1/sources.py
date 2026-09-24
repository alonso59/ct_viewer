"""API-19 source detection and API-07/08 Open mode (SRC-01..13)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.api.v1.deps import Ctx
from app.core.errors import NotFound, SourceMissing, UnsupportedFormat, ValidationProblem
from app.imaging import npy_convert, streaming
from app.sources import formats
from app.sources import open as open_mode
from app.sources.detect import DetectResult, detect

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


def _guarded(ctx: Ctx, raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        raise ValidationProblem(
            "path must be absolute", errors=[{"loc": ["body", "path"], "msg": "not absolute"}]
        )
    real = ctx.guard.check(p)
    if not real.exists():
        raise NotFound("Path not found")
    return real


@router.post("/sources/detect", response_model=DetectResult)
async def detect_source(ctx: Ctx, body: PathBody) -> DetectResult:
    """API-19: candidate adapters with reasons, counts and confidence (SRC-01/02)."""
    real = _guarded(ctx, body.path)
    available = "dicom.convert" in ctx.registry.tasks
    return await asyncio.to_thread(detect, real, dicom_available=available)


@router.post("/open", response_model=open_mode.OpenSession, status_code=201)
async def open_path(ctx: Ctx, body: PathBody) -> open_mode.OpenSession:
    """API-07: a file or folder → an ephemeral session, headers only (SRC-09)."""
    real = _guarded(ctx, body.path)
    if real.is_file():
        scan = await asyncio.to_thread(formats.scan, real.parent, [real.name])
        if formats.classify(real) is None:
            raise open_mode.refuse_empty(real, scan)
    else:
        scan = await asyncio.to_thread(formats.scan, real)
    rels = open_mode.accepted(scan)
    if not rels:
        raise open_mode.refuse_empty(real, scan)
    rows = await ctx.jobs.run_in_worker(open_mode.probe, str(scan.root), rels)
    session = open_mode.build_session(real, rows, scan)
    ctx.open_sessions.put(session)
    return session


@router.get("/open/{sid}", response_model=open_mode.OpenSession)
def get_open(ctx: Ctx, sid: str) -> open_mode.OpenSession:
    return ctx.open_sessions.get(sid)


@router.delete("/open/{sid}", status_code=204)
def close_open(ctx: Ctx, sid: str) -> Response:
    ctx.open_sessions.drop(sid)
    return Response(status_code=204)


async def _nifti_path(ctx: Ctx, sid: str, n: int, axis_order: str | None) -> tuple[Path, str]:
    s = ctx.open_sessions.get(sid)
    it = open_mode.item(s, n)
    src = open_mode.source_path(s, it)
    if not src.is_file():
        raise SourceMissing(f"{it.name} is missing")
    ctx.guard.check(src)
    if it.error:
        raise UnsupportedFormat(it.error, actions=["choose_another_path"])
    fp = await asyncio.to_thread(open_mode.fingerprint, src)
    if it.format == "nifti":
        return src, fp
    order = open_mode.need_axis_order(it, axis_order)
    geo = it.geometry
    spacing = geo.spacing if geo else [1.0, 1.0, 1.0]
    dst = open_mode.scratch_dir(ctx.settings.workspace_root, fp, order) / "volume.nii.gz"
    out = await npy_convert.ensure_nifti(
        ctx.jobs, src, dst, spacing, order, geo.affine if geo else None
    )
    await asyncio.to_thread(
        open_mode.purge_scratch, ctx.settings.workspace_root, ctx.settings.cache_max_gb
    )
    return out, f"{fp}.{order}"


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
    path, etag = await _nifti_path(ctx, sid, n, axis_order)
    name = path.name if path.name != "volume.nii.gz" else f"open-{n}.nii.gz"
    return streaming.volume_response(path, etag, name, request)


@router.get(
    "/open/{sid}/items/{n}/preview",
    response_class=Response,
    responses=_PNG,
    summary="NumPy middle slice in one axis order (the Open dialog, SRC-12)",
)
async def open_preview(
    ctx: Ctx, sid: str, n: int, axis_order: Literal["xyz", "zyx"] = "xyz"
) -> Response:
    s = ctx.open_sessions.get(sid)
    it = open_mode.item(s, n)
    if it.format != "npy":
        raise ValidationProblem("Axis-order previews exist for NumPy arrays only")
    src = open_mode.source_path(s, it)
    png = await ctx.jobs.run_in_worker(open_mode.middle_slice_png, str(src), axis_order)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.post("/open/{sid}/items/{n}/attach", response_model=open_mode.OpenSession)
async def open_attach(ctx: Ctx, sid: str, n: int, body: PathBody) -> open_mode.OpenSession:
    """API-08 attach (SRC-10): a segmentation for item n, only if the geometry matches."""
    s = ctx.open_sessions.get(sid)
    image = open_mode.item(s, n)
    real = _guarded(ctx, body.path)
    if not real.is_file() or formats.classify(real) not in ("nifti", "npy"):
        raise UnsupportedFormat(
            "Attach a NIfTI or NumPy label map", actions=["choose_another_path"]
        )
    rows = await ctx.jobs.run_in_worker(open_mode.probe, str(real.parent), [real.name])
    row = rows[0]
    if row.get("error") or not row.get("geometry"):
        raise UnsupportedFormat(
            str(row.get("error") or "unreadable"), actions=["choose_another_path"]
        )
    geo = open_mode.OpenGeometry.model_validate(row["geometry"])
    open_mode.check_attach(image, geo)
    root = Path(s.root)
    rel = real.relative_to(root).as_posix() if real.is_relative_to(root) else None
    if rel is None:
        # outside the session root: keep a root-relative path by rebasing the session
        raise ValidationProblem(
            "Attach a segmentation from the opened folder (or open its folder)",
            actions=["open_folder"],
        )
    new = open_mode.OpenItem(
        n=len(s.items),
        item_id=f"open.{len(s.items)}",
        name=real.name,
        rel=rel,
        format="npy" if row["format"] == "npy" else "nifti",
        kind="label",
        geometry=geo,
        n_slices=geo.shape[2],
        attached_to=n,
        axis_order=row.get("axis_order"),
        needs_axis_order=bool(row.get("needs_axis_order")),
    )
    s.items.append(new)
    return s
