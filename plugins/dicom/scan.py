"""Scan stage (headers only): series discovery, header rows, geometry / advanced-DICOM / MRI
component inspection (DCM-03). Ported from `legacy/convert/{dicom_io,series_inspection}.py`."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

from plugins.text import split_multi_value, value_to_text

IGNORED_DIR_NAMES = {
    ".git", "__pycache__", "autorun", "bin", "configuration", "help", "java", "jre", "lib",
    "modules", "plugins", "resource", "resources",
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
    out: list[Path] = []
    for cur, dirs, files in os.walk(root):
        dirs[:] = sorted(
            d for d in dirs if d.lower() not in IGNORED_DIR_NAMES and not d.startswith(".")
        )
        if files and _possible_dicom(files):
            out.append(Path(cur))
    return out


def discover(root: Path, diagnostics: list[Diagnostic]) -> list[Series]:
    """GDCM series per folder (SimpleITK), sorted; one file → its own one-file series (DCM-10)."""
    import SimpleITK as sitk

    if root.is_file():
        return [Series(root.parent, _single_series_id(root), (root,))]
    found: list[Series] = []
    seen: set[tuple[str, str]] = set()
    for d in candidate_dirs(root):
        try:
            ids = sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(d))
        except RuntimeError as exc:
            diagnostics.append(
                Diagnostic("WARNING", "dicom_discovery", "DICOM_DISCOVERY_FAILED", str(exc), str(d))
            )
            continue
        for sid in ids or ():
            key = (str(d.resolve()), str(sid))
            if key in seen:
                continue
            seen.add(key)
            try:
                names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(d), sid)
            except RuntimeError as exc:
                diagnostics.append(
                    Diagnostic(
                        "WARNING",
                        "dicom_discovery",
                        "DICOM_DISCOVERY_FAILED",
                        str(exc),
                        str(d),
                        str(sid),
                    )
                )
                continue
            if names:
                found.append(Series(d, str(sid), tuple(Path(n) for n in names)))
    return sorted(found, key=lambda s: (str(s.dicom_dir), s.series_id))


def _single_series_id(path: Path) -> str:
    ds = read_header(path)
    return value_to_text(getattr(ds, "SeriesInstanceUID", "")) or path.name


def read_header(path: Path) -> Any:
    """Headers only (`stop_before_pixels`); sources are opened read-only (R1)."""
    import pydicom
    from pydicom import config as pydicom_config

    pydicom_config.convert_wrong_length_to_UN = True
    with path.open("rb") as fh:
        return pydicom.dcmread(fh, stop_before_pixels=True, force=True)


def first_header(series: Series) -> Any:
    return read_header(sorted(series.files, key=str)[0])


def inspect(series: Series, first: Any, diagnostics: list[Diagnostic]) -> Inspection:
    out = Inspection()
    try:
        headers = [read_header(p) for p in series.files] if len(series.files) > 1 else [first]
    except Exception as exc:
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
    bad = o0 is not None and any(
        o is not None and _delta(o, o0) > ORIENTATION_TOLERANCE for o in g.orientations
    )
    return "ORIENTATION_CONFLICT" if bad else None


def _check_in_plane(g: _Headers) -> str | None:
    s0 = _first(g.spacings)
    bad = s0 is not None and any(
        s is not None and _delta(s, s0) > IN_PLANE_SPACING_TOLERANCE_MM for s in g.spacings
    )
    return "IN_PLANE_SPACING_CONFLICT" if bad else None


def _check_matrix(g: _Headers) -> str | None:
    r0, c0 = _first(g.rows), _first(g.cols)
    bad = any(v is not None and v != r0 for v in g.rows) or any(
        v is not None and v != c0 for v in g.cols
    )
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
    echoes = {
        value_to_text(getattr(ds, k, "")) for ds in datasets for k in ("EchoNumbers", "EchoNumber")
    } - {""}
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
        comp = MRI_ALIASES.get(
            value_to_text(getattr(ds, "ComplexImageComponent", "")).strip().upper(), ""
        )
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
