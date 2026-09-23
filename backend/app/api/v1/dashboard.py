"""API-38 dashboard views (DB-*) and API-39 guided analyses (ANA-*).

API-38 is `POST /projects/{pid}/radiomics/runs/{rid}/views/{view}`; each view slug
(DASHBOARD.md §Views) has its own route so request and response bodies are typed in the
OpenAPI contract. An unknown slug is `not-found`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Header, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.analytics import views as vw
from app.analytics.data import Frame
from app.analytics.models import (
    Analysis,
    AnalysisList,
    AnalysisSpec,
    AssociationRequest,
    AssociationResponse,
    BalanceRequest,
    BalanceResponse,
    ConsistencyRequest,
    ConsistencyResponse,
    CorrelationRequest,
    CorrelationResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    FeatureDistributionRequest,
    FeatureDistributionResponse,
    FeatureVsVolumeRequest,
    FeatureVsVolumeResponse,
    GroupComparisonRequest,
    GroupComparisonResponse,
    MissingMatrixRequest,
    MissingMatrixResponse,
    OutliersRequest,
    OutliersResponse,
    RunOverviewRequest,
    RunOverviewResponse,
    ViewRequest,
)
from app.analytics.service import AnalysisService, DashboardService, ExportFile
from app.api.v1.deps import Ctx
from app.core.errors import NotFound

router = APIRouter(tags=["dashboard"])
VIEWS = "/projects/{pid}/radiomics/runs/{rid}/views"


def dashboard(ctx: Ctx) -> DashboardService:
    return DashboardService(ctx.workspace, ctx.index, ctx.locks, ctx.bus)


def analyses(ctx: Ctx) -> AnalysisService:
    return AnalysisService(ctx.workspace, ctx.index, ctx.locks, ctx.bus)


async def _view[Q: ViewRequest, R: BaseModel](
    ctx: Ctx, pid: str, rid: str, body: Q, fn: Callable[[Frame, Q], R]
) -> R:
    return await dashboard(ctx).view(pid, rid, body, fn)


@router.post(f"{VIEWS}/run-overview", response_model=RunOverviewResponse)
async def run_overview(
    pid: str, rid: str, ctx: Ctx, body: RunOverviewRequest | None = None
) -> RunOverviewResponse:
    """Run overview: items ok/failed, per-label counts, runtime, errors -> item (API-38)."""
    return await dashboard(ctx).run_overview(pid, rid, body or RunOverviewRequest())


@router.post(f"{VIEWS}/feature-distribution", response_model=FeatureDistributionResponse)
async def feature_distribution(
    pid: str, rid: str, body: FeatureDistributionRequest, ctx: Ctx
) -> FeatureDistributionResponse:
    """Histogram / box of one feature split by a color variable (DB-03/07)."""
    return await _view(ctx, pid, rid, body, vw.feature_distribution)


@router.post(f"{VIEWS}/missing-matrix", response_model=MissingMatrixResponse)
async def missing_matrix(
    pid: str, rid: str, ctx: Ctx, body: MissingMatrixRequest | None = None
) -> MissingMatrixResponse:
    """Feature x item NaN/inf/absent cells, sparse (DB-05)."""
    return await _view(ctx, pid, rid, body or MissingMatrixRequest(), vw.missing_matrix)


@router.post(f"{VIEWS}/correlation", response_model=CorrelationResponse)
async def correlation(
    pid: str, rid: str, ctx: Ctx, body: CorrelationRequest | None = None
) -> CorrelationResponse:
    """Spearman correlation between features, clustered order."""
    return await _view(ctx, pid, rid, body or CorrelationRequest(), vw.correlation)


@router.post(f"{VIEWS}/embedding", response_model=EmbeddingResponse)
async def embedding(
    pid: str, rid: str, ctx: Ctx, body: EmbeddingRequest | None = None
) -> EmbeddingResponse:
    """PCA (default) or UMAP (optional extra) on z-scored features (DB-03/07)."""
    return await _view(ctx, pid, rid, body or EmbeddingRequest(), vw.embedding)


@router.post(f"{VIEWS}/outliers", response_model=OutliersResponse)
async def outliers(
    pid: str, rid: str, ctx: Ctx, body: OutliersRequest | None = None
) -> OutliersResponse:
    """Robust z-score (median/MAD) per item; top-N items and features."""
    return await _view(ctx, pid, rid, body or OutliersRequest(), vw.outliers)


@router.post(f"{VIEWS}/feature-vs-volume", response_model=FeatureVsVolumeResponse)
async def feature_vs_volume(
    pid: str, rid: str, body: FeatureVsVolumeRequest, ctx: Ctx
) -> FeatureVsVolumeResponse:
    """Scatter of a feature against shape MeshVolume; size-driven features ranked."""
    return await _view(ctx, pid, rid, body, vw.feature_vs_volume)


@router.post(f"{VIEWS}/group-comparison", response_model=GroupComparisonResponse)
async def group_comparison(
    pid: str, rid: str, body: GroupComparisonRequest, ctx: Ctx
) -> GroupComparisonResponse:
    """Box per group + test for one feature, results for all features (ANA-03..07)."""
    return await _view(ctx, pid, rid, body, vw.group_comparison)


@router.post(f"{VIEWS}/association", response_model=AssociationResponse)
async def association(
    pid: str, rid: str, body: AssociationRequest, ctx: Ctx
) -> AssociationResponse:
    """Scatter feature x continuous variable with rho; ranked table (ANA-04/05)."""
    return await _view(ctx, pid, rid, body, vw.association)


@router.post(f"{VIEWS}/balance", response_model=BalanceResponse)
async def balance(pid: str, rid: str, body: BalanceRequest, ctx: Ctx) -> BalanceResponse:
    """Contingency heat map of two categorical variables with chi2 / Fisher."""
    return await _view(ctx, pid, rid, body, vw.balance)


@router.post(f"{VIEWS}/phase-side-consistency", response_model=ConsistencyResponse)
async def phase_side_consistency(
    pid: str, rid: str, body: ConsistencyRequest, ctx: Ctx
) -> ConsistencyResponse:
    """Same case across phases or sides, Bland-Altman style."""
    return await _view(ctx, pid, rid, body, vw.consistency)


@router.post(VIEWS + "/{view}", include_in_schema=False)
async def unknown_view(pid: str, rid: str, view: str) -> None:
    raise NotFound(f"Unknown view {view!r}")


# -- API-39 -----------------------------------------------------------------------------------


@router.post("/projects/{pid}/analyses", response_model=Analysis, status_code=201)
async def create_analysis(
    pid: str,
    body: AnalysisSpec,
    ctx: Ctx,
    x_reviewer: Annotated[str | None, Header()] = None,
) -> Analysis:
    """Create and run an analysis synchronously (ANA-01..08); saved under `analyses/`."""
    return await analyses(ctx).create(pid, body, x_reviewer)


@router.get("/projects/{pid}/analyses", response_model=AnalysisList)
async def list_analyses(
    pid: str, ctx: Ctx, run_id: Annotated[str | None, Query()] = None
) -> AnalysisList:
    """Saved analyses, newest first (optionally for one run)."""
    return await analyses(ctx).list(pid, run_id)


@router.get("/projects/{pid}/analyses/{aid}", response_model=Analysis)
async def get_analysis(pid: str, aid: str, ctx: Ctx) -> Analysis:
    """Results + descriptives + recommendations (DB-08)."""
    return await analyses(ctx).get(pid, aid)


@router.get(
    "/projects/{pid}/analyses/{aid}/export",
    response_class=FileResponse,
    responses={
        200: {
            "description": "tidy/results/descriptives CSV, or the spec JSON (ANA-09)",
            "content": {
                "text/csv": {"schema": {"type": "string"}},
                "application/json": {"schema": {"type": "object"}},
            },
        }
    },
)
async def export_analysis(
    pid: str, aid: str, ctx: Ctx, file: Annotated[ExportFile, Query()] = "tidy"
) -> FileResponse:
    """ANA-09: `tidy` (unit rows x ids + variables + features), `results`, `descriptives`
    CSV, or `spec` JSON."""
    path, media, name = analyses(ctx).export_path(pid, aid, file)
    return FileResponse(path, media_type=media, filename=name)
