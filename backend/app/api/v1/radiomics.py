"""API-30/32/36 radiomics: engine schema, profiles, feature exports (RAD-01/03/10).

Validate, estimate and runs are the generic task endpoints API-43..47 for the builtin task
`radiomics.pyradiomics` (RAD-13); API-31/33/34/35/37 were their aliases and are retired (AUD-A4-09).

Engine-dependent endpoints answer 503 `server-busy` when the optional `[radiomics]` extra
is not installed (ADR-0006).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response

from app.api.v1.deps import Ctx
from app.api.v1.paging import Page, Paging, paginate
from app.radiomics.models import (
    FeaturesTable,
    Profile,
    ProfileCreate,
    ProfilePatch,
    SettingsSchema,
)
from app.radiomics.service import RadiomicsService, to_csv, to_parquet

router = APIRouter(tags=["radiomics"])

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
