"""API v1 router aggregation. One module per resource group (API.md)."""

from fastapi import APIRouter

from app.api.v1 import (
    cases,
    curation,
    dashboard,
    events,
    fs,
    health,
    imports,
    items,
    jobs,
    projects,
    radiomics,
    variables,
    volumes,
)

router = APIRouter()
for _module in (
    health, projects, fs, imports, variables, cases, items, volumes, curation, radiomics,
    dashboard, jobs, events,
):  # fmt: skip
    router.include_router(_module.router)
