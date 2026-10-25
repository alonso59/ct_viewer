"""Open-mode service: open, volume bytes, attach, Save as NIfTI.

Every refusal carries its cause and next actions. Nothing here writes to a source root:
DICOM/NumPy go to the disposable `.scratch/open/`, saves to ALLOWED_DERIVED_ROOTS.
"""

from __future__ import annotations

import asyncio
import gzip
import shutil
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from app.config import Settings
from app.core.cache_budget import touch
from app.core.errors import (
    DerivedRootRequired,
    NotFound,
    PathOutsideRoot,
    SourceMissing,
    UnsupportedFormat,
    ValidationProblem,
)
from app.core.paths import PathGuard, is_within
from app.imaging import npy_convert
from app.imaging.fingerprint import quick_fingerprint
from app.jobs.manager import JobManager
from app.sources import formats
from app.sources import open as om
from app.tasks import dicom_stage

AxisOrder = Literal["xyz", "zyx"]
RETRY = ["choose_another_path", "home"]
NOT_SHARED = (
    "The server does not share this folder with the app. Choose a file or folder inside one "
    "of the shared folders (the Open dialog lists them)."
)


class SaveBody(BaseModel):
    dest_dir: str | None = None  # default: {first ALLOWED_DERIVED_ROOTS}/_open/{YYYY-MM-DD}/
    sidecar: bool = True  # DICOM only
    anonymize: Literal["none", "basic"] = "none"
    axis_order: AxisOrder | None = None  # NumPy without a decided order


class Saved(BaseModel):
    path: str
    sidecar_path: str | None = None


# One conversion per scratch target at a time: the viewer's image request and "Save as NIfTI…"
# often ask for the same DICOM volume together; the second caller awaits the first.
_converting: dict[str, asyncio.Future[str | None]] = {}


async def convert_once(
    jobs: JobManager,
    root: str,
    files: list[str],
    dst: Path,
    *,
    settings: Settings | None = None,
    expected_fingerprint: str | None = None,
) -> str | None:
    key = str(dst)
    running = _converting.get(key)
    if running is not None:
        return await asyncio.shield(running)
    fut: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
    _converting[key] = fut
    try:
        if settings is None:
            err: str | None = await jobs.run_in_worker(dicom_stage.convert_series, root, files, key)
        else:
            from app.tasks.dicom_open import convert_volume

            err = await convert_volume(
                settings, root, files, dst, expected_fingerprint=expected_fingerprint
            )
        fut.set_result(err)
        return err
    except BaseException as exc:
        fut.set_exception(exc)
        fut.exception()  # retrieved: waiters re-raise it, no "never retrieved" warning
        raise
    finally:
        del _converting[key]


def gz_copy(src: Path, dst: Path) -> None:
    """`.nii.gz` bytes as-is; a plain `.nii` is gzipped (never modifies the source)."""
    with src.open("rb") as fh:
        head = fh.read(2)
        fh.seek(0)
        with dst.open("xb") as out:
            if head == b"\x1f\x8b":
                shutil.copyfileobj(fh, out)
            else:
                with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
                    shutil.copyfileobj(fh, gz)


def guarded_source(guard: PathGuard, raw: str) -> Path:
    """An absolute, readable path under ALLOWED_DATA_ROOTS, else a problem with actions."""
    p = Path(raw)
    if not p.is_absolute():
        raise ValidationProblem(
            "path must be absolute",
            errors=[{"loc": ["body", "path"], "msg": "not absolute"}],
            actions=RETRY,
        )
    try:
        real = guard.check(p)
    except PathOutsideRoot:
        raise PathOutsideRoot(NOT_SHARED, actions=RETRY) from None
    if not real.exists():
        raise NotFound(f"{p.name or p} does not exist (moved, renamed or deleted?)", actions=RETRY)
    return real


class OpenService:
    def __init__(
        self,
        *,
        guard: PathGuard,
        derived_guard: PathGuard,
        reserved_derived: Callable[[], tuple[Path, ...]],
        jobs: JobManager,
        sessions: om.OpenSessions,
        workspace_root: Path,
        settings: Settings,
        on_cache_write: Callable[[], None],
        restore_session: Callable[[str], om.OpenSession] | None = None,
        persist_session: Callable[[om.OpenSession], None] = lambda _: None,
    ) -> None:
        self.guard = guard
        self.derived_guard = derived_guard
        self.reserved_derived = reserved_derived
        self.jobs = jobs
        self.sessions = sessions
        self.workspace_root = workspace_root
        self.settings = settings
        self.restore_session = restore_session
        self.persist_session = persist_session
        self.on_cache_write = on_cache_write  # CACHE_MAX_GB sweep

    def session(self, sid: str) -> om.OpenSession:
        try:
            return self.sessions.get(sid)
        except NotFound as ended:
            if self.restore_session is None:
                raise
            try:
                restored = self.restore_session(sid)
            except NotFound:
                raise ended from None
            self.sessions.put(restored)
            return restored

    def guarded(self, raw: str) -> Path:
        return guarded_source(self.guard, raw)

    async def open(self, raw: str) -> om.OpenSession:
        real = self.guarded(raw)
        if real.is_file():
            scan = await asyncio.to_thread(formats.scan, real.parent, [real.name])
            if formats.classify(real) is None:
                raise om.refuse_empty(real, scan)
        else:
            scan = await asyncio.to_thread(formats.scan, real)
        rels = om.accepted(scan)
        if not rels:
            raise om.refuse_empty(real, scan)
        kinds = {rel: kind for kind, files in scan.files.items() for rel in files}
        rows = await self.jobs.run_in_worker(om.probe, str(scan.root), rels, kinds)
        modalities = await asyncio.to_thread(om.row_modalities, scan.root)
        session = om.build_session(real, rows, scan, modalities)
        self.sessions.put(session)
        return om.preview(session)

    async def volume(self, sid: str, n: int, axis_order: str | None) -> tuple[Path, str]:
        """The item as NIfTI (NumPy/DICOM converted into `.scratch/`) and its ETag."""
        s = await asyncio.to_thread(self.session, sid)
        it = om.item(s, n)
        src = om.source_path(s, it)
        if not src.is_file():
            raise SourceMissing(f"{it.name} is missing", actions=RETRY)
        self.guard.check(src)
        if it.error:
            raise UnsupportedFormat(it.error, actions=RETRY)
        if it.format == "nifti":
            fp = await asyncio.to_thread(quick_fingerprint, src)
            return src, fp
        if it.format == "dicom":
            try:
                fp = await self.jobs.run_in_worker(
                    dicom_stage.series_fingerprint, s.root, it.files or [it.rel]
                )
            except (OSError, ValueError):
                raise UnsupportedFormat(
                    "DICOM series changed or a member cannot be read safely; reopen the source",
                    actions=RETRY,
                ) from None
            dst = om.scratch_dir(self.workspace_root, fp, "dicom") / "volume.nii.gz"
            if not dst.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                err = await convert_once(
                    self.jobs,
                    s.root,
                    it.files or [it.rel],
                    dst,
                    settings=self.settings,
                    expected_fingerprint=fp,
                )
                if err is not None or not dst.is_file():
                    raise UnsupportedFormat(f"{it.name}: cannot convert ({err})", actions=RETRY)
                self.on_cache_write()
            else:
                touch(dst)
            return dst, f"{fp}.dicom"
        fp = await asyncio.to_thread(quick_fingerprint, src)
        order = om.need_axis_order(it, axis_order)
        geo = it.geometry
        spacing = geo.spacing if geo else [1.0, 1.0, 1.0]
        dst = om.scratch_dir(self.workspace_root, fp, order) / "volume.nii.gz"
        cached = dst.is_file()
        out = await npy_convert.ensure_nifti(
            self.jobs, src, dst, spacing, order, geo.affine if geo else None
        )
        if not cached:
            self.on_cache_write()
        return out, f"{fp}.{order}"

    async def dicom_tags(self, sid: str, n: int) -> dict[str, Any]:
        s = await asyncio.to_thread(self.session, sid)
        it = om.item(s, n)
        if it.format != "dicom":
            raise NotFound(f"{it.name} has no DICOM header")
        self.guard.check(om.source_path(s, it))
        tags: dict[str, Any] = await self.jobs.run_in_worker(dicom_stage.dicom_tags, s.root, it.rel)
        return tags

    async def preview_png(self, sid: str, n: int, axis_order: AxisOrder) -> bytes:
        s = await asyncio.to_thread(self.session, sid)
        it = om.item(s, n)
        if it.format != "npy":
            raise ValidationProblem("Axis-order previews exist for NumPy arrays only")
        src = om.source_path(s, it)
        png: bytes = await self.jobs.run_in_worker(om.middle_slice_png, str(src), axis_order)
        return png

    async def attach(self, sid: str, n: int, raw: str) -> om.OpenSession:
        """A NIfTI segmentation from anywhere under ALLOWED_DATA_ROOTS; the geometry check (same
        shape, affines within tolerance) is the guard, never resampled."""
        s = await asyncio.to_thread(self.session, sid)
        image = om.item(s, n)
        real = self.guarded(raw)
        if not real.is_file() or formats.classify(real) != "nifti":
            raise UnsupportedFormat(
                "Attach a NIfTI segmentation (.nii or .nii.gz)", actions=["choose_another_path"]
            )
        try:
            before = real.stat()
            rows = await self.jobs.run_in_worker(om.probe, str(real.parent), [real.name])
            after = real.stat()
        except OSError:
            raise SourceMissing(
                "Mask became unavailable while reading its geometry; attach it again", actions=RETRY
            ) from None
        if (before.st_size, before.st_mtime_ns, before.st_dev, before.st_ino) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_dev,
            after.st_ino,
        ):
            raise SourceMissing(
                "Mask changed while reading its geometry; attach it again", actions=RETRY
            )
        row = rows[0]
        if row.get("error") or not row.get("geometry"):
            raise UnsupportedFormat(
                f"{real.name} cannot be read as NIfTI: {row.get('error') or 'no header'}",
                actions=["choose_another_path"],
            )
        geo = om.OpenGeometry.model_validate(row["geometry"])
        om.check_attach(image, geo)
        result = om.add_label(s, n, real, geo)
        self.persist_session(result)
        return result

    def _dest(self, raw: str | None) -> Path:
        guard = self.derived_guard
        if not guard.allowed_roots:
            raise DerivedRootRequired(
                "ALLOWED_DERIVED_ROOTS is empty: there is no folder to save into",
                actions=["configure:ALLOWED_DERIVED_ROOTS"],
            )
        if raw:
            dest = Path(raw)
            if not dest.is_absolute():
                raise ValidationProblem("dest_dir must be absolute")
        else:
            dest = guard.allowed_roots[0] / "_open" / date.today().isoformat()
        try:
            real = guard.check(dest)  # inside ALLOWED_DERIVED_ROOTS, never next to a source
        except PathOutsideRoot:
            raise PathOutsideRoot(
                "Save into a folder under the derived folders (ALLOWED_DERIVED_ROOTS)",
                actions=["choose_another_path"],
            ) from None
        if any(is_within(real, r) for r in self.reserved_derived()):
            raise PathOutsideRoot(  # datasets and project task folders have one writer
                "Choose a folder outside workspace datasets (_datasets/) and project task folders",
                actions=["choose_another_path"],
            )
        return real

    async def save(self, sid: str, n: int, body: SaveBody) -> Saved:
        """Write the open volume as a new `.nii.gz` under ALLOWED_DERIVED_ROOTS, once."""
        dest = self._dest(body.dest_dir)
        s = await asyncio.to_thread(self.session, sid)
        it = om.item(s, n)
        volume, fp = await self.volume(sid, n, body.axis_order)
        await asyncio.to_thread(dest.mkdir, parents=True, exist_ok=True)
        if body.anonymize == "basic":  # neither the file name nor the sidecar names the patient
            stem = om.pseudonym(fp)
        else:
            series_dir = om.source_path(s, it).parent.name
            stem = formats.stem(it.name) if it.format != "dicom" else series_dir or "dicom"
            stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem) or "volume"
        tmp = dest / f".{uuid.uuid4().hex}.tmp"
        await asyncio.to_thread(gz_copy, volume, tmp)
        out = await asyncio.to_thread(dicom_stage.link_new, tmp, dest, stem, ".nii.gz")
        side: str | None = None
        if it.format == "dicom" and body.sidecar:
            side_tmp = dest / f".{uuid.uuid4().hex}.json.tmp"
            src = Path(s.root) / (it.files[0] if it.files else it.rel)
            err = await self.jobs.run_in_worker(
                dicom_stage.write_sidecar, str(src), str(side_tmp), body.anonymize == "basic", stem
            )
            if err is not None:
                raise UnsupportedFormat(f"sidecar: {err}")
            name = out.name[: -len(".nii.gz")]
            side_path = await asyncio.to_thread(
                dicom_stage.link_new, side_tmp, dest, name, ".dicom.json"
            )
            side = str(side_path)
        return Saved(path=str(out), sidecar_path=side)
