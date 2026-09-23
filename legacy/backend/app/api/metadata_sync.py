from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.metadata_sync import MetadataSyncApplyResponse, MetadataSyncPreviewResponse
from app.services.metadata_sync import apply_metadata_sync, preview_metadata_sync


router = APIRouter(tags=["metadata-sync"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected metadata sync error")


@router.get(
    "/api/datasets/{dataset_id}/metadata-sync/preview",
    response_model=MetadataSyncPreviewResponse,
)
def metadata_sync_preview(dataset_id: str) -> MetadataSyncPreviewResponse:
    try:
        return preview_metadata_sync(dataset_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/api/datasets/{dataset_id}/metadata-sync/apply",
    response_model=MetadataSyncApplyResponse,
)
def metadata_sync_apply(dataset_id: str) -> MetadataSyncApplyResponse:
    try:
        return apply_metadata_sync(dataset_id)
    except Exception as exc:
        raise _http_error(exc) from exc
