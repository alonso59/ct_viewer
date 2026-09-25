"""API-59 dataset table (ADR-0020 §4): rows + active layers, and the list of active layers."""

from __future__ import annotations

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.v1.deps import Ctx
from app.context import AppContext
from app.layers import table
from app.layers.model import Layer, LayerContext, active_layers
from app.variables.schema import SENSITIVE_FIELDS, name_exclusion
from app.variables.service import VariableService

router = APIRouter(tags=["layers"])


class LayerInfo(BaseModel):
    column: str
    id: str
    plugin: str
    field: str
    level: Literal["item", "case", "scan"]
    source: str
    n_values: int


def project_layers(ctx: AppContext, pid: str) -> list[Layer]:
    cfg = ctx.workspace.get(pid)
    lctx = LayerContext(
        project_dir=ctx.workspace.project_dir(pid),
        annotation_sources=dict(cfg.annotation_sources),
        task_owner=ctx.plugins.task_owner(),
    )
    return active_layers(lctx)


@router.get("/projects/{pid}/layers", response_model=list[LayerInfo])
def list_layers(ctx: Ctx, pid: str) -> list[LayerInfo]:
    return [
        LayerInfo(**layer.describe(), n_values=len(layer.values))
        for layer in project_layers(ctx, pid)
    ]


NEVER_EXPORTED: Final = frozenset({"raw_metadata"})  # the DICOM tag blob (NFR-17)


async def dropped_fields(ctx: AppContext, pid: str, include_sensitive: bool) -> frozenset[str]:
    """VAR-09 / NFR-17 in every format: absolute paths and the raw tag blob never leave; UIDs,
    accession numbers, `patient_id`, dates and catalog-`sensitive` fields only on request."""
    cat = await VariableService(ctx.workspace, ctx.index, ctx.locks, ctx.bus).catalog(pid)
    never = NEVER_EXPORTED | {e.name for e in cat.excluded if e.reason == "path"}
    if include_sensitive:
        return never
    extra = {k for i in ctx.index.load(pid).items for k in i.extra}
    return (
        never
        | SENSITIVE_FIELDS
        | {v.name for v in cat.variables if "sensitive" in v.tags}
        | {e.name for e in cat.excluded if e.reason in ("uid", "accession")}
        | {k for k in extra if name_exclusion(k)}  # also fields only excluded items carry
    )


def annotation_refs(ctx: AppContext, pid: str) -> dict[str, str]:
    """ADR-0025: where each active annotation run keeps its full records (ANZ-04)."""
    pdir = ctx.workspace.project_dir(pid)
    out: dict[str, str] = {}
    for fld, run_id in ctx.workspace.get(pid).annotation_sources.items():
        rel = f"tasks/runs/{run_id}/annotations.jsonl"
        if run_id and (pdir / rel).is_file():
            out[fld] = rel
    return out


MEDIA: dict[str, str] = {
    "csv": "text/csv",
    "parquet": "application/vnd.apache.parquet",
    "jsonl": "application/x-ndjson",
}


@router.get(
    "/projects/{pid}/exports/dataset-table",
    response_class=Response,
    responses={200: {"content": {m: {} for m in MEDIA.values()}}},
)
async def dataset_table(
    ctx: Ctx,
    pid: str,
    format: Literal["csv", "parquet", "jsonl"] = "csv",
    include_sensitive: Annotated[
        bool,
        Query(
            description="Also export `sensitive` fields: patient_id, dates, UIDs, accession "
            "numbers (VAR-09). Absolute paths and `raw_metadata` never leave."
        ),
    ] = False,
) -> Response:
    """API-59: `dataset_table.csv|parquet`, or `dataset.jsonl` (ADR-0025), built on demand."""
    layers = project_layers(ctx, pid)
    items = ctx.index.load(pid).items
    drop = await dropped_fields(ctx, pid, include_sensitive)
    if format == "jsonl":
        body, name = table.to_jsonl(items, layers, annotation_refs(ctx, pid), drop), "dataset.jsonl"
    else:
        header, data = table.rows(items, layers, drop)
        body = (
            table.to_parquet(header, data, [x for x in layers if x.field not in drop])
            if format == "parquet"
            else table.to_csv(header, data)
        )
        name = f"dataset_table.{format}"
    return Response(
        body,
        media_type=MEDIA[format],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
