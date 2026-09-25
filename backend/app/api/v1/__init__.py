"""API v1 router aggregation. One module per resource group (API.md)."""

from fastapi import APIRouter

from app.api.v1 import (
    annotations,
    cases,
    curation,
    dashboard,
    events,
    exports,
    fs,
    health,
    imports,
    items,
    jobs,
    labeling,
    phase,
    plugins,
    projects,
    radiomics,
    segmentations,
    sources,
    tasks,
    variables,
    view,
    volumes,
)
from app.imaging import mesh_api

router = APIRouter()
for _module in (
    health, projects, fs, sources, imports, variables, cases, items, volumes, segmentations,
    curation, phase, annotations, exports, radiomics, tasks, plugins, labeling, dashboard, jobs,
    events, view,
):  # fmt: skip
    router.include_router(_module.router)
router.include_router(mesh_api.router)  # API-25 (lane P3)
