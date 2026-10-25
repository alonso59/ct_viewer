"""Open mode: view files without a project.

Sessions live in memory only: nothing is written to a project or to the workspace registry.
NumPy (and, with the converter, DICOM) volumes are converted into the disposable
`WORKSPACE_ROOT/.scratch/open/{fingerprint}/`, inside the global `CACHE_MAX_GB` LRU budget.
Headers run in job workers. An opened file is always an image; a segmentation comes only from
attach (NIfTI, same geometry, from anywhere under ALLOWED_DATA_ROOTS).
"""

from __future__ import annotations

import hashlib
import io
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from app.core.errors import AmbiguousAxisOrder, GeometryMismatch, NotFound, UnsupportedFormat
from app.core.fsio import iter_jsonl
from app.core.ids import new_ulid, utc_now
from app.imaging import npy_convert
from app.imaging.header import AFFINE_ATOL_MM, HeaderError, read_header
from app.sources import formats

MAX_ITEMS = 500
MAX_SESSIONS = 32
OPEN_DIR = Path(".scratch") / "open"

# "label" only for a segmentation attached to an image
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
    rel: str  # relative to the session root; absolute for an attachment outside it
    format: Literal["nifti", "npy", "dicom"]
    kind: ItemKind = "image"
    geometry: OpenGeometry | None = None
    # DICOM, or the `metadata.jsonl` row of a dataset folder; else unknown
    modality: str | None = None
    n_slices: int | None = None
    attached_to: int | None = None
    axis_order: Literal["xyz", "zyx"] | None = None  # NumPy
    needs_axis_order: bool = False
    error: str | None = None
    # DICOM: one item per series; files relative to the session root
    files: list[str] = Field(default_factory=list)
    series_uid: str | None = None
    description: str | None = None
    # the DICOM header window `[width, center]` (first values), when present
    window: list[float] | None = None


class OpenSession(BaseModel):
    sid: str
    path: str
    root: str
    kind: Literal["file", "folder"]
    created_at: str
    items: list[OpenItem]
    truncated: bool = False
    ignored: dict[str, int] = Field(default_factory=dict)


def probe(
    root: str, rels: list[str], kinds: dict[str, formats.Kind] | None = None
) -> list[dict[str, Any]]:
    """Worker: header per accepted file (NIfTI, NumPy). Never raises."""
    out: list[dict[str, Any]] = []
    dicom: list[str] = []
    for rel in rels:
        path = Path(root) / rel
        fmt = kinds.get(rel) if kinds is not None else formats.classify(path, Path(root))
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
            elif fmt == "nifti":
                h = read_header(path)
                row["geometry"] = {**h.geometry(), "affine": h.affine}
            else:
                if fmt == "dicom":
                    dicom.append(rel)
                continue  # DICOM files are grouped into series below
        except (HeaderError, OSError, ValueError) as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        out.append(row)
    if dicom:
        from app.tasks.dicom_stage import probe_series

        out += probe_series(root, dicom)
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


class OpenSessions:
    """In-memory LRU of Open-mode sessions (API process)."""

    def __init__(self) -> None:
        self._s: OrderedDict[str, OpenSession] = OrderedDict()

    def put(self, s: OpenSession) -> None:
        self._s[s.sid] = s
        while len(self._s) > MAX_SESSIONS:
            self._s.popitem(last=False)

    def get(self, sid: str) -> OpenSession:
        s = self._s.get(sid)
        if s is None:
            raise NotFound(
                "This Open session has ended: it was closed, or the server restarted "
                "(sessions live in server memory only). Open the file or folder again.",
                actions=["choose_another_path", "home"],
            )
        self._s.move_to_end(sid)
        return s

    def drop(self, sid: str) -> None:
        self._s.pop(sid, None)


def row_modalities(root: Path) -> dict[str, str]:
    """File name → `modality` from the `metadata.jsonl` of an opened dataset folder, or of the
    folder above an opened `nifti/`. Rows without a modality are skipped; an unreadable file gives
    none."""
    for d in (root, root.parent):
        meta = d / "metadata.jsonl"
        if not meta.is_file():
            continue
        out: dict[str, str] = {}
        try:
            for r in iter_jsonl(meta):
                mod = r.get("modality")
                ref = r.get("relative_path") or r.get("filename")
                if isinstance(mod, str) and mod and isinstance(ref, str) and ref:
                    out[Path(ref.replace("\\", "/")).name] = mod.upper()
        except (OSError, ValueError):
            return {}
        return out
    return {}


def build_session(
    path: Path,
    rows: list[dict[str, Any]],
    scan: formats.Scan,
    modalities: dict[str, str],
) -> OpenSession:
    items: list[OpenItem] = []
    for n, r in enumerate(rows):
        geo = OpenGeometry.model_validate(r["geometry"]) if r.get("geometry") else None
        rel = Path(r["rel"])
        name = rel.name
        if r["format"] == "dicom" and len(r.get("files") or []) > 1:
            # a series is named by its description or folder
            name = r.get("description") or rel.parent.name or rel.name
        items.append(
            OpenItem(
                n=n,
                item_id=f"open.{n}",
                name=name,
                rel=r["rel"],
                format=r["format"],
                geometry=geo,
                n_slices=geo.shape[2] if geo else None,
                axis_order=r.get("axis_order"),
                needs_axis_order=bool(r.get("needs_axis_order")),
                error=r.get("error"),
                files=list(r.get("files") or []),
                series_uid=r.get("series_uid"),
                description=r.get("description"),
                modality=r.get("modality") or modalities.get(rel.name),
                window=r.get("window"),
            )
        )
    return OpenSession(
        sid=new_ulid(),
        path=str(path),
        root=str(scan.root),
        kind="file" if path.is_file() else "folder",
        created_at=utc_now(),
        items=items,
        truncated=scan.truncated,
        ignored=dict(scan.ignored),
    )


def accepted(scan: formats.Scan) -> list[str]:
    return sorted(scan.files["nifti"] + scan.files["npy"] + scan.files["dicom"])


def preview(session: OpenSession) -> OpenSession:
    """The session with at most `MAX_ITEMS` items; the items endpoint pages the full list."""
    return session.model_copy(
        update={
            "items": session.items[:MAX_ITEMS],
            "truncated": session.truncated or len(session.items) > MAX_ITEMS,
        }
    )


def refuse_empty(path: Path, scan: formats.Scan) -> UnsupportedFormat:
    ignored = ", ".join(f"{n} {e}" for e, n in scan.ignored.most_common(5)) or "no files"
    extra = "; ".join(scan.refused.values())
    detail = f"Nothing to open in {path.name}: {ignored}" + (f". {extra}" if extra else "")
    return UnsupportedFormat(detail, actions=["choose_another_path", "home"])


def item(session: OpenSession, n: int) -> OpenItem:
    if not 0 <= n < len(session.items):
        raise NotFound(f"Open item {n} not found")
    return session.items[n]


def source_path(session: OpenSession, it: OpenItem) -> Path:
    rel = Path(it.rel)
    return rel if rel.is_absolute() else Path(session.root) / rel


def add_label(session: OpenSession, n: int, path: Path, geo: OpenGeometry) -> OpenSession:
    """Append an attached segmentation for item n. A file outside the session root keeps its
    absolute path; reads are guarded again on every request."""
    root = Path(session.root)
    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    k = len(session.items)
    session.items.append(
        OpenItem(
            n=k,
            item_id=f"open.{k}",
            name=path.name,
            rel=rel,
            format="nifti",
            kind="label",
            geometry=geo,
            n_slices=geo.shape[2],
            attached_to=n,
        )
    )
    return session


def scratch_dir(workspace_root: Path, fp: str, axis_order: str) -> Path:
    return workspace_root / OPEN_DIR / f"{fp}.{axis_order}"


def need_axis_order(it: OpenItem, chosen: str | None) -> Literal["xyz", "zyx"]:
    order = npy_convert.axis_order_of(chosen) or it.axis_order
    if order is None:
        raise AmbiguousAxisOrder(
            f"{it.name}: axis order unknown (no sidecar axis_order, no decisive reference_ref); "
            "pick xyz (nibabel) or zyx (SimpleITK)",
            actions=["axis_order:xyz", "axis_order:zyx"],
        )
    return order


def check_attach(image: OpenItem, label: OpenGeometry) -> None:
    """Same shape and affines within `AFFINE_ATOL_MM`; never resampled."""
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
            "It is never resampled",
            actions=["choose_another_path"],
        )


def pseudonym(fp: str) -> str:
    """With `anonymize: basic`: the saved file's stem and the sidecar's PatientName / PatientID.
    Derived from the volume's content fingerprint, never from a folder or file name (DICOM folders
    are often patient names)."""
    return "open-" + hashlib.sha256(fp.encode()).hexdigest()[:12]
