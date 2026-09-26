"""Open mode (SRC-09/10, API-07/08): view files without a project.

Sessions live in memory only: nothing is written to a project or to the workspace registry.
NumPy (and, with the converter, DICOM) volumes are converted into the disposable
`WORKSPACE_ROOT/.scratch/open/{fingerprint}/`, LRU-purged with `CACHE_MAX_GB`.
Headers run in job workers (BE-12). An opened file is always an image; a segmentation
comes only from attach (SRC-10: NIfTI, same geometry, from anywhere under ALLOWED_DATA_ROOTS,
ADR-0027). The actions (open, attach, save) live in `open_service.py`.
"""

from __future__ import annotations

import hashlib
import io
import shutil
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from app.core.errors import AmbiguousAxisOrder, GeometryMismatch, NotFound, UnsupportedFormat
from app.core.fsio import iter_jsonl
from app.core.ids import new_ulid, utc_now
from app.imaging import npy_convert
from app.imaging.fingerprint import quick_fingerprint
from app.imaging.header import AFFINE_ATOL_MM, HeaderError, read_header
from app.sources import formats

MAX_ITEMS = 500
MAX_SESSIONS = 32
OPEN_DIR = Path(".scratch") / "open"

# "label" only for a segmentation attached to an image (SRC-10)
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
    rel: str  # relative to the session root; absolute for an attachment outside it (ADR-0027)
    format: Literal["nifti", "npy", "dicom"]
    kind: ItemKind = "image"
    geometry: OpenGeometry | None = None
    # DICOM, or the `metadata.jsonl` row of a dataset folder (SRC-16); else unknown (VW-05)
    modality: str | None = None
    n_slices: int | None = None
    attached_to: int | None = None
    axis_order: Literal["xyz", "zyx"] | None = None  # NumPy (SRC-12)
    needs_axis_order: bool = False
    error: str | None = None
    # DICOM: one item per series (SRC-13); files relative to the session root
    files: list[str] = Field(default_factory=list)
    series_uid: str | None = None
    description: str | None = None
    # VW-22: the DICOM header window `[width, center]` (first values), when present
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


# -- worker units ----------------------------------------------------------------------------


def probe(root: str, rels: list[str]) -> list[dict[str, Any]]:
    """Worker: header per accepted file (NIfTI, NumPy). Never raises."""
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
            elif fmt == "nifti":
                h = read_header(path)
                row["geometry"] = {**h.geometry(), "affine": h.affine}
            else:
                continue  # DICOM files are grouped into series below
        except (HeaderError, OSError, ValueError) as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        out.append(row)
    dicom = [r for r in rels if formats.classify(Path(root) / r) == "dicom"]
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
            raise NotFound(  # UI-18: the route shows how to go on (AUD-A1-19)
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
    folder above an opened `nifti/` (SRC-16, AUD-A2-10). Unreadable rows are skipped."""
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
    modalities: dict[str, str] | None = None,
) -> OpenSession:
    known = modalities or {}
    items: list[OpenItem] = []
    for n, r in enumerate(rows):
        geo = OpenGeometry.model_validate(r["geometry"]) if r.get("geometry") else None
        rel = Path(r["rel"])
        name = rel.name
        if r["format"] == "dicom" and len(r.get("files") or []) > 1:
            # A series is named by its description or folder, not by its first file
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
                modality=r.get("modality") or known.get(rel.name),
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
    return UnsupportedFormat(detail, actions=["choose_another_path", "home"])


def item(session: OpenSession, n: int) -> OpenItem:
    if not 0 <= n < len(session.items):
        raise NotFound(f"Open item {n} not found")
    return session.items[n]


def source_path(session: OpenSession, it: OpenItem) -> Path:
    rel = Path(it.rel)
    return rel if rel.is_absolute() else Path(session.root) / rel


def add_label(session: OpenSession, n: int, path: Path, geo: OpenGeometry) -> OpenSession:
    """Append an attached segmentation for item n (SRC-10). A file outside the session root keeps
    its absolute path (ADR-0027); reads are guarded again on every request."""
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


def pseudonym(fp: str) -> str:
    """SRC-14 with `anonymize: basic`: the saved file's stem and the sidecar's PatientName /
    PatientID. Derived from the volume's content fingerprint, never from a folder or file name
    (DICOM folders are often patient names; NFR-17, AUD-A2-15)."""
    return "open-" + hashlib.sha256(fp.encode()).hexdigest()[:12]
