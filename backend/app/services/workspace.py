from __future__ import annotations

from pathlib import Path

from app.models.workspace import WorkspaceInspection, WorkspaceStatus
from app.services.path_policy import resolve_dataset_path_input
from app.services.workspace_inspector import inspect_workspace_dataset_path
from app.services.workspace_store import workspace_store


def get_workspace_status() -> WorkspaceStatus:
    status = workspace_store.get()
    if not status.configured or not status.dataset_path:
        return status
    try:
        resolved = resolve_dataset_path_input(status.dataset_path)
    except (FileNotFoundError, PermissionError, ValueError):
        return WorkspaceStatus(configured=False, recent_datasets=status.recent_datasets)
    return status.model_copy(
        update={
            "dataset_id": resolved.name,
            "dataset_path": str(resolved),
        }
    )


def inspect_workspace(dataset_path: str) -> WorkspaceInspection:
    return inspect_workspace_dataset_path(dataset_path)


def require_workspace_dataset_path() -> Path:
    status = workspace_store.get()
    if not status.configured or not status.dataset_path:
        raise RuntimeError("No dataset workspace configured. Select a dataset folder first.")
    return resolve_dataset_path_input(status.dataset_path)


def set_workspace_dataset_path(dataset_path: str) -> WorkspaceStatus:
    inspection = inspect_workspace_dataset_path(dataset_path)
    if not inspection.valid:
        raise ValueError(
            f"Dataset cannot be activated because it is classified as '{inspection.dataset_kind}'."
        )

    previous = workspace_store.get()
    next_status = workspace_store.set(
        Path(inspection.dataset_path),
        inspection.dataset_kind,
    )
    if previous.dataset_key != next_status.dataset_key:
        from app.services.runtime_cache import reset_runtime_caches

        reset_runtime_caches()
    return next_status


def clear_workspace(recent_key: str | None = None) -> WorkspaceStatus:
    previous = workspace_store.get()
    if recent_key:
        next_status = workspace_store.remove_recent(recent_key)
    else:
        next_status = workspace_store.clear()

    if previous.dataset_key and previous.dataset_key != next_status.dataset_key:
        from app.services.runtime_cache import reset_runtime_caches

        reset_runtime_caches()
    return next_status


def validate_workspace_dataset_id(dataset_id: str) -> Path:
    dataset_path = require_workspace_dataset_path()
    if dataset_path.name != dataset_id:
        raise FileNotFoundError(
            f"Dataset '{dataset_id}' is not the active workspace. Active dataset is '{dataset_path.name}'."
        )
    return dataset_path


def workspace_file(filename: str, *, create: bool = True) -> Path:
    dataset_path = require_workspace_dataset_path()
    from app.services.state_dir import dataset_state_file

    return dataset_state_file(dataset_path, filename, create=create)
