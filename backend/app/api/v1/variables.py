"""API-16..18 study variables (VAR-*)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, UploadFile

from app.api.v1.deps import Ctx
from app.variables.models import Catalog, DerivedDef, ExternalReport, VariableOverride
from app.variables.service import VariableService

router = APIRouter(tags=["variables"])


def variable_service(ctx: Ctx) -> VariableService:
    return VariableService(ctx.workspace, ctx.index, ctx.locks, ctx.bus)


@router.get("/projects/{pid}/variables", response_model=Catalog)
async def get_variables(pid: str, ctx: Ctx) -> Catalog:
    """Catalog with profiles (VAR-01..05, 08, 09); profiles lazily after the first index."""
    return await variable_service(ctx).catalog(pid)


@router.patch("/projects/{pid}/variables/{name}", response_model=Catalog)
async def patch_variable(pid: str, name: str, body: VariableOverride, ctx: Ctx) -> Catalog:
    """Confirm or override the type; set visibility and tags (VAR-03/05)."""
    return await variable_service(ctx).patch(pid, name, body)


@router.post("/projects/{pid}/variables/derived", response_model=Catalog, status_code=201)
async def add_derived(pid: str, body: DerivedDef, ctx: Ctx) -> Catalog:
    """Bin / recode / dominant (VAR-06)."""
    return await variable_service(ctx).add_derived(pid, body)


@router.delete("/projects/{pid}/variables/derived/{name}", response_model=Catalog)
async def delete_derived(pid: str, name: str, ctx: Ctx) -> Catalog:
    return await variable_service(ctx).delete_derived(pid, name)


@router.post("/projects/{pid}/variables/external", response_model=ExternalReport, status_code=201)
async def import_external(
    pid: str,
    ctx: Ctx,
    file: Annotated[UploadFile, File(description="CSV or TSV keyed by case_id or patient_id")],
    key: Annotated[Literal["case_id", "patient_id"] | None, Form()] = None,
) -> ExternalReport:
    """External case-keyed table → match report (VAR-07)."""
    data = await file.read()
    return await variable_service(ctx).import_external(pid, data, file.filename or "table.csv", key)
