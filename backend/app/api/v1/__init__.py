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
    mesh,
    phase,
    plugins,
    projects,
    radiomics,
    segmentations,
    source_operations,
    sources,
    tasks,
    variables,
    view,
    volumes,
)

router = APIRouter()
for _module in (
    health, projects, fs, sources, source_operations, imports, variables, cases, items, volumes,
    segmentations, curation, phase, annotations, exports, radiomics, tasks, plugins, labeling,
    dashboard, jobs, events, view, mesh,
):  # fmt: skip
    router.include_router(_module.router)
