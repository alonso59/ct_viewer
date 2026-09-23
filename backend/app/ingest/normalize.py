"""Normalizer: parsed rows → item drafts (phase, side, paths, identity). IMP-05/06/07/10/11.

Runs in the API process: every path is turned into an alias ref (`PathResolver.to_ref`) and
resolved (`resolve`, BE-02) here, so worker units only receive guarded absolute paths.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.errors import PathOutsideRoot, Problem
from app.core.ids import Scope, Side, item_id
from app.core.paths import PathResolver
from app.imaging.header import VolumeFormat, volume_format
from app.ingest.codes import QcCode
from app.ingest.models import ItemStatus, Phase, PhaseInfo, PhaseSource
from app.ingest.parsers import ParsedInputs, PhaseOverrides, Row, is_excluded

__all__ = ["is_excluded"]

PHASE_ORDER: tuple[Phase, ...] = ("NC", "CMP", "NP", "EP", "UNK")
PHASE_TABLE: dict[str, Phase] = {
    **dict.fromkeys(("NC", "NONCONTRAST", "NON-CONTRAST"), "NC"),
    **dict.fromkeys(("ART", "ARTERIAL", "CMP", "CORTICOMEDULLARY"), "CMP"),
    **dict.fromkeys(("VEN", "VENOUS", "NP", "NEPHROGRAPHIC", "PORTAL"), "NP"),
    **dict.fromkeys(("EP", "DELAY", "DELAYED", "EXC", "EXCRETORY"), "EP"),
    **dict.fromkeys(("", "UNDEFINED", "UNKNOWN", "N/A", "NONE"), "UNK"),
}
PHASE_FIELDS: tuple[PhaseSource, ...] = ("curated_phase", "canonical_phase", "phase", "phase_guess")
CONFLICT_FIELDS = ("curated_phase", "canonical_phase", "phase")
SIDES: dict[str, Literal["L", "R"]] = {
    **dict.fromkeys(("l", "left", "sidel", "_l"), "L"),
    **dict.fromkeys(("r", "right", "sider", "_r"), "R"),
}
_SEG_SUFFIX = re.compile(r"_0000(\.nii(?:\.gz)?)$", re.IGNORECASE)

# Row fields consumed into Item fields (paths never go to `extra`: PRJ-04).
META_CONSUMED = frozenset(
    {"case_id", "scan_idx", "patient_id", "group", "filename", "relative_path", "nifti_file",
     "seg_path"}
)  # fmt: skip
CATALOG_CONSUMED = frozenset(
    {"case_id", "scan_idx", "patient_id", "group", "side", "image_path", "mask_path"}
)


def normalize_phase(raw: str | None) -> Phase:
    """INPUT_METADATA.md §Phase resolution table; unknown strings → UNK."""
    return PHASE_TABLE.get((raw or "").strip().upper(), "UNK")


def parse_side(value: str | None) -> Literal["L", "R"] | None:
    return SIDES.get((value or "").strip().lower())


def seg_convention(filename: str) -> str:
    """`seg/{filename minus the trailing _0000}`."""
    return "seg/" + _SEG_SUFFIX.sub(r"\1", filename)


def identity_filename(row: Row) -> str | None:
    name = row.text("filename")
    if name:
        return name
    for f in ("relative_path", "nifti_file"):
        v = row.text(f)
        if v:
            return posixpath.basename(v.replace("\\", "/")) or None
    return None


def image_path(row: Row) -> str | None:
    """`relative_path` → `nifti_file` (absolute legacy) → `nifti/{filename}`."""
    for f in ("relative_path", "nifti_file"):
        v = row.text(f)
        if v:
            return v
    name = row.text("filename")
    return f"nifti/{name}" if name else None


def resolve_phase(row: Row, override: str | None) -> tuple[PhaseInfo, bool]:
    """Returns the phase and whether it is ambiguous (UNK, or conflicting sources)."""
    raw: str | None = None
    source: PhaseSource = "none"
    if override:
        raw, source = override, "phase.json"
    else:
        for f in PHASE_FIELDS:
            v = row.text(f)
            if v:
                raw, source = v, f
                break
    canonical = normalize_phase(raw)
    ambiguous = canonical == "UNK"
    if not override:
        codes = {normalize_phase(row.text(f)) for f in CONFLICT_FIELDS if row.text(f)}
        ambiguous = ambiguous or len(codes - {"UNK"}) >= 2
    return PhaseInfo(canonical=canonical, raw=raw, source=source), ambiguous


@dataclass(frozen=True)
class PendingWarning:
    code: QcCode
    field: str | None
    message: str
    path_ref: str | None = None


@dataclass
class FileDraft:
    """A resolved file reference; `path` is absolute and guarded, or None if unresolvable."""

    ref: str | None
    path: str | None
    format: VolumeFormat
    explicit: bool = True  # False for the SEG naming convention (missing → missing_seg only)


@dataclass
class Draft:
    item_id: str
    case_id: str
    scan_idx: str
    scope: Scope
    side: Side
    patient_id: str | None
    group: str | None
    phase: PhaseInfo
    status: ItemStatus
    extra: dict[str, Any]
    image: FileDraft | None = None
    mask: FileDraft | None = None
    spacing: tuple[float, ...] | None = None
    line: int = 0
    warnings: list[PendingWarning] = field(default_factory=list)

    def warn(
        self, code: QcCode, field_: str | None, message: str, path_ref: str | None = None
    ) -> None:
        self.warnings.append(PendingWarning(code, field_, message, path_ref))


def _extra(row: Row, consumed: frozenset[str]) -> dict[str, Any]:
    out = {k: v for k, v in row.data.items() if k not in consumed}
    out.update(row.extra)
    return out


def _file(
    d: Draft, resolver: PathResolver, alias: str, raw: str, role: str, *, explicit: bool = True
) -> FileDraft | None:
    """Resolve one path; emits `outside_root` / `missing_path` (invalid) and returns None."""
    try:
        ref = resolver.to_ref(alias, raw)
    except PathOutsideRoot:
        d.warn(QcCode.OUTSIDE_ROOT, role, f"{role} path escapes the data root")
        return None
    except Problem:
        d.warn(QcCode.MISSING_PATH, role, f"{role} path is not a valid relative path")
        return None
    try:
        path = resolver.resolve(ref)
    except PathOutsideRoot:
        d.warn(QcCode.OUTSIDE_ROOT, role, f"{role} resolves outside its root", ref)
        return None
    except Problem:
        d.warn(QcCode.MISSING_PATH, role, f"{role} path cannot be resolved", ref)
        return None
    return FileDraft(ref, str(path), volume_format(raw), explicit)


def _spacing(row: Row) -> tuple[float, ...] | None:
    v = row.extra.get("spacing", row.data.get("spacing"))
    if isinstance(v, list) and len(v) == 3:
        try:
            sp = tuple(float(x) for x in v)
        except (TypeError, ValueError):
            return None
        if all(s > 0 for s in sp):
            return sp
    return None


def _scan_draft(row: Row, ov: PhaseOverrides, resolver: PathResolver, alias: str) -> Draft:
    fname = identity_filename(row)
    phase, ambiguous = resolve_phase(row, ov.lookup(row.case_id, row.scan_idx, fname))
    excluded = is_excluded(row)
    d = Draft(
        item_id=item_id(row.case_id, row.scan_idx, "complete", "-"),
        case_id=row.case_id,
        scan_idx=row.scan_idx,
        scope="complete",
        side="-",
        patient_id=row.text("patient_id"),
        group=row.text("group"),
        phase=phase,
        status="excluded_upstream" if excluded else "active",
        extra=_extra(row, META_CONSUMED),
        line=row.line,
    )
    if excluded:
        return d  # IMP-07: no file checks, no warnings
    if ambiguous:
        d.warn(QcCode.AMBIGUOUS_PHASE, "phase", f"phase {phase.raw!r} is unknown or conflicting")
    raw = image_path(row)
    d.image = _file(d, resolver, alias, raw, "image") if raw else None
    if d.image is None:
        d.status = "missing"
    seg = row.text("seg_path")
    if seg:
        d.mask = _file(d, resolver, alias, seg, "mask")
    elif fname:
        d.mask = _file(d, resolver, alias, seg_convention(fname), "mask", explicit=False)
    if d.mask is None:
        d.warn(QcCode.MISSING_SEG, "mask", "scan has no SEG")
    return d


def _voi_draft(row: Row, parent: Draft | None, resolver: PathResolver, alias: str) -> Draft:
    side = parse_side(row.text("side"))
    if parent is not None:
        phase = parent.phase
        ambiguous = False
    else:
        cat = row.text("phase")
        phase = PhaseInfo(canonical=normalize_phase(cat), raw=cat, source="catalog")
        ambiguous = phase.canonical == "UNK"
    excluded = parent is not None and parent.status == "excluded_upstream"
    d = Draft(
        item_id=item_id(row.case_id, row.scan_idx, "voi", side or "-"),
        case_id=row.case_id,
        scan_idx=row.scan_idx,
        scope="voi",
        side=side or "-",
        patient_id=(parent.patient_id if parent else None) or row.text("patient_id"),
        group=(parent.group if parent else None) or row.text("group"),
        phase=phase,
        status="excluded_upstream" if excluded else "active",
        extra=_extra(row, CATALOG_CONSUMED),
        spacing=_spacing(row),
        line=row.line,
    )
    if excluded:
        return d
    if side is None:
        d.warn(QcCode.AMBIGUOUS_SIDE, "side", f"side {row.text('side')!r} is not L or R")
    if ambiguous:
        d.warn(QcCode.AMBIGUOUS_PHASE, "phase", f"catalog phase {phase.raw!r} is unknown")
    raw = row.text("image_path")
    d.image = _file(d, resolver, alias, raw, "image") if raw else None
    if d.image is None:
        d.status = "missing"
    mraw = row.text("mask_path")
    d.mask = _file(d, resolver, alias, mraw, "mask") if mraw else None
    if mraw is None:
        d.warn(QcCode.MISSING_VOI_MASK, "mask", "VOI has no mask_path")
    return d


def build_drafts(inputs: ParsedInputs, resolver: PathResolver, alias: str) -> list[Draft]:
    """One `complete` draft per metadata row and one `voi` draft per catalog row (deduped)."""
    out: dict[str, Draft] = {}
    dups: dict[str, list[int]] = {}

    def add(d: Draft) -> None:
        first = out.get(d.item_id)
        if first is None:
            out[d.item_id] = d
            return
        lines = dups.setdefault(d.item_id, [first.line])
        lines.append(d.line)

    parents: dict[tuple[str, str], Draft] = {}
    for row in inputs.metadata:
        d = _scan_draft(row, inputs.overrides, resolver, alias)
        add(d)
        parents.setdefault((d.case_id, d.scan_idx), d)
    by_image: dict[tuple[str, str, str], list[Draft]] = {}
    for row in inputs.catalog:
        d = _voi_draft(row, parents.get((row.case_id, row.scan_idx)), resolver, alias)
        add(d)
        if d.image is not None and d.image.ref and out.get(d.item_id) is d:
            by_image.setdefault((d.case_id, d.scan_idx, d.image.ref), []).append(d)
    for group in by_image.values():
        if len(group) > 1:
            for d in group:
                d.warn(QcCode.AMBIGUOUS_SIDE, "side", "several VOI sides point to the same image")
    for iid, lines in dups.items():
        d = out[iid]
        d.warn(
            QcCode.DUPLICATE_ROW_IDENTITY,
            "scan_idx" if d.scope == "complete" else "side",
            f"{len(lines)} rows produce {iid} (lines {', '.join(map(str, lines))}); kept the first",
        )
    return list(out.values())
