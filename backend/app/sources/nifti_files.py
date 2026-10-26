"""Adapter `nifti-files`: a folder or one file of NIfTI volumes → contract v1 rows. File names
only (headers are read later by the index job).

A pattern with `/` matches the relative path without extension (one folder per case); otherwise
the file stem. A `mask_template` names each image's mask from its groups; a template that names a
folder of NIfTI files is a mask set (one binary file per structure, composed on read)."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.ingest.schemas import ParsedFile
from app.sources import formats
from app.sources.identity import IdentityRegistry, slug

VERSION = "2"
DEFAULT_PATTERN = r"^(?P<case_id>.+)$"  # one case per file stem
# one case per image folder (its parent, at any depth); scans numbered within it
FOLDER_PATTERN = r"^(?:.*/)?(?P<case_id>[^/]+)/[^/]+$"
CONVENTIONS = ("seg/{name}", "suffix:_seg", "suffix:_mask")
MASK_DIRS = {"seg", "masks"}
GROUPS = ("case_id", "scan_idx", "channel", "modality", "phase", "side")
SAMPLE = 50
PLACEHOLDERS = {"stem", "dir"}  # besides the pattern's groups
_FIELD = re.compile(r"{(\w*)}")
# `seg/{name minus _0000}`: the metadata-v1 / converter layout
_SEG_SUFFIX = re.compile(r"_0000$")
MODALITY_CODES = {"MRI": "MR"}  # DICOM codes


class NiftiOptions(BaseModel):
    pattern: str = DEFAULT_PATTERN
    case_id_from: Literal["pattern", "stem", "sequential"] = "pattern"
    mask_conventions: list[str] = Field(default_factory=lambda: list(CONVENTIONS))
    modality: str = Field("CT", min_length=1, max_length=16)
    include: list[str] | None = None  # explicit relative file list
    # image rel → mask rel: the segmentation attached in Open mode, carried into the import
    # ("Create project from this" / "Add to project…"); these files are not items
    masks: dict[str, str] | None = None
    # relative to the root, e.g. `LabelTr/{case_id}/segmentations`: a file, or a folder = a mask set
    mask_template: str | None = Field(None, min_length=1, max_length=512)

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

    @model_validator(mode="after")
    def _template(self) -> NiftiOptions:
        t = self.mask_template
        if t is None:
            return self
        if t.startswith("/") or ".." in t.split("/"):
            raise ValueError("mask_template must stay inside the root (no leading / or ..)")
        allowed = set(re.compile(self.pattern).groupindex) | PLACEHOLDERS
        unknown = set(_FIELD.findall(t)) - allowed
        if unknown:
            raise ValueError(f"mask_template uses {sorted(unknown)}; allowed {sorted(allowed)}")
        return self


class NiftiPlan(BaseModel):
    rows: list[dict[str, Any]]
    sample: list[ParsedFile]
    unmatched: list[str]  # names the pattern did not match
    orphan_masks: list[str]  # mask-like files with no image
    skipped_channels: int = 0  # non-first channels folded into their channel-0000 row
    # files that gave an already used (case_id, scan_idx): `case/scan: first, other`
    collisions: list[str] = Field(default_factory=list)
    registry: IdentityRegistry
    ignored: dict[str, int]


def _is_mask(rel: str, conventions: list[str]) -> bool:
    parts = rel.lower().split("/")
    st = formats.stem(parts[-1])
    if len(parts) > 1 and any(p in MASK_DIRS for p in parts[:-1]):
        return "seg/{name}" in conventions
    return ("suffix:_seg" in conventions and st.endswith("_seg")) or (
        "suffix:_mask" in conventions and st.endswith("_mask")
    )


def _mask_for(rel: str, masks: dict[str, str], conventions: list[str]) -> str | None:
    """First convention that names an existing mask file; `masks`: lower rel → rel."""
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


def _subject(rel: str, by_path: bool) -> str:
    """What the pattern fullmatches: the relative path without extension, or the file stem."""
    st = formats.stem(posixpath.basename(rel))
    return posixpath.join(posixpath.dirname(rel), st) if by_path else st


def _groups(m: re.Match[str] | None) -> dict[str, str]:
    return {k: v for k, v in (m.groupdict() if m else {}).items() if v}


def _template_target(template: str, rel: str, groups: dict[str, str]) -> str | None:
    """The mask path a template names for one image; None when a field has no value."""
    fields = {
        **groups,
        "stem": formats.stem(posixpath.basename(rel)),
        "dir": posixpath.dirname(rel),
    }
    try:
        target = posixpath.normpath(template.format_map(fields))
    except (KeyError, ValueError, IndexError):
        return None
    return None if target.startswith("..") else target


def plan(root: Path, opts: NiftiOptions, registry: IdentityRegistry) -> NiftiPlan:
    """Rows for every image file; masks found by template or convention are not items."""
    reg = registry.model_copy(deep=True)
    reg.strategy = "filename_pattern"
    s = formats.scan(root, opts.include)
    files = s.files["nifti"]
    rx = re.compile(opts.pattern)
    by_path = "/" in opts.pattern
    folders: dict[str, list[str]] = {}
    for f in files:
        folders.setdefault(posixpath.dirname(f), []).append(f)
    by_template: dict[str, str] = {}  # image → mask file, or a folder of NIfTI files (mask set)
    if opts.mask_template:
        lower = {f.lower(): f for f in files}
        for rel in files:
            m = rx.fullmatch(_subject(rel, by_path))
            target = _template_target(opts.mask_template, rel, _groups(m)) if m else None
            hit = None if target is None else lower.get(target.lower())
            if hit is None and target in folders:
                hit = target
            if hit is not None and hit != rel:
                by_template[rel] = hit
    templated = set(by_template.values())
    explicit = {k: v for k, v in (opts.masks or {}).items() if v in files}
    mask_files = [
        f
        for f in files
        if f in explicit.values()
        or f in templated
        or posixpath.dirname(f) in templated
        or _is_mask(f, opts.mask_conventions)
    ]
    masks = {f.lower(): f for f in mask_files}
    images = [f for f in files if f.lower() not in masks]
    if opts.include is not None and not images and mask_files:
        images, masks = mask_files, {}  # one file explicitly chosen: it is the item
    # one value per structure name across the import, so a name means the same label everywhere
    names = sorted(
        {
            formats.stem(posixpath.basename(f))
            for d in templated & folders.keys()
            for f in folders[d]
        }
    )
    set_values = {n: v for v, n in enumerate(names, start=1)}
    used_masks: set[str] = set()
    rows: list[dict[str, Any]] = []
    sample: list[ParsedFile] = []
    unmatched: list[str] = []
    collisions: list[str] = []
    skipped = 0
    by_first: dict[tuple[str, str], dict[str, Any]] = {}
    for rel in images:
        subject = _subject(rel, by_path)
        m = rx.fullmatch(subject)
        g = _groups(m)
        channel = g.get("channel")
        if m is None:
            unmatched.append(subject if by_path else posixpath.basename(rel))
        key = g.get("case_id") or subject
        if opts.case_id_from == "sequential":
            case_id = reg.case_id(key)
        elif opts.case_id_from == "pattern" and "case_id" in g:
            case_id = slug(g["case_id"])
        else:
            case_id = slug(subject)
        scan_idx = slug(g.get("scan_idx") or reg.scan_idx(key, subject))
        first = by_first.get((case_id, scan_idx))
        if first is not None:
            if channel in (None, "0000"):
                collisions.append(f"{case_id}/{scan_idx}: {first['relative_path']}, {rel}")
            else:
                first.setdefault("channels", []).append(rel)
                skipped += 1
            continue
        mask = (
            explicit.get(rel)
            or by_template.get(rel)
            or (_mask_for(rel, masks, opts.mask_conventions) if masks else None)
        )
        if mask:
            used_masks.add(mask)
            used_masks.update(folders.get(mask, []) if mask in templated else [])
        modality = g.get("modality")
        modality = MODALITY_CODES.get(modality, modality) if modality else opts.modality
        row: dict[str, Any] = {
            "case_id": case_id,
            "scan_idx": scan_idx,
            "relative_path": rel,
            "modality": modality,
            "source_kind": "nifti",
            "source_name": subject,
        }
        if mask:
            row["seg_path"] = mask
            if mask in folders and mask in templated:
                members = {formats.stem(posixpath.basename(f)) for f in folders[mask]}
                row["seg_labels"] = {n: set_values[n] for n in sorted(members)}
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
        collisions=collisions,
        registry=reg,
        ignored=dict(s.ignored),
    )
