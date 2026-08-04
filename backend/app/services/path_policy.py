from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.config import Settings, get_settings


MAX_DATASET_PATH_LENGTH = 4096


class PathPolicyError(ValueError):
    pass


class PathOutsideAllowedRootsError(PermissionError):
    pass


class PathUnreadableError(PermissionError):
    pass


def is_path_value_valid(raw_path: str) -> bool:
    return "\x00" not in raw_path and len(raw_path) <= MAX_DATASET_PATH_LENGTH


def dataset_key(path: Path | str) -> str:
    resolved = Path(path).expanduser().resolve(strict=False)
    normalized = os.path.normcase(str(resolved))
    return hashlib.sha256(os.fsencode(normalized)).hexdigest()[:12]


def allowed_data_roots(settings: Settings | None = None) -> tuple[Path, ...]:
    resolved_settings = settings or get_settings()
    return tuple(
        Path(root).expanduser().resolve(strict=False)
        for root in resolved_settings.allowed_data_roots
    )


def is_path_allowed(path: Path | str, settings: Settings | None = None) -> bool:
    resolved_settings = settings or get_settings()
    if resolved_settings.allow_unrestricted_data_paths:
        return True

    resolved = Path(path).expanduser().resolve(strict=False)
    return any(resolved.is_relative_to(root) for root in allowed_data_roots(resolved_settings))


def require_path_allowed(path: Path | str, settings: Settings | None = None) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    if not is_path_allowed(resolved, settings):
        raise PathOutsideAllowedRootsError(
            "Dataset path is outside the allowed data roots. "
            "Configure ALLOWED_DATA_ROOTS or enable the explicit development override."
        )
    return resolved


def resolve_dataset_path_input(raw_path: str, settings: Settings | None = None) -> Path:
    if "\x00" in raw_path:
        raise PathPolicyError("Dataset path contains a null character")
    if len(raw_path) > MAX_DATASET_PATH_LENGTH:
        raise PathPolicyError(
            f"Dataset path exceeds the maximum length of {MAX_DATASET_PATH_LENGTH} characters"
        )

    cleaned = raw_path.strip()
    if not cleaned:
        raise PathPolicyError("Dataset path is required")

    candidate = Path(cleaned).expanduser()
    try:
        require_path_allowed(candidate.resolve(strict=False), settings)
    except PathOutsideAllowedRootsError:
        raise
    except OSError as exc:
        raise PathPolicyError("Dataset path could not be resolved") from exc
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError("Dataset path does not exist") from exc
    except OSError as exc:
        raise PathPolicyError("Dataset path could not be resolved") from exc

    if not resolved.is_dir():
        raise PathPolicyError("Dataset path is not a directory")
    require_path_allowed(resolved, settings)
    if not os.access(resolved, os.R_OK | os.X_OK):
        raise PathUnreadableError("Dataset path is not readable")
    try:
        with os.scandir(resolved):
            pass
    except OSError as exc:
        raise PathUnreadableError("Dataset path is not readable") from exc
    return resolved


def file_access_status(path: Path | str, settings: Settings | None = None) -> str:
    raw_path = os.fspath(path)
    if not is_path_value_valid(raw_path):
        return "unreadable"
    candidate = Path(raw_path)
    try:
        resolved = candidate.expanduser().resolve(strict=False)
    except OSError:
        return "missing"
    if not is_path_allowed(resolved, settings):
        return "forbidden"
    if not resolved.is_file():
        return "missing"
    if not os.access(resolved, os.R_OK):
        return "unreadable"
    try:
        with resolved.open("rb"):
            pass
    except OSError:
        return "unreadable"
    return "exists"
