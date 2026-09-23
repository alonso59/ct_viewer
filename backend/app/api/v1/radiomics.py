"""API-30..37 radiomics: schema, validate, profiles, estimate, runs, exports (RAD-*).

Engine-dependent endpoints answer 503 `server-busy` when the optional `[radiomics]` extra
is not installed (ADR-0006).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Query, Response

from app.api.v1.deps import Ctx
from app.api.v1.paging import Page, Paging, paginate
from app.radiomics.models import (
    EstimateRequest,
    EstimateResult,
    FeaturesTable,
    Profile,
    ProfileCreate,
    ProfilePatch,
    RunDetail,
    RunError,
    RunRequest,
    RunSummary,
    SettingsSchema,
    ValidateRequest,
    ValidateResult,
)
from app.radiomics.service import RadiomicsService, to_csv, to_parquet

router = APIRouter(tags=["radiomics"])

Reviewer = Annotated[
    str | None, Header(description="Reviewer name or initials; recorded in run.json (RAD-09)")
]
_FILE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {"text/csv": {}, "application/vnd.apache.parquet": {}},
        "description": "Features as JSON (FeaturesTable), CSV or Parquet",
    }
}


def radiomics_service(ctx: Ctx) -> RadiomicsService:
    return RadiomicsService(ctx.workspace, ctx.index, ctx.jobs, ctx.bus, ctx.locks)


@router.get("/radiomics/schema", response_model=SettingsSchema)
def get_schema(ctx: Ctx) -> SettingsSchema:
    """API-30 (RAD-01/02): every engine option with type, default, constraints and group."""
    return radiomics_service(ctx).engine().schema()


@router.post("/radiomics/validate", response_model=ValidateResult)
def validate_settings(body: ValidateRequest, ctx: Ctx) -> ValidateResult:
    """API-31 (RAD-04): issues (errors + the normalize/HU warning) with field locations."""
    return radiomics_service(ctx).validate(body)


@router.get("/projects/{pid}/radiomics/profiles", response_model=Page[Profile])
def list_profiles(pid: str, ctx: Ctx, paging: Paging) -> Page[Profile]:
    """API-32 (RAD-03): saved profiles, by name."""
    return paginate(radiomics_service(ctx).list_profiles(pid), paging)


@router.post(
    "/projects/{pid}/radiomics/profiles",
    response_model=Profile,
    status_code=201,
    responses={200: {"model": Profile, "description": "Identical settings already saved"}},
)
async def create_profile(pid: str, body: ProfileCreate, ctx: Ctx, response: Response) -> Profile:
    """API-32 (RAD-03): save settings; content-addressed by `profile_hash` (200 if it exists)."""
    prof, created = await radiomics_service(ctx).create_profile(pid, body)
    if not created:
        response.status_code = 200
    return prof


@router.patch("/projects/{pid}/radiomics/profiles/{phash}", response_model=Profile)
async def rename_profile(pid: str, phash: str, body: ProfilePatch, ctx: Ctx) -> Profile:
    """API-32 (RAD-03): rename. `phash` is `sha256:<hex>` or `<hex>`."""
    return await radiomics_service(ctx).rename_profile(pid, phash, body.name)


@router.delete("/projects/{pid}/radiomics/profiles/{phash}", response_model=Page[Profile])
async def delete_profile(pid: str, phash: str, ctx: Ctx, paging: Paging) -> Page[Profile]:
    """API-32 (RAD-03): delete a profile → remaining profiles (runs keep their snapshot)."""
    svc = radiomics_service(ctx)
    await svc.delete_profile(pid, phash)
    return paginate(svc.list_profiles(pid), paging)


@router.post("/projects/{pid}/radiomics/estimate", response_model=EstimateResult)
async def estimate(pid: str, body: EstimateRequest, ctx: Ctx) -> EstimateResult:
    """API-33 (RAD-11): n_items x n_labels and time per item from a 3-item worker sample."""
    return await radiomics_service(ctx).estimate(pid, body)


@router.post("/projects/{pid}/radiomics/runs", response_model=RunDetail, status_code=202)
async def start_run(pid: str, body: RunRequest, ctx: Ctx, x_reviewer: Reviewer = None) -> RunDetail:
    """API-34 (RAD-05/06/09): validate and start a background run. 428 without `X-Reviewer`."""
    return await radiomics_service(ctx).start(pid, body, x_reviewer)


@router.get("/projects/{pid}/radiomics/runs", response_model=Page[RunSummary])
async def list_runs(pid: str, ctx: Ctx, paging: Paging) -> Page[RunSummary]:
    """API-34: runs, newest first; stale `running` runs are reported `interrupted` (BE-06)."""
    return paginate(await radiomics_service(ctx).list_runs(pid), paging)


@router.get("/projects/{pid}/radiomics/runs/{rid}", response_model=RunDetail)
async def get_run(pid: str, rid: str, ctx: Ctx) -> RunDetail:
    """API-34 (RAD-09): the run record plus live progress while its job runs."""
    return await radiomics_service(ctx).get(pid, rid)


@router.post("/projects/{pid}/radiomics/runs/{rid}/cancel", response_model=RunDetail)
async def cancel_run(pid: str, rid: str, ctx: Ctx) -> RunDetail:
    """API-35 (RAD-06): cancel; idempotent for finished runs."""
    return await radiomics_service(ctx).cancel(pid, rid)


@router.post(
    "/projects/{pid}/radiomics/runs/{rid}/resume", response_model=RunDetail, status_code=202
)
async def resume_run(pid: str, rid: str, ctx: Ctx) -> RunDetail:
    """API-35 (RAD-08): resume an interrupted/cancelled/failed run, skipping finished parts."""
    return await radiomics_service(ctx).resume(pid, rid)


@router.get(
    "/projects/{pid}/radiomics/runs/{rid}/features",
    response_model=FeaturesTable,
    responses=_FILE_RESPONSES,
)
def get_features(
    pid: str,
    rid: str,
    ctx: Ctx,
    format: Annotated[Literal["json", "parquet", "csv"], Query()] = "json",
    shape: Annotated[Literal["long", "wide"], Query()] = "long",
    item_id: Annotated[str | None, Query(description="Only this item (Measurements)")] = None,
) -> Any:
    """API-36 (RAD-10, UI-14): long or wide features as JSON, CSV or Parquet."""
    svc = radiomics_service(ctx)
    table = svc.features(pid, rid, item_id, shape)
    if format == "json":
        return svc.features_json(rid, table, shape)
    name = f"features_{rid}_{shape}"
    if format == "csv":
        return Response(
            to_csv(table),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
        )
    return Response(
        to_parquet(table),
        media_type="application/vnd.apache.parquet",
        headers={"Content-Disposition": f'attachment; filename="{name}.parquet"'},
    )


@router.get("/projects/{pid}/radiomics/runs/{rid}/errors", response_model=Page[RunError])
def get_errors(pid: str, rid: str, ctx: Ctx, paging: Paging) -> Page[RunError]:
    """API-37 (RAD-07): per-item failures and label-absent skips."""
    return paginate(radiomics_service(ctx).errors(pid, rid), paging)
