from __future__ import annotations

from pathlib import Path

from app.models.database import PathStatus
from app.services.path_policy import file_access_status, is_path_allowed, is_path_value_valid


def resolve_database_path(dataset_path: Path | str, raw_value: str | None) -> PathStatus:
    raw = (raw_value or "").strip()
    if not raw:
        return PathStatus(raw=None, resolved=None, status="not_provided")
    if not is_path_value_valid(raw):
        return PathStatus(raw=raw, resolved=None, status="unreadable")

    raw_path = Path(raw).expanduser()
    candidates: list[Path] = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        root = Path(dataset_path).expanduser().resolve()
        candidates.append(root / raw_path)
        candidates.extend(parent / raw_path for parent in root.parents if is_path_allowed(parent))
        if is_path_allowed(Path.cwd()):
            candidates.append(Path.cwd() / raw_path)

    seen: set[str] = set()
    normalized: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            resolved = candidate.absolute()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(resolved)

    saw_forbidden = False
    saw_unreadable = False
    for candidate in normalized:
        access_status = file_access_status(candidate)
        if access_status == "forbidden":
            saw_forbidden = True
            continue
        if access_status == "unreadable":
            saw_unreadable = True
            continue
        if access_status == "exists":
            return PathStatus(
                raw=raw,
                resolved=str(candidate),
                status="exists",
            )

    if saw_forbidden:
        return PathStatus(raw=raw, resolved=None, status="forbidden")
    if saw_unreadable:
        return PathStatus(raw=raw, resolved=None, status="unreadable")

    first = normalized[0] if normalized else raw_path
    return PathStatus(raw=raw, resolved=str(first), status="missing")


def path_exists(status: PathStatus) -> bool:
    return status.status == "exists" and bool(status.resolved)


def path_is_unreadable(status: PathStatus) -> bool:
    return status.status == "unreadable"


def path_is_forbidden(status: PathStatus) -> bool:
    return status.status == "forbidden"
