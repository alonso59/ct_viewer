"""Thumbnail job (IMP-12, UI-08): 128 px mid-axial WebP at the default W/L with mask outlines.

`render` / `render_batch` run in job workers (BE-12): sources are read-only (R1) and output
goes to `cache/thumbs/{image_fp}.webp` (PRJ-10). `schedule_thumbnails` runs in the API process
after an index rebuild.
"""

from __future__ import annotations

import io
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import nibabel as nib
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from app.core.errors import JobConflict, Problem
from app.core.redact import Redactor
from app.imaging.npy_convert import CACHE_DIR, atomic_write_cache
from app.jobs.types import JobInfo, JobSpec, WorkUnit

if TYPE_CHECKING:
    from app.ingest.store import IndexStore
    from app.jobs.manager import JobManager
    from app.projects.service import Workspace

log = logging.getLogger("app.imaging.thumbnails")

THUMB_SIZE = 128
BATCH = 8
RGB = tuple[int, int, int]
# (image_path, mask_path, out_path, ww, wl, colors)
RenderTask = tuple[str, str | None, str, float, float, dict[int, RGB]]


def thumb_path(project_dir: Path, image_fp: str) -> Path:
    return project_dir / CACHE_DIR / "thumbs" / f"{image_fp}.webp"


def hex_to_rgb(color: str) -> RGB:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _axial_slice(path: str) -> tuple[NDArray[Any], tuple[float, float]]:
    """Mid-axial slice in RAS as `[x, y]` plus its (x, y) spacing; reads one slab only."""
    img: Any = nib.load(path)
    if len(img.shape) < 3:
        raise ValueError(f"expected a 3D volume, got shape {img.shape}")
    affine = np.asarray(img.affine, dtype=float)
    ornt = nib.orientations.io_orientation(affine)  # per input axis: (RAS axis, flip)
    axes = [int(a) for a in ornt[:, 0]]
    flips = [ornt[i, 1] < 0 for i in range(3)]
    zooms = np.sqrt((affine[:3, :3] ** 2).sum(axis=0))
    z_in = axes.index(2)
    n = int(img.shape[z_in])
    mid = (n - 1) // 2
    idx = n - 1 - mid if flips[z_in] else mid
    slicer: list[Any] = [slice(None)] * 3
    slicer[z_in] = idx
    if len(img.shape) > 3:
        slicer += [0] * (len(img.shape) - 3)
    sl = np.asarray(img.dataobj[tuple(slicer)])
    a, b = (i for i in range(3) if i != z_in)
    if flips[a]:
        sl = sl[::-1, :]
    if flips[b]:
        sl = sl[:, ::-1]
    if axes[a] == 1:  # first remaining axis is anterior-posterior: put x first
        sl = sl.T
        a, b = b, a
    return sl, (float(zooms[a]), float(zooms[b]))


def _window(sl: NDArray[Any], ww: float, wl: float) -> NDArray[np.uint8]:
    width = ww if ww > 0 else 1.0
    lo = wl - width / 2
    v = (np.nan_to_num(sl.astype(np.float32)) - lo) / width
    return np.asarray(np.clip(v * 255.0 + 0.5, 0, 255), dtype=np.uint8)


def _display(xy: NDArray[Any]) -> NDArray[Any]:
    """RAS `[x, y]` → rows=y (anterior up), cols=x (patient right on image left)."""
    return np.ascontiguousarray(xy.T[::-1, ::-1])


def _boundaries(lab: NDArray[Any]) -> NDArray[np.bool_]:
    """1-px inner outline of every label region (4-neighbourhood)."""
    p = np.pad(lab, 1, mode="edge")
    c = p[1:-1, 1:-1]
    diff = (c != p[:-2, 1:-1]) | (c != p[2:, 1:-1]) | (c != p[1:-1, :-2]) | (c != p[1:-1, 2:])
    edge = np.zeros_like(diff)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    return np.asarray((diff | edge) & (c > 0), dtype=np.bool_)


def render(
    image_path: str,
    mask_path: str | None,
    out_path: str,
    ww: float,
    wl: float,
    colors: dict[int, tuple[int, int, int]],
    size: int = THUMB_SIZE,
) -> str | None:
    """Worker: write the WebP thumbnail. Returns None on success or an error string."""
    try:
        img_xy, (sx, sy) = _axial_slice(image_path)
        gray = _display(_window(img_xy, ww, wl))
        h0, w0 = gray.shape
        scale = size / max(w0 * sx, h0 * sy)
        w = max(1, round(w0 * sx * scale))
        h = max(1, round(h0 * sy * scale))
        rgb = Image.fromarray(gray).resize((w, h), Image.Resampling.BILINEAR)
        out = np.array(rgb.convert("RGB"))
        if mask_path is not None:
            m_xy, _ = _axial_slice(mask_path)
            if m_xy.shape == img_xy.shape:
                lab = _display(np.rint(np.nan_to_num(m_xy)).astype(np.int32))
                lab_img = Image.fromarray(lab).resize((w, h), Image.Resampling.NEAREST)
                lab_r = np.asarray(lab_img, dtype=np.int32)
                edge = _boundaries(lab_r)
                for value, color in colors.items():
                    out[edge & (lab_r == value)] = color
        buf = io.BytesIO()
        Image.fromarray(out).save(buf, format="WEBP", lossless=True)  # crisp 1-px outlines
        atomic_write_cache(Path(out_path), buf.getvalue())
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def render_batch(tasks: Sequence[RenderTask]) -> list[str | None]:
    """Worker: one WorkUnit = a batch of `render` calls; returns one result per task."""
    return [render(*t) for t in tasks]


def _result_logger(red: Redactor) -> Callable[[Any], Awaitable[None]]:
    """Failures are logged with alias refs, never absolute paths (NFR-17, AUD-A5-16)."""

    async def log_result(result: Any) -> None:
        failed = [r for r in result if r is not None] if isinstance(result, list) else []
        if failed:
            first = red.text(str(failed[0]))
            log.warning("thumbnails failed", extra={"n_failed": len(failed), "first": first})

    return log_result


async def schedule_thumbnails(
    workspace: Workspace, store: IndexStore, jobs: JobManager, project_id: str
) -> JobInfo | None:
    """Submit a `thumbnail` job for complete, active items without a thumbnail (IMP-12)."""
    if jobs.active(project_id, "thumbnail") is not None:
        return None
    cfg = workspace.get(project_id)
    pdir = workspace.project_dir(project_id)
    resolver = workspace.resolver(project_id)
    ww, wl = cfg.display.ct_window()
    colors = {e.value: hex_to_rgb(e.color) for e in cfg.label_map}
    tasks: dict[str, RenderTask] = {}
    for item in store.load(project_id).items:
        img = item.image
        if (
            item.scope != "complete"
            or item.status != "active"
            or img is None
            or img.fp is None
            or img.format != "nifti"
        ):
            continue
        out = thumb_path(pdir, img.fp)
        if str(out) in tasks or out.exists():
            continue
        try:
            img_path = resolver.resolve(img.ref)
        except Problem:
            continue
        mask_path: str | None = None
        if item.mask is not None and item.mask.format == "nifti" and item.mask.fp is not None:
            try:
                mask_path = str(resolver.resolve(item.mask.ref))
            except Problem:
                mask_path = None
        tasks[str(out)] = (str(img_path), mask_path, str(out), ww, wl, colors)
    if not tasks:
        return None
    todo = list(tasks.values())
    units = [WorkUnit(render_batch, (todo[i : i + BATCH],)) for i in range(0, len(todo), BATCH)]
    on_result = _result_logger(Redactor(aliases=[(r.alias, r.path) for r in cfg.path_roots]))
    try:
        return jobs.submit(
            JobSpec(project_id=project_id, kind="thumbnail", units=units, on_result=on_result)
        )
    except JobConflict:
        return None


_last_regen: dict[str, float] = {}
REGEN_THROTTLE_S = 30.0


async def regenerate_soon(
    workspace: Workspace, store: IndexStore, jobs: JobManager, project_id: str
) -> None:
    """A thumbnail was asked for but is missing (evicted by CACHE_MAX_GB, AUD-A4-16): schedule
    the idempotent pass again, at most once per `REGEN_THROTTLE_S` per project."""
    now = time.monotonic()
    if now - _last_regen.get(project_id, float("-inf")) < REGEN_THROTTLE_S:
        return
    _last_regen[project_id] = now
    try:
        await schedule_thumbnails(workspace, store, jobs, project_id)
    except Exception:
        log.exception("thumbnail scheduling failed", extra={"project_id": project_id})


def after_index_hook(
    workspace: Workspace, store: IndexStore, jobs: JobManager
) -> Callable[[str], Awaitable[None]]:
    """`AppContext.after_index` adapter: schedules thumbnails, never fails the index job."""

    async def hook(project_id: str) -> None:
        try:
            await schedule_thumbnails(workspace, store, jobs, project_id)
        except Exception:
            log.exception("thumbnail scheduling failed", extra={"project_id": project_id})

    return hook
