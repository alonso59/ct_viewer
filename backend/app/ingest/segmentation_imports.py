"""Attach existing NIfTI masks as a manual segmentation set.

Source volumes are read only. The project stores an immutable manifest of alias references and
rebuilds the derived item index from it, like task-produced segmentation sets.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Literal

from pydantic import BaseModel, Field

from app.context import AppContext
from app.core.errors import JobConflict, ValidationProblem
from app.core.fsio import atomic_write_json, write_jsonl_atomic
from app.core.ids import new_ulid, utc_now
from app.core.paths import is_within, realpath
from app.imaging import maskset
from app.imaging.header import compare_geometry
from app.ingest.indexer import FileProbe, ItemProbe, ItemProbeResult, batches, probe_batch
from app.ingest.segsets import IMPORTS, MASKS
from app.jobs.types import JobInfo, JobSpec, WorkUnit
from app.projects.labels import match_labels
from app.projects.models import LabelEntry, SegmentationSet
from app.projects.presets import AUTO_LABEL_COLORS, auto_label_name
from app.sources.formats import classify

ImportMode = Literal["auto", "combined", "binary"]
ALLOWED_FIELDS = frozenset({"case_id", "scan_idx", "item_id", "side", "scope"})


class SegmentationImportRequest(BaseModel):
    seg_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(default="", max_length=200)
    root: str = Field(min_length=1)
    template: str = Field(default="{case_id}.nii.gz", min_length=1, max_length=500)
    mode: ImportMode = "auto"
    item_id: str | None = None


class SegmentationImportStarted(BaseModel):
    import_id: str
    job_id: str
    matched: int
    missing: int


@dataclass(frozen=True)
class _Candidate:
    item_id: str
    case_id: str
    image_path: str
    mask_path: str
    ref: str
    mode: Literal["combined", "binary"]
    members: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Planned:
    candidate: _Candidate
    labels: dict[str, int] | None


def _render(template: str, values: dict[str, str]) -> str:
    fields: set[str] = set()
    try:
        parts = list(Formatter().parse(template))
    except ValueError as exc:
        raise ValidationProblem(f"Invalid mask template: {exc}") from None
    for _literal, field, spec, conversion in parts:
        if field is None:
            continue
        if field not in ALLOWED_FIELDS or spec or conversion:
            raise ValidationProblem(
                f"Mask template field {field!r} is not supported",
                errors=[{"loc": ["body", "template"], "msg": "invalid placeholder"}],
            )
        fields.add(field)
    if not fields:
        raise ValidationProblem(
            "Mask template must identify items with a placeholder",
            errors=[{"loc": ["body", "template"], "msg": "placeholder required"}],
        )
    rendered = template.format_map(values).replace("\\", "/")
    path = Path(rendered)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationProblem(
            "Mask template must stay below the selected folder",
            errors=[{"loc": ["body", "template"], "msg": "path escapes root"}],
        )
    return rendered


def _source_alias(ctx: AppContext, pid: str, root: Path) -> str:
    matches = []
    for entry in ctx.workspace.get(pid).path_roots:
        candidate = realpath(entry.path)
        if entry.role == "source" and is_within(root, candidate):
            matches.append((len(candidate.parts), entry.alias))
    if not matches:
        raise ValidationProblem(
            "Segmentation path must be inside a source root already registered in this project",
            errors=[{"loc": ["body", "root"], "msg": "not under a project source root"}],
        )
    return max(matches)[1]


def _plan(
    ctx: AppContext, pid: str, body: SegmentationImportRequest
) -> tuple[list[_Planned], int, Literal["combined", "binary"]]:
    raw_root = Path(body.root)
    if not raw_root.is_absolute():
        raise ValidationProblem(
            "Segmentation path must be absolute",
            errors=[{"loc": ["body", "root"], "msg": "not absolute"}],
        )
    root = ctx.guard.check(raw_root)
    if not root.exists():
        raise ValidationProblem(
            "Segmentation path does not exist",
            errors=[{"loc": ["body", "root"], "msg": "not found"}],
        )
    alias = _source_alias(ctx, pid, root)
    resolver = ctx.workspace.resolver(pid)
    items = [
        item
        for item in ctx.index.load(pid).items
        if item.status == "active" and item.image is not None
    ]
    if body.item_id:
        items = [item for item in items if item.item_id == body.item_id]
        if not items:
            raise ValidationProblem(
                f"Item {body.item_id!r} is not active in this project",
                errors=[{"loc": ["body", "item_id"], "msg": "unknown item"}],
            )
    if root.is_file() and len(items) != 1:
        raise ValidationProblem(
            "A single mask file needs one selected item",
            errors=[{"loc": ["body", "item_id"], "msg": "select an item"}],
        )

    candidates: list[_Candidate] = []
    missing = 0
    for item in items:
        image = item.image
        if image is None:
            continue
        if root.is_file():
            path = root
        else:
            rel = _render(
                body.template,
                {
                    "case_id": item.case_id,
                    "scan_idx": item.scan_idx,
                    "item_id": item.item_id,
                    "side": item.side,
                    "scope": item.scope,
                },
            )
            path = root / rel
        if not path.exists():
            missing += 1
            continue
        ref = resolver.to_ref(alias, str(path))
        path = resolver.resolve(ref)
        members: tuple[str, ...] = ()
        if path.is_dir():
            try:
                files = maskset.members(path)
            except (OSError, ValueError) as exc:
                raise ValidationProblem(f"Cannot read mask folder {path.name}: {exc}") from None
            if not files:
                missing += 1
                continue
            mode: Literal["combined", "binary"] = "binary"
            members = tuple(maskset.member_name(p) for p in files)
        elif classify(path) == "nifti":
            mode = "combined"
        else:
            raise ValidationProblem(
                f"Segmentation path is not a NIfTI file or mask folder: {path.name}"
            )
        candidates.append(
            _Candidate(
                item.item_id,
                item.case_id,
                str(resolver.resolve(image.ref)),
                str(path),
                ref,
                mode,
                members,
            )
        )
    if not candidates:
        raise ValidationProblem(
            "The template did not find a segmentation for any active item",
            errors=[{"loc": ["body", "template"], "msg": "no matches"}],
        )
    modes = {candidate.mode for candidate in candidates}
    if len(modes) != 1:
        raise ValidationProblem("One import cannot mix combined files and binary-mask folders")
    mode = next(iter(modes))
    if body.mode != "auto" and body.mode != mode:
        raise ValidationProblem(
            f"Expected {body.mode} masks, but the template found {mode} masks",
            errors=[{"loc": ["body", "mode"], "msg": "format differs"}],
        )
    values = {
        name: value
        for value, name in enumerate(
            sorted({name for candidate in candidates for name in candidate.members}), start=1
        )
    }
    planned = [
        _Planned(
            candidate,
            ({name: values[name] for name in candidate.members} if mode == "binary" else None),
        )
        for candidate in candidates
    ]
    return planned, missing, mode


def _combined_labels(
    values: set[int], label_map: list[LabelEntry]
) -> tuple[dict[str, int], list[int], list[LabelEntry]]:
    existing = {entry.value for entry in label_map}
    colors = list(AUTO_LABEL_COLORS)
    new = [
        LabelEntry(
            value=value,
            name=auto_label_name(value),
            color=colors[(len(label_map) + n) % len(colors)],
            opacity=0.2,
        )
        for n, value in enumerate(sorted(values - existing))
    ]
    return {str(value): value for value in sorted(values)}, sorted(values - existing), new


async def start_import(
    ctx: AppContext, pid: str, body: SegmentationImportRequest
) -> SegmentationImportStarted:
    planned, missing, mode = await asyncio.to_thread(_plan, ctx, pid, body)
    current = ctx.workspace.get(pid).segmentation(body.seg_id, include_removed=True)
    if current is not None and current.active:
        raise JobConflict(
            f"Segmentation set {body.seg_id!r} already exists; remove it before reimporting"
        )
    probes = [
        ItemProbe(
            p.candidate.item_id,
            image=FileProbe(p.candidate.image_path),
            mask=FileProbe(p.candidate.mask_path, labels=p.labels is None),
        )
        for p in planned
    ]
    results: dict[str, ItemProbeResult] = {}
    import_id = new_ulid()

    async def on_result(batch: list[ItemProbeResult]) -> None:
        results.update((result.item_id, result) for result in batch)

    async def on_finish(info: JobInfo) -> str | None:
        if info.status != "succeeded":
            return import_id
        rows: list[dict[str, object]] = []
        values: set[int] = set()
        rejected: list[dict[str, str]] = []
        for plan in planned:
            result = results.get(plan.candidate.item_id)
            image = result.image if result else None
            mask = result.mask if result else None
            error = None
            if image is None or image.error or image.header is None:
                error = (image.error if image else None) or "image could not be read"
            elif mask is None or not mask.exists or mask.error or mask.header is None:
                error = (mask.error if mask else None) or "mask could not be read"
            else:
                issues = compare_geometry(image.header, mask.header)
                if issues:
                    error = f"{' and '.join(issues)} differ from image"
            if error:
                rejected.append({"item_id": plan.candidate.item_id, "error": error})
                continue
            assert mask is not None and mask.header is not None
            if plan.labels is None:
                values.update(mask.labels)
            else:
                values.update(plan.labels.values())
            rows.append(
                {
                    "item_id": plan.candidate.item_id,
                    "ref": plan.candidate.ref,
                    "format": mask.header.format,
                    "fp": mask.fp,
                    "labels": plan.labels,
                    "labels_present": list(mask.labels) if plan.labels is None else [],
                }
            )
        if not rows:
            raise ValidationProblem("No segmentation matched its image geometry")

        mapping: dict[str, int] = {}
        unmatched: list[int] = []

        def edit(label_map: list[LabelEntry]) -> list[LabelEntry]:
            nonlocal mapping, unmatched
            if mode == "binary":
                all_names = {
                    name: value for plan in planned for name, value in (plan.labels or {}).items()
                }
                names = {str(value): name for name, value in all_names.items()}
                mapping, unmatched, new = match_labels(names, label_map)
            else:
                mapping, unmatched, new = _combined_labels(values, label_map)
            return [*label_map, *new]

        await ctx.workspace.edit_label_map(pid, edit)
        folder = ctx.workspace.project_dir(pid) / IMPORTS / import_id
        async with ctx.locks(pid):
            write_jsonl_atomic(folder / MASKS, rows)
            atomic_write_json(
                folder / "source.json",
                {
                    "seg_id": body.seg_id,
                    "name": body.name,
                    "root": body.root,
                    "template": body.template,
                    "mode": mode,
                    "created_at": utc_now(),
                },
            )
            atomic_write_json(
                folder / "report.json",
                {
                    "matched": len(rows),
                    "missing": missing,
                    "rejected": rejected,
                },
            )
        await ctx.workspace.put_segmentation(
            pid,
            SegmentationSet(
                seg_id=body.seg_id,
                name=body.name.strip(),
                kind="manual",
                artifact_id=import_id,
                label_mapping=mapping,
                unmatched=unmatched,
                created_at=utc_now(),
            ),
        )
        from app.ingest.service import IngestService

        await IngestService(
            ctx.workspace, ctx.index, ctx.jobs, ctx.bus, ctx.locks, ctx.after_index
        ).reapply_segmentations(pid)
        ctx.bus.publish(pid, "project.updated", {"fields": ["segmentations", "label_map"]})
        return import_id

    job_id = new_ulid()
    ctx.jobs.submit(
        JobSpec(
            project_id=pid,
            kind="index",
            units=[WorkUnit(probe_batch, (batch,)) for batch in batches(probes)],
            on_result=on_result,
            on_finish=on_finish,
            ref=import_id,
            job_id=job_id,
            drain_workers=True,
        )
    )
    return SegmentationImportStarted(
        import_id=import_id,
        job_id=job_id,
        matched=len(planned),
        missing=missing,
    )
