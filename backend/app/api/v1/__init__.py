from fastapi import APIRouter

from app.api.v1 import (
    annotations,
    cases,
    cohort,
    ctflow,
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
    logs,
    mesh,
    phase,
    plugins,
    projects,
    radiomics,
    segmentations,
    source_batches,
    source_operations,
    sources,
    tasks,
    variables,
    view,
    voi,
    volumes,
)

router = APIRouter()
for _module in (
    health, projects, fs, sources, source_operations, source_batches, imports, variables, cases,
    cohort, items, volumes, segmentations, curation, phase, annotations, exports, radiomics, tasks,
    plugins, labeling, dashboard, jobs, logs, ctflow, events, view, mesh, voi,
):  # fmt: skip
    router.include_router(_module.router)
