"""API-59 dataset table (ADR-0020 §4): rows + active layers, and the list of active layers."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.v1.deps import Ctx
from app.context import AppContext
from app.layers import table
from app.layers.model import Layer, LayerContext, active_layers

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


@router.get(
    "/projects/{pid}/exports/dataset-table",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}, "application/vnd.apache.parquet": {}}}},
)
def dataset_table(ctx: Ctx, pid: str, format: Literal["csv", "parquet"] = "csv") -> Response:
    layers = project_layers(ctx, pid)
    header, data = table.rows(ctx.index.load(pid).items, layers)
    if format == "parquet":
        body, media = table.to_parquet(header, data, layers), "application/vnd.apache.parquet"
    else:
        body, media = table.to_csv(header, data), "text/csv"
    return Response(
        body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="dataset_table.{format}"'},
    )
