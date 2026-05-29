from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models.dataset_browser import (
    DatasetBrowserListResponse,
    DatasetBrowserRootsResponse,
    WorkspaceSelectionValidationRequest,
    WorkspaceSelectionValidationResponse,
)
from app.services.dataset_browser import (
    dataset_browser_roots,
    list_dataset_browser_path,
    validate_workspace_selection,
)


router = APIRouter(tags=["dataset-browser"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected dataset browser error")


@router.get("/api/dataset-browser/roots", response_model=DatasetBrowserRootsResponse)
def roots() -> DatasetBrowserRootsResponse:
    return DatasetBrowserRootsResponse(roots=dataset_browser_roots())


@router.get("/api/dataset-browser/list", response_model=DatasetBrowserListResponse)
def list_path(path: str = Query(...)) -> DatasetBrowserListResponse:
    try:
        return list_dataset_browser_path(path)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/api/workspace/validate-selection",
    response_model=WorkspaceSelectionValidationResponse,
)
def validate_selection(
    payload: WorkspaceSelectionValidationRequest,
) -> WorkspaceSelectionValidationResponse:
    try:
        return validate_workspace_selection(payload)
    except Exception as exc:
        raise _http_error(exc) from exc
