"""Scan stage (headers only): series discovery, header rows, geometry / advanced-DICOM / MRI
component inspection (DCM-03). Ported from `legacy/convert/{dicom_io,series_inspection}.py`."""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

from plugins.text import split_multi_value, value_to_text

IGNORED_DIR_NAMES = {
    ".git", "__pycache__", "autorun", "bin", "configuration", "help", "java", "jre", "lib",
    "modules", "plugins", "resource", "resources", "recycle_bin", "derived",
}  # fmt: skip
IGNORED_FILE_SUFFIXES = {
    ".ags", ".agm", ".bmp", ".cmd", ".csv", ".doc", ".docx", ".dll", ".exe", ".gz", ".inf",
    ".ini", ".jar", ".json", ".jsonl", ".log", ".md", ".nii", ".npy", ".pdf", ".sh", ".tar",
    ".txt", ".xls", ".xlsx", ".xml", ".zip", ".yaml", ".yml", ".png", ".jpg",
}  # fmt: skip
POSITION_TOLERANCE_MM = 1e-3
ORIENTATION_TOLERANCE = 1e-4
IN_PLANE_SPACING_TOLERANCE_MM = 1e-4
SLICE_SPACING_ABSOLUTE_TOLERANCE_MM = 1e-3
SLICE_SPACING_RELATIVE_TOLERANCE = 0.05
LARGE_GAP_FACTOR = 1.5
MULTIPLE_STACK_GAP_FACTOR = 3.0
ENHANCED_CT_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.2.1"
ENHANCED_MR_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.4.1"
DICOM_SEG_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.66.4"


@dataclass(frozen=True)
class Series:
    dicom_dir: Path
    series_id: str
    files: tuple[Path, ...]
    # the discovery pass's per-file headers (`SCAN_TAGS` only), reused by `inspect`
    headers: tuple[Any, ...] = field(default=(), compare=False, repr=False)
    # the files' total size, known from that pass (0: unknown); a stat per file is a round trip
    source_bytes: int = 0


@dataclass
class Diagnostic:
    severity: str
    stage: str
    code: str
    message: str
    path: str = ""
    series_id: str = ""

    def as_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


@dataclass
class Inspection:
    geometry_status: str = "ok"
    geometry_codes: list[str] = field(default_factory=list)
    nominal_slice_spacing: float | None = None
    maximum_spacing_deviation: float | None = None
    advanced_status: str = "standard"
    advanced_codes: list[str] = field(default_factory=list)
    mri_component: str = ""
    mri_component_status: str = ""


def _possible_dicom(names: list[str]) -> bool:
    return any(Path(n).suffix.lower() not in IGNORED_FILE_SUFFIXES for n in names)


def has_dicom_files(folder: Path) -> bool:
    """The folder itself holds possible DICOM files (not only subfolders)."""
    try:
        return _possible_dicom([p.name for p in folder.iterdir() if p.is_file()])
    except OSError:
        return False


def candidate_dirs(root: Path) -> list[Path]:
    return [d for d, _ in candidate_files(root)]


def candidate_files(root: Path) -> list[tuple[Path, list[Path]]]:
    """Folders under `root` with their possible DICOM files (one directory walk)."""
    out: list[tuple[Path, list[Path]]] = []
    for cur, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d.lower() not in IGNORED_DIR_NAMES and not d.startswith("."))
        names = sorted(f for f in files if Path(f).suffix.lower() not in IGNORED_FILE_SUFFIXES)
        if names:
            out.append((Path(cur), [Path(cur) / f for f in names]))
    return out


# Everything grouping, ordering and `inspect` need; the discovery pass reads only these, once
# per file, so a dry run reads each file one time (the full header only for a series' first)
SCAN_TAGS = [
    "SeriesInstanceUID", "SOPClassUID", "InstanceNumber", "Modality", "ImageOrientationPatient",
    "ImagePositionPatient", "PixelSpacing", "Rows", "Columns", "NumberOfFrames", "EchoNumbers",
    "TemporalPositionIdentifier", "DiffusionBValue", "GantryDetectorTilt",
    "ComplexImageComponent", "ImageType", "SharedFunctionalGroupsSequence",
    "PerFrameFunctionalGroupsSequence",
]  # fmt: skip
# Header reads overlap: sources are often on network or bind mounts, where latency dominates
READ_THREADS = 16
# One read per file: the header is parsed from memory. Many small reads (pydicom on a file
# object) are one round trip each on a network or Docker Desktop bind mount (~10x slower).
HEAD_BYTES = 16_384
PIXEL_TAGS = (b"\xe0\x7f\x10\x00", b"\x7f\xe0\x00\x10")  # (7FE0,0010) little / big endian


def _looks_dicom(head: bytes) -> bool:
    """A `DICM` preamble, or a file starting at group 0002/0008 (GDCM reads those too)."""
    return head[128:132] == b"DICM" or head[:2] in (b"\x02\x00", b"\x08\x00")


def _head(path: Path, check: bool = False) -> tuple[bytes, bool, int] | None:
    """(bytes up to the pixel data or the whole file, whether it is cut short, file size);
    None when `check` and it doesn't look like DICOM (then only its first bytes were read)."""
    with path.open("rb", buffering=0) as fh:
        buf = fh.read(HEAD_BYTES)
        if check and not _looks_dicom(buf):
            return None
        if len(buf) < HEAD_BYTES:
            return buf, False, len(buf)
        size = os.fstat(fh.fileno()).st_size
        # a longer header (private tags, enhanced multi-frame): doubling reads, not the file
        while not any(t in buf for t in PIXEL_TAGS):
            more = fh.read(len(buf))
            if not more:
                return buf, False, size
            buf += more
        return buf, len(buf) < size, size


def _parse(path: Path, head: tuple[bytes, bool, int], **kw: Any) -> Any:
    """Headers only (`stop_before_pixels`) from memory; the whole file if a cut-short head
    doesn't parse (a pixel-tag byte pattern inside an earlier value)."""
    import pydicom
    from pydicom import config as pydicom_config

    pydicom_config.convert_wrong_length_to_UN = True
    buf, cut, _ = head
    try:
        return pydicom.dcmread(io.BytesIO(buf), stop_before_pixels=True, force=True, **kw)
    except Exception:
        if not cut:
            raise
        data = io.BytesIO(path.read_bytes())
        return pydicom.dcmread(data, stop_before_pixels=True, force=True, **kw)


def _scan_header(path: Path) -> tuple[Any, int] | None:
    """(`SCAN_TAGS` of one file, its size), or None when it isn't DICOM or can't be read."""
    try:
        head = _head(path, check=True)
        return None if head is None else (_parse(path, head, specific_tags=SCAN_TAGS), head[2])
    except Exception:  # noqa: BLE001 - any malformed candidate is not DICOM
        return None


def _ipp_order(files: list[Path], headers: list[Any]) -> list[int]:
    """GDCM's order: along the slice normal, else by InstanceNumber, else by file name."""
    idx = list(range(len(files)))
    by_name = sorted(idx, key=lambda i: str(files[i]))
    o = _floats(headers[0], "ImageOrientationPatient", 6)
    pos = [_floats(h, "ImagePositionPatient", 3) for h in headers]
    if o is not None and all(p is not None for p in pos):
        n = _normal(o)
        dist = [sum(a * b for a, b in zip(p or (), n, strict=False)) for p in pos]
        if len(set(dist)) == len(dist):
            return sorted(by_name, key=lambda i: dist[i])
    nums = [_int(getattr(h, "InstanceNumber", None)) for h in headers]
    if all(v is not None for v in nums) and len(set(nums)) == len(nums):
        return sorted(by_name, key=lambda i: nums[i] or 0)
    return by_name


def discover(
    root: Path,
    diagnostics: list[Diagnostic],
    files: list[tuple[Path, list[Path]]] | None = None,
    tick: Callable[[int], None] | None = None,
) -> list[Series]:
    """Series per folder by SeriesInstanceUID (as GDCM groups them), sorted; one file → its own
    one-file series (DCM-10). One header read per file; `tick(1)` after each.
    The pixel stage asks GDCM for its own file order again (DCM-02, `convert.read_image`)."""
    if root.is_file():
        return [Series(root.parent, _single_series_id(root), (root,))]
    found: list[Series] = []
    with ThreadPoolExecutor(READ_THREADS, thread_name_prefix="dcm-scan") as pool:
        for d, paths in files if files is not None else candidate_files(root):
            groups: dict[str, tuple[list[Path], list[Any], list[int]]] = {}
            for path, got in zip(paths, pool.map(_scan_header, paths), strict=True):
                if tick is not None:
                    tick(1)
                if got is None:
                    continue
                ds, size = got
                uid = value_to_text(getattr(ds, "SeriesInstanceUID", "")).strip()
                if uid:
                    g = groups.setdefault(uid, ([], [], []))
                    g[0].append(path)
                    g[1].append(ds)
                    g[2].append(size)
            if not groups and paths:
                diagnostics.append(
                    Diagnostic(
                        "INFO", "dicom_discovery", "NO_DICOM_SERIES",
                        f"{len(paths)} files, none readable as DICOM", str(d),
                    )
                )  # fmt: skip
            for uid, (ps, hs, sizes) in groups.items():
                order = _ipp_order(ps, hs)
                ordered = tuple(ps[i] for i in order)
                found.append(Series(d, uid, ordered, tuple(hs[i] for i in order), sum(sizes)))
    return sorted(found, key=lambda s: (str(s.dicom_dir), s.series_id))


def _single_series_id(path: Path) -> str:
    ds = read_header(path)
    return value_to_text(getattr(ds, "SeriesInstanceUID", "")) or path.name


def read_header(path: Path) -> Any:
    """Headers only (`stop_before_pixels`); sources are opened read-only (R1)."""
    head = _head(path)
    assert head is not None
    return _parse(path, head)


def first_header(series: Series) -> Any:
    return read_header(min(series.files, key=str))


def inspect(series: Series, first: Any, diagnostics: list[Diagnostic]) -> Inspection:
    out = Inspection()
    try:
        headers = (
            list(series.headers)
            if len(series.headers) == len(series.files) > 1
            else [read_header(p) for p in series.files]
            if len(series.files) > 1
            else [first]
        )
    except Exception as exc:  # noqa: BLE001 - surface malformed headers as diagnostics
        diagnostics.append(
            Diagnostic(
                "WARNING",
                "geometry_validation",
                "GEOMETRY_INSPECTION_FAILED",
                str(exc),
                str(series.dicom_dir),
                series.series_id,
            )
        )
        out.geometry_status = "unknown"
        return out
    frames = _int(getattr(first, "NumberOfFrames", None))
    if len(headers) > 1 or not frames or frames <= 1:
        _geometry(headers, out)
    for code in out.geometry_codes:
        diagnostics.append(
            Diagnostic(
                "WARNING",
                "geometry_validation",
                code,
                f"Geometry validation warning: {code}",
                str(series.dicom_dir),
                series.series_id,
            )
        )
    _advanced(headers, out)
    modality = value_to_text(getattr(first, "Modality", "")).upper()
    if modality == "MR":
        _mri(headers, out)
    return out


def _geometry(datasets: list[Any], out: Inspection) -> None:
    """DCM-06 geometry checks over the slice headers of one series; each check adds its code."""
    g = _Headers(
        orientations=[_floats(ds, "ImageOrientationPatient", 6) for ds in datasets],
        positions=[_floats(ds, "ImagePositionPatient", 3) for ds in datasets],
        spacings=[_floats(ds, "PixelSpacing", 2) for ds in datasets],
        rows=[_int(getattr(ds, "Rows", None)) for ds in datasets],
        cols=[_int(getattr(ds, "Columns", None)) for ds in datasets],
    )
    codes: list[str] = []
    for check in (_check_missing, _check_orientation, _check_in_plane, _check_matrix):
        code = check(g)
        if code:
            _add(codes, code)
    spacing = _slice_spacing(g)
    if spacing is not None:
        for code in spacing.codes:
            _add(codes, code)
        if spacing.nominal is not None:
            out.nominal_slice_spacing = spacing.nominal
            out.maximum_spacing_deviation = spacing.deviation
    out.geometry_codes = codes
    out.geometry_status = "warning" if codes else "ok"


@dataclass(frozen=True)
class _Headers:
    """The geometry tags of every slice of a series (None = missing or unreadable)."""

    orientations: list[tuple[float, ...] | None]
    positions: list[tuple[float, ...] | None]
    spacings: list[tuple[float, ...] | None]
    rows: list[int | None]
    cols: list[int | None]


@dataclass(frozen=True)
class _Spacing:
    nominal: float | None  # None: every slice is a duplicate position
    deviation: float | None
    codes: list[str]


def _first(values: list[Any]) -> Any:
    return next((v for v in values if v is not None), None)


def _check_missing(g: _Headers) -> str | None:
    tags: list[Any] = [*g.orientations, *g.positions, *g.spacings, *g.rows, *g.cols]
    return "GEOMETRY_METADATA_MISSING" if any(v is None for v in tags) else None


def _check_orientation(g: _Headers) -> str | None:
    o0 = _first(g.orientations)
    bad = o0 is not None and any(o is not None and _delta(o, o0) > ORIENTATION_TOLERANCE for o in g.orientations)
    return "ORIENTATION_CONFLICT" if bad else None


def _check_in_plane(g: _Headers) -> str | None:
    s0 = _first(g.spacings)
    bad = s0 is not None and any(s is not None and _delta(s, s0) > IN_PLANE_SPACING_TOLERANCE_MM for s in g.spacings)
    return "IN_PLANE_SPACING_CONFLICT" if bad else None


def _check_matrix(g: _Headers) -> str | None:
    r0, c0 = _first(g.rows), _first(g.cols)
    bad = any(v is not None and v != r0 for v in g.rows) or any(v is not None and v != c0 for v in g.cols)
    return "MATRIX_SIZE_CONFLICT" if bad else None


def _slice_spacing(g: _Headers) -> _Spacing | None:
    """Distances between slices along the normal: duplicates, irregular spacing, gaps, stacks."""
    o0 = _first(g.orientations)
    if o0 is None or len(g.positions) < 2 or any(p is None for p in g.positions):
        return None
    normal = _normal(o0)
    proj = sorted(sum(a * b for a, b in zip(p or (), normal, strict=False)) for p in g.positions)
    dist = [abs(proj[i + 1] - proj[i]) for i in range(len(proj) - 1)]
    codes: list[str] = []
    if any(d <= POSITION_TOLERANCE_MM for d in dist):
        codes.append("DUPLICATE_SLICE_POSITION")
    pos = [d for d in dist if d > POSITION_TOLERANCE_MM]
    if not pos:
        return _Spacing(None, None, codes) if codes else None
    nominal = float(median(pos))
    dev = max(abs(d - nominal) for d in pos)
    tol = max(SLICE_SPACING_ABSOLUTE_TOLERANCE_MM, nominal * SLICE_SPACING_RELATIVE_TOLERANCE)
    gaps = [d for d in pos if d > nominal * LARGE_GAP_FACTOR or d > min(pos) * LARGE_GAP_FACTOR]
    if dev > tol:
        codes.append("IRREGULAR_SLICE_SPACING")
    if gaps:
        codes.append("LARGE_SLICE_GAP")
    if len(gaps) > 1 or any(d > nominal * MULTIPLE_STACK_GAP_FACTOR for d in pos):
        codes.append("POSSIBLE_MULTIPLE_STACKS")
    return _Spacing(nominal, dev, codes)


def _advanced(datasets: list[Any], out: Inspection) -> None:
    first = datasets[0]
    codes: list[str] = []
    frames = _int(getattr(first, "NumberOfFrames", None))
    sop = value_to_text(getattr(first, "SOPClassUID", ""))
    if frames is not None and frames > 1:
        _add(codes, "MULTIFRAME_OBJECT")
    if sop == ENHANCED_CT_SOP_CLASS_UID:
        _add(codes, "ENHANCED_CT")
    if sop == ENHANCED_MR_SOP_CLASS_UID:
        _add(codes, "ENHANCED_MR")
    if any(getattr(ds, "SharedFunctionalGroupsSequence", None) for ds in datasets):
        _add(codes, "SHARED_FUNCTIONAL_GROUPS_PRESENT")
    if any(getattr(ds, "PerFrameFunctionalGroupsSequence", None) for ds in datasets):
        _add(codes, "PER_FRAME_FUNCTIONAL_GROUPS_PRESENT")
    echoes = {value_to_text(getattr(ds, k, "")) for ds in datasets for k in ("EchoNumbers", "EchoNumber")} - {""}
    if len(echoes) > 1:
        _add(codes, "MULTI_ECHO_INDICATORS")
    if any(value_to_text(getattr(ds, "TemporalPositionIdentifier", "")) for ds in datasets):
        _add(codes, "TEMPORAL_POSITION_INDICATORS")
    if any(value_to_text(getattr(ds, "DiffusionBValue", "")) for ds in datasets):
        _add(codes, "DIFFUSION_INDICATORS")
    if any(_nonzero(getattr(ds, "GantryDetectorTilt", "")) for ds in datasets):
        _add(codes, "GANTRY_TILT_INDICATOR")
    out.advanced_codes = codes
    out.advanced_status = "detected" if codes else "standard"


MRI_ALIASES = {
    "MAGNITUDE": "MAGNITUDE", "M": "MAGNITUDE", "PHASE": "PHASE", "P": "PHASE", "REAL": "REAL",
    "R": "REAL", "IMAGINARY": "IMAGINARY", "IMAG": "IMAGINARY", "I": "IMAGINARY", "MIXED": "MIXED",
}  # fmt: skip


def _mri(datasets: list[Any], out: Inspection) -> None:
    seen: set[str] = set()
    for ds in datasets:
        comp = MRI_ALIASES.get(value_to_text(getattr(ds, "ComplexImageComponent", "")).strip().upper(), "")
        if not comp:
            for tok in split_multi_value(getattr(ds, "ImageType", "")):
                comp = MRI_ALIASES.get(tok.upper(), "")
                if comp:
                    break
        if comp:
            seen.add(comp)
    if len(seen) > 1:
        out.mri_component, out.mri_component_status = "UNKNOWN", "heterogeneous"
    elif seen:
        out.mri_component, out.mri_component_status = seen.pop(), "ok"
    else:
        out.mri_component, out.mri_component_status = "UNKNOWN", "unknown"


def _floats(ds: Any, keyword: str, n: int) -> tuple[float, ...] | None:
    value = getattr(ds, keyword, None)
    if value is None:
        return None
    try:
        vals = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        try:
            vals = tuple(float(p) for p in value_to_text(value).split("\\") if p)
        except ValueError:
            return None
    return vals if len(vals) >= n else None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _nonzero(value: Any) -> bool:
    try:
        return abs(float(value_to_text(value))) > 1e-6
    except ValueError:
        return False


def _normal(o: tuple[float, ...]) -> tuple[float, float, float]:
    r, c = o[:3], o[3:6]
    return (r[1] * c[2] - r[2] * c[1], r[2] * c[0] - r[0] * c[2], r[0] * c[1] - r[1] * c[0])


def _delta(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return max(abs(x - y) for x, y in zip(a, b, strict=False))


def _add(codes: list[str], code: str) -> None:
    if code not in codes:
        codes.append(code)
