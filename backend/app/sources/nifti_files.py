"""Adapter `nifti-files` (SRC-04/05, SOURCES.md §NIfTI files): a folder or one file of NIfTI
volumes → contract v1 rows. File names only (headers are read later by the index job).

nnU-Net dataset naming (`{case}_{channel:04d}` stems, `imagesTr/`/`labelsTr/`) is not a core
convention: it belongs to the pending nnU-Net plugin (TSK-08). The default is one case per stem;
a user pattern may still name a `channel` group."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.ingest.schemas import ParsedFile
from app.sources import formats
from app.sources.identity import IdentityRegistry, slug

ADAPTER = "nifti-files"
VERSION = "1"
DEFAULT_PATTERN = r"^(?P<case_id>.+)$"  # one case per file stem
CONVENTIONS = ("seg/{name}", "suffix:_seg", "suffix:_mask")
MASK_DIRS = {"seg", "masks"}
GROUPS = ("case_id", "scan_idx", "channel", "modality", "phase", "side")
SAMPLE = 50
# `seg/{name minus _0000}`: the metadata-v1 / converter layout (INPUT_METADATA `seg_path`)
_SEG_SUFFIX = re.compile(r"_0000$")
MODALITY_CODES = {"MRI": "MR"}  # DICOM codes (DCM-12)


class NiftiOptions(BaseModel):
    pattern: str = DEFAULT_PATTERN
    case_id_from: Literal["pattern", "stem", "sequential"] = "pattern"
    mask_conventions: list[str] = Field(default_factory=lambda: list(CONVENTIONS))
    modality: str = Field("CT", min_length=1, max_length=16)
    include: list[str] | None = None  # explicit relative file list (SRC-05)
    # image rel → mask rel: the segmentation attached in Open mode, carried into the import
    # ("Create project from this" / "Add to project…", ADR-0027); these files are not items
    masks: dict[str, str] | None = None

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            rx = re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from None
        unknown = set(rx.groupindex) - set(GROUPS)
        if unknown:
            raise ValueError(f"unknown named groups {sorted(unknown)}; allowed {list(GROUPS)}")
        return v

    @field_validator("mask_conventions")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        bad = [c for c in v if c not in CONVENTIONS]
        if bad:
            raise ValueError(f"unknown mask conventions {bad}; allowed {list(CONVENTIONS)}")
        return v


class NiftiPlan(BaseModel):
    rows: list[dict[str, Any]]
    sample: list[ParsedFile]
    unmatched: list[str]  # names the pattern did not match
    orphan_masks: list[str]  # mask-like files with no image
    skipped_channels: int = 0  # non-first channels folded into their channel-0000 row
    registry: IdentityRegistry


def _is_mask(rel: str, conventions: list[str]) -> bool:
    parts = rel.lower().split("/")
    st = formats.stem(parts[-1])
    if len(parts) > 1 and any(p in MASK_DIRS for p in parts[:-1]):
        return "seg/{name}" in conventions
    return ("suffix:_seg" in conventions and st.endswith("_seg")) or (
        "suffix:_mask" in conventions and st.endswith("_mask")
    )


def _mask_for(rel: str, masks: dict[str, str], conventions: list[str]) -> str | None:
    """First convention that names an existing mask file (SRC-04); `masks`: lower rel → rel."""
    d, name = posixpath.split(rel)
    st = formats.stem(name)
    base = _SEG_SUFFIX.sub("", st)
    ext = formats.extension(name)
    cands: list[str] = []
    for conv in conventions:
        if conv == "seg/{name}":
            cands += [f"seg/{name}", f"seg/{base}{ext}", f"seg/{base}.nii.gz"]
            if d:
                cands += [posixpath.join(posixpath.dirname(d), "seg", f"{base}.nii.gz")]
        else:
            suffix = conv.removeprefix("suffix:")
            for s in (st, base):
                cands += [posixpath.join(d, f"{s}{suffix}{e}") for e in (ext, ".nii.gz", ".nii")]
    for c in cands:
        hit = masks.get(posixpath.normpath(c).lower())
        if hit is not None:
            return hit
    return None


def plan(root: Path, opts: NiftiOptions, registry: IdentityRegistry) -> NiftiPlan:
    """Rows for every image file; masks found by convention are not items (SRC-04)."""
    reg = registry.model_copy(deep=True)
    reg.strategy = "filename_pattern"
    s = formats.scan(root, opts.include)
    files = s.files["nifti"]
    explicit = {k: v for k, v in (opts.masks or {}).items() if v in files}
    mask_files = [f for f in files if f in explicit.values() or _is_mask(f, opts.mask_conventions)]
    masks = {f.lower(): f for f in mask_files}
    images = [f for f in files if f.lower() not in masks]
    if opts.include is not None and not images and mask_files:
        images, masks = mask_files, {}  # one file explicitly chosen: it is the item
    rx = re.compile(opts.pattern)
    used_masks: set[str] = set()
    rows: list[dict[str, Any]] = []
    sample: list[ParsedFile] = []
    unmatched: list[str] = []
    skipped = 0
    by_first: dict[tuple[str, str], dict[str, Any]] = {}
    for rel in images:
        name = posixpath.basename(rel)
        st = formats.stem(name)
        m = rx.fullmatch(st)
        g = {k: v for k, v in (m.groupdict() if m else {}).items() if v}
        channel = g.get("channel")
        if m is None:
            unmatched.append(name)
        key = g.get("case_id") or st
        if opts.case_id_from == "sequential":
            case_id = reg.case_id(key)
        elif opts.case_id_from == "pattern" and "case_id" in g:
            case_id = slug(g["case_id"])
        else:
            case_id = slug(st)
        scan_idx = g.get("scan_idx") or reg.scan_idx(key, st)
        scan_idx = slug(scan_idx)
        if channel not in (None, "0000") and (case_id, scan_idx) in by_first:
            by_first[(case_id, scan_idx)].setdefault("channels", []).append(rel)
            skipped += 1
            continue
        mask = explicit.get(rel) or (
            _mask_for(rel, masks, opts.mask_conventions) if masks else None
        )
        if mask:
            used_masks.add(mask)
        modality = g.get("modality")
        modality = MODALITY_CODES.get(modality, modality) if modality else opts.modality
        row: dict[str, Any] = {
            "case_id": case_id,
            "scan_idx": scan_idx,
            "relative_path": rel,
            "modality": modality,
            "source_kind": "nifti",
            "source_name": st,
        }
        if mask:
            row["seg_path"] = mask
        if g.get("phase"):
            row["phase"] = g["phase"]
        if channel:
            row["channel"] = channel
        if g.get("side"):
            row["side"] = g["side"]
        rows.append(row)
        by_first[(case_id, scan_idx)] = row
        if len(sample) < SAMPLE:
            sample.append(
                ParsedFile(
                    file=rel,
                    case_id=case_id,
                    scan_idx=scan_idx,
                    modality=modality,
                    phase=g.get("phase"),
                    channel=channel,
                    mask=mask,
                    matched=m is not None,
                )
            )
    orphans = sorted(set(mask_files) - used_masks) if masks else []
    return NiftiPlan(
        rows=rows,
        sample=sample,
        unmatched=unmatched,
        orphan_masks=orphans,
        skipped_channels=skipped,
        registry=reg,
    )
