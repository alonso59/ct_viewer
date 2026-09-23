"""`project.json` forward migrations (PRJ-11).

`MIGRATIONS[v]` turns a raw v`v` document into v`v+1`. Empty while format_version is 1.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.errors import FormatVersionUnsupported
from app.projects.models import FORMAT, FORMAT_VERSION

Migration = Callable[[dict[str, Any]], dict[str, Any]]

MIGRATIONS: dict[int, Migration] = {}


def check_version(raw: object) -> int:
    """Return the document's format_version; raise unless it is ours and not newer."""
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise FormatVersionUnsupported(f"Not a {FORMAT} document")
    version = raw.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise FormatVersionUnsupported("format_version must be an integer")
    if version > FORMAT_VERSION:
        raise FormatVersionUnsupported(
            f"project.json format_version {version} is newer than supported {FORMAT_VERSION}"
        )
    return version


def migrate(raw: dict[str, Any], version: int) -> dict[str, Any]:
    """Apply migrations from `version` up to FORMAT_VERSION."""
    while version < FORMAT_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise FormatVersionUnsupported(f"No migration from format_version {version}")
        raw = step(dict(raw))
        version += 1
        raw["format_version"] = version
    return raw
