from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.workspace import WorkspaceStatus, WorkspaceUpdateRequest
from app.services.workspace import clear_workspace, get_workspace_status, set_workspace_dataset_path


router = APIRouter(tags=["workspace"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected workspace error")


@router.get("/api/workspace", response_model=WorkspaceStatus)
def get_workspace() -> WorkspaceStatus:
    try:
        return get_workspace_status()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/api/workspace", response_model=WorkspaceStatus)
def put_workspace(payload: WorkspaceUpdateRequest) -> WorkspaceStatus:
    try:
        return set_workspace_dataset_path(payload.dataset_path)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/api/workspace", response_model=WorkspaceStatus)
def delete_workspace() -> WorkspaceStatus:
    try:
        return clear_workspace()
    except Exception as exc:
        raise _http_error(exc) from exc
