"""Each dashboard view has its own route so request and response bodies are typed in OpenAPI;
an unknown view is `not-found`. Views read an analysis table; the radiomics-run paths of the
same views stay as unlisted aliases."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import FileResponse

from app.analytics import views as vw
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
)
from app.analytics.service import AnalysisService, DashboardService, ExportFile
from app.api.v1.deps import Ctx
from app.core.errors import NotFound

router = APIRouter(tags=["dashboard"])
VIEWS = "/projects/{pid}/tables/{tid}/views"
RUN_VIEWS = "/projects/{pid}/radiomics/runs/{tid}/views"


def view_route(slug: str, model: Any) -> Callable[[Any], Any]:
    """Register a view under the table path and, unlisted, under the radiomics-run path."""

    def register(fn: Any) -> Any:
        router.post(f"{RUN_VIEWS}/{slug}", response_model=model, include_in_schema=False)(fn)
        return router.post(f"{VIEWS}/{slug}", response_model=model)(fn)

    return register


def dashboard(ctx: Ctx) -> DashboardService:
    return DashboardService(ctx.workspace, ctx.index, ctx.locks, ctx.bus)


def analyses(ctx: Ctx) -> AnalysisService:
    return AnalysisService(ctx.workspace, ctx.index, ctx.locks, ctx.bus)


@view_route("run-overview", RunOverviewResponse)
async def run_overview(
    pid: str, tid: str, ctx: Ctx, body: RunOverviewRequest | None = None
) -> RunOverviewResponse:
    """Overview of the table and its producer run: items ok/failed, per-label counts, runtime,
    errors -> item."""
    return await dashboard(ctx).run_overview(pid, tid, body or RunOverviewRequest())


@view_route("feature-distribution", FeatureDistributionResponse)
async def feature_distribution(
    pid: str, tid: str, body: FeatureDistributionRequest, ctx: Ctx
) -> FeatureDistributionResponse:
    """Histogram / box of one feature split by a color variable."""
    return await dashboard(ctx).view(pid, tid, body, vw.feature_distribution)


@view_route("missing-matrix", MissingMatrixResponse)
async def missing_matrix(
    pid: str, tid: str, ctx: Ctx, body: MissingMatrixRequest | None = None
) -> MissingMatrixResponse:
    """Feature x item NaN/inf/absent cells, sparse."""
    return await dashboard(ctx).view(pid, tid, body or MissingMatrixRequest(), vw.missing_matrix)


@view_route("correlation", CorrelationResponse)
async def correlation(
    pid: str, tid: str, ctx: Ctx, body: CorrelationRequest | None = None
) -> CorrelationResponse:
    """Spearman correlation between features, clustered order."""
    return await dashboard(ctx).view(pid, tid, body or CorrelationRequest(), vw.correlation)


@view_route("embedding", EmbeddingResponse)
async def embedding(
    pid: str, tid: str, ctx: Ctx, body: EmbeddingRequest | None = None
) -> EmbeddingResponse:
    """PCA on z-scored features."""
    return await dashboard(ctx).view(pid, tid, body or EmbeddingRequest(), vw.embedding)


@view_route("outliers", OutliersResponse)
async def outliers(
    pid: str, tid: str, ctx: Ctx, body: OutliersRequest | None = None
) -> OutliersResponse:
    """Robust z-score (median/MAD) per item; top-N items and features."""
    return await dashboard(ctx).view(pid, tid, body or OutliersRequest(), vw.outliers)


@view_route("feature-vs-volume", FeatureVsVolumeResponse)
async def feature_vs_volume(
    pid: str, tid: str, body: FeatureVsVolumeRequest, ctx: Ctx
) -> FeatureVsVolumeResponse:
    """Scatter of a feature against the table's volume; size-driven features ranked."""
    return await dashboard(ctx).view(pid, tid, body, vw.feature_vs_volume)


@view_route("group-comparison", GroupComparisonResponse)
async def group_comparison(
    pid: str, tid: str, body: GroupComparisonRequest, ctx: Ctx
) -> GroupComparisonResponse:
    """Box per group + test for one feature, results for all features."""
    return await dashboard(ctx).view(pid, tid, body, vw.group_comparison)


@view_route("association", AssociationResponse)
async def association(
    pid: str, tid: str, body: AssociationRequest, ctx: Ctx
) -> AssociationResponse:
    """Scatter feature x continuous variable with rho; ranked table."""
    return await dashboard(ctx).view(pid, tid, body, vw.association)


@view_route("balance", BalanceResponse)
async def balance(pid: str, tid: str, body: BalanceRequest, ctx: Ctx) -> BalanceResponse:
    """Contingency heat map of two categorical variables with chi2 / Fisher."""
    return await dashboard(ctx).view(pid, tid, body, vw.balance)


@view_route("phase-side-consistency", ConsistencyResponse)
async def phase_side_consistency(
    pid: str, tid: str, body: ConsistencyRequest, ctx: Ctx
) -> ConsistencyResponse:
    """Same case across phases or sides, Bland-Altman style."""
    return await dashboard(ctx).view(pid, tid, body, vw.consistency)


@router.post(RUN_VIEWS + "/{view}", include_in_schema=False)
@router.post(VIEWS + "/{view}", include_in_schema=False)
async def unknown_view(pid: str, tid: str, view: str) -> None:
    raise NotFound(f"Unknown view {view!r}")


@router.post("/projects/{pid}/analyses", response_model=Analysis, status_code=201)
async def create_analysis(
    pid: str,
    body: AnalysisSpec,
    ctx: Ctx,
    x_reviewer: Annotated[str | None, Header()] = None,
) -> Analysis:
    """Create and run an analysis synchronously; saved under `analyses/`."""
    return await analyses(ctx).create(pid, body, x_reviewer)


@router.get("/projects/{pid}/analyses", response_model=AnalysisList)
async def list_analyses(
    pid: str,
    ctx: Ctx,
    table_id: Annotated[str | None, Query()] = None,
    run_id: Annotated[str | None, Query(include_in_schema=False)] = None,
) -> AnalysisList:
    """Saved analyses, newest first (optionally for one table)."""
    return await analyses(ctx).list(pid, table_id or run_id)


@router.get("/projects/{pid}/analyses/{aid}", response_model=Analysis)
async def get_analysis(pid: str, aid: str, ctx: Ctx) -> Analysis:
    """Results + descriptives + recommendations."""
    return await analyses(ctx).get(pid, aid)


@router.get(
    "/projects/{pid}/analyses/{aid}/export",
    response_class=FileResponse,
    responses={
        200: {
            "description": "tidy/results/descriptives CSV, or the spec JSON",
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
    """`tidy` (unit rows x ids + variables + features), `results`, `descriptives` CSV,
    or `spec` JSON."""
    path, media, name = analyses(ctx).export_path(pid, aid, file)
    return FileResponse(path, media_type=media, filename=name)
