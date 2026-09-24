"""Open mode (SRC-09/10, API-07/08): view files without a project.

Sessions live in memory only: nothing is written to a project or to the workspace registry.
NumPy (and, with the converter, DICOM) volumes are converted into the disposable
`WORKSPACE_ROOT/.scratch/open/{fingerprint}/`, LRU-purged with `CACHE_MAX_GB`.
Headers and label sampling run in job workers (BE-12).
"""

from __future__ import annotations

import io
import shutil
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from app.core.errors import AmbiguousAxisOrder, GeometryMismatch, NotFound, UnsupportedFormat
from app.core.ids import new_ulid, utc_now
from app.imaging import npy_convert
from app.imaging.fingerprint import quick_fingerprint
from app.imaging.header import AFFINE_ATOL_MM, HeaderError, read_header
from app.sources import formats

MAX_ITEMS = 500
MAX_SESSIONS = 32
LABEL_MAX_VALUES = 256
OPEN_DIR = Path(".scratch") / "open"

ItemKind = Literal["image", "label"]


class OpenGeometry(BaseModel):
    shape: list[int]
    spacing: list[float]
    dtype: str
    orientation: str | None = None
    affine: list[list[float]] | None = None


class OpenItem(BaseModel):
    """An item-like record (`item_id` = `open.{n}`) from headers only."""

    n: int
    item_id: str
    name: str
    rel: str  # relative to the session root
    format: Literal["nifti", "npy", "dicom"]
    kind: ItemKind = "image"
    geometry: OpenGeometry | None = None
    modality: str | None = None  # from DICOM only; NIfTI/NumPy: unknown (VW-05 percentiles)
    n_slices: int | None = None
    attached_to: int | None = None
    axis_order: Literal["xyz", "zyx"] | None = None  # NumPy (SRC-12)
    needs_axis_order: bool = False
    error: str | None = None


class OpenSession(BaseModel):
    sid: str
    path: str
    root: str
    kind: Literal["file", "folder"]
    created_at: str
    items: list[OpenItem]
    truncated: bool = False
    ignored: dict[str, int] = Field(default_factory=dict)


# -- worker units ----------------------------------------------------------------------------


def _is_label(path: Path, fmt: str, axis_order: str) -> bool:
    """SOURCES §Formats: integer dtype with ≤ 256 distinct values in a header-guided sample."""
    if fmt == "npy":
        arr = np.load(path, mmap_mode="r", allow_pickle=False)
        if not np.issubdtype(arr.dtype, np.integer) and arr.dtype != np.bool_:
            return False
        k = arr.shape[0 if axis_order == "zyx" else 2] // 2
        sample = arr[k] if axis_order == "zyx" else arr[:, :, k]
    else:
        import nibabel as nib

        img: Any = nib.load(path)
        if not np.issubdtype(np.dtype(img.header.get_data_dtype()), np.integer):
            return False
        sample = np.asanyarray(img.dataobj[..., img.shape[2] // 2])
    return len(np.unique(np.asarray(sample))) <= LABEL_MAX_VALUES


def probe(root: str, rels: list[str]) -> list[dict[str, Any]]:
    """Worker: header + label check per accepted file (NIfTI, NumPy). Never raises."""
    out: list[dict[str, Any]] = []
    for rel in rels:
        path = Path(root) / rel
        fmt = formats.classify(path)
        row: dict[str, Any] = {"rel": rel, "format": fmt}
        try:
            if fmt == "npy":
                side = npy_convert.read_sidecar(path)
                spacing = side.get("spacing") or [1.0, 1.0, 1.0]
                raw = read_header(path, spacing=tuple(float(s) for s in spacing))
                ref_shape = None
                if isinstance(side.get("reference_ref"), str):
                    ref = (path.parent / side["reference_ref"]).resolve()
                    if ref.is_file() and ref.is_relative_to(Path(root).resolve()):
                        ref_shape = read_header(ref).shape
                order = npy_convert.decide_axis_order(raw.shape, side.get("axis_order"), ref_shape)
                row["axis_order"] = order
                row["needs_axis_order"] = order is None
                shape = list(reversed(raw.shape)) if order == "zyx" else list(raw.shape)
                aff = side.get("affine")
                row["geometry"] = {
                    "shape": shape,
                    "spacing": [float(s) for s in raw.spacing],
                    "dtype": raw.dtype,
                    "orientation": None,
                    "affine": aff if isinstance(aff, list) else None,
                }
                row["label"] = _is_label(path, "npy", order or "xyz")
            elif fmt == "nifti":
                h = read_header(path)
                row["geometry"] = {**h.geometry(), "affine": h.affine}
                row["label"] = _is_label(path, "nifti", "xyz")
            else:
                row["error"] = "DICOM opens with the DICOM converter (dicom.convert, SRC-13)"
        except (HeaderError, OSError, ValueError) as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        out.append(row)
    return out


def middle_slice_png(src: str, axis_order: str) -> bytes:
    """Worker: the middle axial slice of a `.npy` in one axis order, 1st-99th percentile (PNG)."""
    from PIL import Image

    arr = np.load(src, mmap_mode="r", allow_pickle=False)
    vol = np.transpose(arr, (2, 1, 0)) if axis_order == "zyx" else arr
    sl = np.asarray(vol[:, :, vol.shape[2] // 2], dtype=float).T[::-1]
    lo, hi = np.percentile(sl, [1, 99]) if sl.size else (0.0, 1.0)
    img = np.clip((sl - lo) / ((hi - lo) or 1.0) * 255, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


# -- sessions --------------------------------------------------------------------------------


class OpenSessions:
    """In-memory LRU of Open-mode sessions (API process)."""

    def __init__(self, max_sessions: int = MAX_SESSIONS) -> None:
        self._s: OrderedDict[str, OpenSession] = OrderedDict()
        self.max = max_sessions

    def put(self, s: OpenSession) -> None:
        self._s[s.sid] = s
        while len(self._s) > self.max:
            self._s.popitem(last=False)

    def get(self, sid: str) -> OpenSession:
        s = self._s.get(sid)
        if s is None:
            raise NotFound(
                f"Open session {sid!r} not found (sessions are not kept across restarts)"
            )
        self._s.move_to_end(sid)
        return s

    def drop(self, sid: str) -> None:
        self._s.pop(sid, None)


def build_session(path: Path, rows: list[dict[str, Any]], scan: formats.Scan) -> OpenSession:
    items: list[OpenItem] = []
    for n, r in enumerate(rows):
        geo = OpenGeometry.model_validate(r["geometry"]) if r.get("geometry") else None
        items.append(
            OpenItem(
                n=n,
                item_id=f"open.{n}",
                name=Path(r["rel"]).name,
                rel=r["rel"],
                format=r["format"],
                kind="label" if r.get("label") else "image",
                geometry=geo,
                n_slices=geo.shape[2] if geo else None,
                axis_order=r.get("axis_order"),
                needs_axis_order=bool(r.get("needs_axis_order")),
                error=r.get("error"),
            )
        )
    return OpenSession(
        sid=new_ulid(),
        path=str(path),
        root=str(scan.root),
        kind="file" if path.is_file() else "folder",
        created_at=utc_now(),
        items=items,
        truncated=scan.truncated or scan.n_accepted > MAX_ITEMS,
        ignored=dict(scan.ignored),
    )


def accepted(scan: formats.Scan) -> list[str]:
    rels = sorted(scan.files["nifti"] + scan.files["npy"] + scan.files["dicom"])
    return rels[:MAX_ITEMS]


def refuse_empty(path: Path, scan: formats.Scan) -> UnsupportedFormat:
    ignored = ", ".join(f"{n} {e}" for e, n in scan.ignored.most_common(5)) or "no files"
    extra = "; ".join(scan.refused.values())
    detail = f"Nothing to open in {path.name}: {ignored}" + (f". {extra}" if extra else "")
    return UnsupportedFormat(detail, actions=["choose_another_path"])


def item(session: OpenSession, n: int) -> OpenItem:
    if not 0 <= n < len(session.items):
        raise NotFound(f"Open item {n} not found")
    return session.items[n]


def source_path(session: OpenSession, it: OpenItem) -> Path:
    return Path(session.root) / it.rel


def scratch_dir(workspace_root: Path, fp: str, axis_order: str) -> Path:
    return workspace_root / OPEN_DIR / f"{fp}.{axis_order}"


def need_axis_order(it: OpenItem, chosen: str | None) -> Literal["xyz", "zyx"]:
    order = npy_convert.axis_order_of(chosen) or it.axis_order
    if order is None:
        raise AmbiguousAxisOrder(
            f"{it.name}: axis order unknown (no sidecar axis_order, no decisive reference_ref); "
            "pick xyz (nibabel) or zyx (SimpleITK) (SRC-12)",
            actions=["axis_order:xyz", "axis_order:zyx"],
        )
    return order


def check_attach(image: OpenItem, label: OpenGeometry) -> None:
    """SRC-10: same shape and affines within the IMP-08 tolerance; never resampled."""
    g = image.geometry
    if g is None:
        raise GeometryMismatch("The open image has no geometry")
    same_shape = list(g.shape) == list(label.shape)
    same_affine = True
    if g.affine is not None and label.affine is not None:
        same_affine = bool(
            np.allclose(np.asarray(g.affine), np.asarray(label.affine), atol=AFFINE_ATOL_MM)
        )
    if not (same_shape and same_affine):
        raise GeometryMismatch(
            f"Segmentation does not match the image: image shape {g.shape}, affine {g.affine}; "
            f"segmentation shape {label.shape}, affine {label.affine}. "
            "It is never resampled (SRC-10)",
            actions=["choose_another_path"],
        )


def purge_scratch(workspace_root: Path, max_gb: float) -> None:
    """LRU purge of `.scratch/open/` above `CACHE_MAX_GB` (oldest first)."""
    d = workspace_root / OPEN_DIR
    if not d.is_dir():
        return
    entries = []
    total = 0
    for sub in d.iterdir():
        size = sum(p.stat().st_size for p in sub.rglob("*") if p.is_file())
        total += size
        entries.append((sub.stat().st_mtime, size, sub))
    limit = max_gb * 1024**3
    for _, size, sub in sorted(entries):
        if total <= limit:
            break
        shutil.rmtree(sub, ignore_errors=True)
        total -= size


def fingerprint(path: Path) -> str:
    return quick_fingerprint(path)
