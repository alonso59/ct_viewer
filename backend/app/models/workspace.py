from __future__ import annotations

from pydantic import BaseModel


class WorkspaceStatus(BaseModel):
    configured: bool
    dataset_id: str | None = None
    dataset_path: str | None = None
    database_csv_path: str | None = None
    workspace_dir: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    dataset_path: str
    database_csv_path: str | None = None
