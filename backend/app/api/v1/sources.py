"""API-19 source detection and API-07/08 Open mode (SRC-01..13)."""

from __future__ import annotations

import asyncio
import gzip
import shutil
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.api.v1.deps import Ctx
from app.core.errors import (
    DerivedRootRequired,
    NotFound,
    SourceMissing,
    UnsupportedFormat,
    ValidationProblem,
)
from app.imaging import npy_convert, streaming
from app.sources import formats
from app.sources import open as open_mode
from app.sources.detect import DetectResult, detect
from app.tasks import dicom_stage

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


# One conversion per scratch target at a time: the viewer's image request and "Save as NIfTI…"
# often ask for the same DICOM volume together; the second caller awaits the first.
_converting: dict[str, asyncio.Future[str | None]] = {}


async def _convert_once(ctx: Ctx, root: str, files: list[str], dst: Path) -> str | None:
    key = str(dst)
    running = _converting.get(key)
    if running is not None:
        return await asyncio.shield(running)
    fut: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
    _converting[key] = fut
    try:
        err: str | None = await ctx.jobs.run_in_worker(dicom_stage.convert_series, root, files, key)
        fut.set_result(err)
        return err
    except BaseException as exc:
        fut.set_exception(exc)
        fut.exception()  # retrieved: waiters re-raise it, no "never retrieved" warning
        raise
    finally:
        del _converting[key]


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
    if it.format == "dicom":  # SRC-13: the convert stage into `.scratch/` only
        dst = open_mode.scratch_dir(ctx.settings.workspace_root, fp, "dicom") / "volume.nii.gz"
        if not dst.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            err = await _convert_once(ctx, s.root, it.files or [it.rel], dst)
            if err is not None or not dst.is_file():
                raise UnsupportedFormat(f"{it.name}: cannot convert ({err})")
            await asyncio.to_thread(
                open_mode.purge_scratch, ctx.settings.workspace_root, ctx.settings.cache_max_gb
            )
        return dst, f"{fp}.dicom"
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


@router.get("/open/{sid}/items/{n}/dicom-tags", response_model=dict[str, Any])
async def open_dicom_tags(ctx: Ctx, sid: str, n: int) -> dict[str, Any]:
    """Header info for a DICOM item (VW-22): its first file's DICOM JSON, never PixelData."""
    s = ctx.open_sessions.get(sid)
    it = open_mode.item(s, n)
    if it.format != "dicom":
        raise NotFound(f"{it.name} has no DICOM header")
    src = open_mode.source_path(s, it)
    ctx.guard.check(src)
    tags: dict[str, Any] = await ctx.jobs.run_in_worker(dicom_stage.dicom_tags, s.root, it.rel)
    return tags


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
    if not real.is_file() or formats.classify(real) != "nifti":
        raise UnsupportedFormat(
            "Attach a NIfTI segmentation (.nii or .nii.gz)", actions=["choose_another_path"]
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
        format="nifti",
        kind="label",
        geometry=geo,
        n_slices=geo.shape[2],
        attached_to=n,
    )
    s.items.append(new)
    return s


class SaveBody(BaseModel):
    """API-09 (SRC-14)."""

    dest_dir: str | None = None  # default: {first ALLOWED_DERIVED_ROOTS}/_open/{YYYY-MM-DD}/
    sidecar: bool = True  # DICOM only (DCM-04)
    anonymize: Literal["none", "basic"] = "none"  # sidecar (DCM-05, NFR-17)
    axis_order: Literal["xyz", "zyx"] | None = None  # NumPy without a decided order


class Saved(BaseModel):
    path: str
    sidecar_path: str | None = None


@router.post("/open/{sid}/items/{n}/save", response_model=Saved, status_code=201)
async def open_save(ctx: Ctx, sid: str, n: int, body: SaveBody) -> Saved:
    """SRC-14: write the open volume as a new `.nii.gz` under ALLOWED_DERIVED_ROOTS, once."""
    guard = ctx.workspace.derived_guard
    if not guard.allowed_roots:
        raise DerivedRootRequired(
            "ALLOWED_DERIVED_ROOTS is empty: there is no folder to save into (OPS-11)",
            actions=["configure:ALLOWED_DERIVED_ROOTS"],
        )
    if body.dest_dir:
        dest = Path(body.dest_dir)
        if not dest.is_absolute():
            raise ValidationProblem("dest_dir must be absolute")
    else:
        dest = guard.allowed_roots[0] / "_open" / date.today().isoformat()
    dest_real = guard.check(dest)  # inside ALLOWED_DERIVED_ROOTS, never next to a source (R1)
    s = ctx.open_sessions.get(sid)
    it = open_mode.item(s, n)
    volume, _ = await _nifti_path(ctx, sid, n, body.axis_order)
    await asyncio.to_thread(dest_real.mkdir, parents=True, exist_ok=True)
    series_dir = (Path(s.root) / it.rel).parent.name
    stem = formats.stem(it.name) if it.format != "dicom" else series_dir or "dicom"
    stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem) or "volume"
    tmp = dest_real / f".{uuid.uuid4().hex}.tmp"
    await asyncio.to_thread(_gz_copy, volume, tmp)
    out = await asyncio.to_thread(dicom_stage.link_new, tmp, dest_real, stem, ".nii.gz")
    side: str | None = None
    if it.format == "dicom" and body.sidecar:
        side_tmp = dest_real / f".{uuid.uuid4().hex}.json.tmp"
        src = Path(s.root) / (it.files[0] if it.files else it.rel)
        err = await ctx.jobs.run_in_worker(
            dicom_stage.write_sidecar, str(src), str(side_tmp), body.anonymize == "basic", stem
        )
        if err is not None:
            raise UnsupportedFormat(f"sidecar: {err}")
        name = out.name[: -len(".nii.gz")]
        side_path = await asyncio.to_thread(
            dicom_stage.link_new, side_tmp, dest_real, name, ".dicom.json"
        )
        side = str(side_path)
    return Saved(path=str(out), sidecar_path=side)


def _gz_copy(src: Path, dst: Path) -> None:
    """`.nii.gz` bytes as-is; a plain `.nii` is gzipped (never modifies the source, R1)."""
    with src.open("rb") as fh:
        head = fh.read(2)
        fh.seek(0)
        with dst.open("xb") as out:
            if head == b"\x1f\x8b":
                shutil.copyfileobj(fh, out)
            else:
                with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
                    shutil.copyfileobj(fh, gz)
