from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.models.curation import (
    CorrectionQueueResponse,
    CurationDecision,
    CurationDecisionRequest,
)
from app.services.curation_store import (
    correction_queue_csv,
    get_curation_history,
    list_correction_queue,
    save_curation_decision,
)
from app.services.workspace import validate_workspace_dataset_id


router = APIRouter(tags=["curation"])


def _dataset_path(dataset_id: str):
    try:
        return validate_workspace_dataset_id(dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected curation API error")


@router.get(
    "/api/datasets/{dataset_id}/curation/cases/{case_id}/history",
    response_model=list[CurationDecision],
)
def curation_history(dataset_id: str, case_id: str) -> list[CurationDecision]:
    try:
        return get_curation_history(_dataset_path(dataset_id), dataset_id, case_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/api/datasets/{dataset_id}/curation/decisions",
    response_model=CurationDecision,
)
def curation_decision(dataset_id: str, payload: CurationDecisionRequest) -> CurationDecision:
    try:
        return save_curation_decision(_dataset_path(dataset_id), dataset_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/api/datasets/{dataset_id}/curation/correction-queue",
    response_model=CorrectionQueueResponse,
)
def correction_queue(dataset_id: str) -> CorrectionQueueResponse:
    try:
        return list_correction_queue(_dataset_path(dataset_id), dataset_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/api/datasets/{dataset_id}/curation/correction-queue.csv")
def correction_queue_export(dataset_id: str) -> Response:
    try:
        content = correction_queue_csv(_dataset_path(dataset_id), dataset_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{dataset_id}_correction_queue.csv"'
        },
    )
