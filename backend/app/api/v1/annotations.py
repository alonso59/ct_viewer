"""API-48 analyzer annotations and their activation (ANZ-01/04)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.v1.deps import Ctx
from app.api.v1.imports import ingest_service
from app.core.errors import NotFound, ValidationProblem
from app.core.fsio import iter_jsonl
from app.core.ids import is_ulid

router = APIRouter(tags=["annotations"])
ANNOTATIONS = "annotations.jsonl"


class AnnotationRow(BaseModel):
    run_id: str
    item_id: str
    field: str
    value: str | None = None
    confidence: str | None = None
    evidence: str | None = None
    rules_version: str | None = None
    active: bool = False


class SourceBody(BaseModel):
    run_id: str | None = None


class AnnotationSources(BaseModel):
    annotation_sources: dict[str, str | None]
    job_id: str | None = None  # the reindex job (PRJ-10)


def _runs(ctx: Ctx, pid: str) -> list[str]:
    d = ctx.workspace.project_dir(pid) / "tasks" / "runs"
    if not d.is_dir():
        return []
    return sorted(
        (p.name for p in d.iterdir() if is_ulid(p.name) and (p / ANNOTATIONS).is_file()),
        reverse=True,
    )


@router.get("/projects/{pid}/annotations", response_model=list[AnnotationRow])
def list_annotations(
    ctx: Ctx,
    pid: str,
    field: str | None = None,
    run: str | None = None,
    item_id: str | None = None,
) -> list[AnnotationRow]:
    """Annotations with confidence and evidence; `active` = the run is the field's source."""
    active = ctx.workspace.get(pid).annotation_sources
    pdir = ctx.workspace.project_dir(pid)
    out: list[AnnotationRow] = []
    for rid in _runs(ctx, pid):
        if run is not None and rid != run:
            continue
        for row in iter_jsonl(pdir / "tasks" / "runs" / rid / ANNOTATIONS):
            f = str(row.get("field", ""))
            if (field is not None and f != field) or (
                item_id is not None and row.get("item_id") != item_id
            ):
                continue
            out.append(
                AnnotationRow(
                    run_id=rid,
                    item_id=str(row.get("item_id")),
                    field=f,
                    value=None if row.get("value") is None else str(row["value"]),
                    confidence=row.get("confidence"),
                    evidence=row.get("evidence"),
                    rules_version=row.get("rules_version"),
                    active=active.get(f) == rid,
                )
            )
    return out


@router.get("/projects/{pid}/annotation-sources", response_model=AnnotationSources)
def get_sources(ctx: Ctx, pid: str) -> AnnotationSources:
    return AnnotationSources(annotation_sources=ctx.workspace.get(pid).annotation_sources)


@router.put("/projects/{pid}/annotation-sources/{field}", response_model=AnnotationSources)
async def put_source(ctx: Ctx, pid: str, field: str, body: SourceBody) -> AnnotationSources:
    """ANZ-04: activate a run for one field (or `null`), then rebuild the index."""
    if body.run_id is not None:
        path = ctx.workspace.project_dir(pid) / "tasks" / "runs" / body.run_id / ANNOTATIONS
        if not is_ulid(body.run_id) or not path.is_file():
            raise NotFound(f"Annotation run {body.run_id!r} not found")
        if not any(r.get("field") == field for r in iter_jsonl(path)):
            raise ValidationProblem(
                f"Run {body.run_id} has no {field!r} annotations",
                errors=[{"loc": ["path", "field"], "msg": "not in this run"}],
            )
    await ctx.workspace.set_annotation_source(pid, field, body.run_id)
    ctx.bus.publish(pid, "project.updated", {"fields": ["annotation_sources"]})
    job_id = await ingest_service(ctx).reindex(pid)
    return AnnotationSources(
        annotation_sources=ctx.workspace.get(pid).annotation_sources, job_id=job_id
    )
