from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.review import ReviewApplyRequest, ReviewApplyResponse, ReviewDeleteDecision
from app.services.review_apply import (
    apply_review_operations,
    list_recent_delete_decisions,
    undo_delete_decision,
)


router = APIRouter(tags=["review"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected review apply error")


@router.post(
    "/api/datasets/{dataset_id}/review/apply",
    response_model=ReviewApplyResponse,
)
def review_apply(dataset_id: str, payload: ReviewApplyRequest) -> ReviewApplyResponse:
    if len(payload.operations) == 0:
        raise HTTPException(status_code=400, detail="At least one operation is required")
    try:
        return apply_review_operations(dataset_id, payload.operations)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/api/datasets/{dataset_id}/review/deletions",
    response_model=list[ReviewDeleteDecision],
)
def review_deletions(dataset_id: str) -> list[ReviewDeleteDecision]:
    try:
        return list_recent_delete_decisions(dataset_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/api/datasets/{dataset_id}/review/undo-delete/{decision_id}",
    response_model=ReviewApplyResponse,
)
def review_undo_delete(dataset_id: str, decision_id: str) -> ReviewApplyResponse:
    try:
        return undo_delete_decision(dataset_id, decision_id)
    except Exception as exc:
        raise _http_error(exc) from exc
