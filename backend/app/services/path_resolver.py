from __future__ import annotations

import os
from pathlib import Path

from app.models.database import PathStatus


def resolve_database_path(dataset_path: Path | str, raw_value: str | None) -> PathStatus:
    raw = (raw_value or "").strip()
    if not raw:
        return PathStatus(raw=None, resolved=None, status="not_provided")

    raw_path = Path(raw).expanduser()
    candidates: list[Path] = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        root = Path(dataset_path).expanduser().resolve()
        candidates.append(root / raw_path)
        candidates.extend(parent / raw_path for parent in root.parents)
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

    for candidate in normalized:
        if candidate.is_file():
            return PathStatus(
                raw=raw,
                resolved=str(candidate),
                status="exists" if os.access(candidate, os.R_OK) else "unreadable",
            )

    first = normalized[0] if normalized else raw_path
    return PathStatus(raw=raw, resolved=str(first), status="missing")


def path_exists(status: PathStatus) -> bool:
    return status.status == "exists" and bool(status.resolved)


def path_is_unreadable(status: PathStatus) -> bool:
    return status.status == "unreadable"
