from __future__ import annotations

import os
from pathlib import Path

from app.models.workspace import WorkspaceStatus
from app.services.state_dir import dataset_state_dir
from app.services.workspace_store import workspace_store


REQUIRED_DATASET_MARKERS = ("database.csv", "metadata.jsonl", "nifti", "seg", "voi", "manifest.csv")


def get_workspace_status() -> WorkspaceStatus:
    status = workspace_store.get()
    if not status.configured:
        return status

    dataset_path = Path(status.dataset_path or "").expanduser().resolve()
    if not dataset_path.is_dir():
        return workspace_store.clear()

    return WorkspaceStatus(
        configured=True,
        dataset_id=dataset_path.name,
        dataset_path=str(dataset_path),
        workspace_dir=str(dataset_state_dir(dataset_path)),
    )


def require_workspace_dataset_path() -> Path:
    status = get_workspace_status()
    if not status.configured or not status.dataset_path:
        raise RuntimeError("No dataset workspace configured. Select a dataset folder first.")
    return Path(status.dataset_path).expanduser().resolve()


def set_workspace_dataset_path(dataset_path: str) -> WorkspaceStatus:
    return set_workspace_selection(dataset_path)


def set_workspace_selection(
    dataset_path: str,
    database_csv_path: str | Path | None = None,
) -> WorkspaceStatus:
    candidate = Path(dataset_path).expanduser().resolve()
    _validate_dataset_path(candidate)
    from app.services.runtime_cache import reset_runtime_caches

    reset_runtime_caches()
    return workspace_store.set(candidate, resolved_database)


def clear_workspace() -> WorkspaceStatus:
    from app.services.runtime_cache import reset_runtime_caches

    reset_runtime_caches()
    return workspace_store.clear()


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


def _validate_dataset_path(dataset_path: Path) -> None:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset path '{dataset_path}' does not exist")
    if not dataset_path.is_dir():
        raise ValueError(f"Dataset path '{dataset_path}' is not a directory")

    has_marker = False
    for marker in REQUIRED_DATASET_MARKERS:
        candidate = dataset_path / marker
        if Path(marker).suffix:
            if candidate.is_file():
                has_marker = True
                break
        elif candidate.is_dir():
            has_marker = True
            break

    if not has_marker:
        raise ValueError(
            "Selected folder is not a dataset directory. Expected one of: database.csv, metadata.jsonl, nifti/, seg/, voi/, manifest.csv"
        )


def _validate_database_csv_path(database_csv_path: str | Path | None) -> Path | None:
    if database_csv_path is None:
        return None
    candidate = Path(database_csv_path).expanduser().resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"database.csv path '{candidate}' does not exist")
    if not candidate.is_file():
        raise ValueError(f"database.csv path '{candidate}' is not a file")
    if candidate.name != "database.csv":
        raise ValueError(f"database.csv path '{candidate}' must be named database.csv")
    if not os.access(candidate, os.R_OK):
        raise PermissionError(f"database.csv path '{candidate}' is not readable")
    return candidate
