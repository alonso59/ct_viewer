"""IDs and timestamps (DATA_MODEL.md §item_id, §Conventions)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from ulid import ULID

Scope = Literal["complete", "voi"]
Side = Literal["L", "R", "-"]

CASE_ID_RE = re.compile(r"^case_\d{5}$")
ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
ITEM_ID_RE = re.compile(r"^(case_\d{5})\.([A-Za-z0-9_-]+)\.(complete|voi)\.(L|R|-)$")


def new_ulid() -> str:
    return str(ULID())


def is_ulid(value: str) -> bool:
    return bool(ULID_RE.match(value))


def item_id(case_id: str, scan_idx: str, scope: Scope, side: Side) -> str:
    """`{case_id}.{scan_idx}.{scope}.{side}`: deterministic and URL-safe (IMP-06)."""
    return f"{case_id}.{scan_idx}.{scope}.{side}"


def parse_item_id(value: str) -> tuple[str, str, Scope, Side] | None:
    m = ITEM_ID_RE.match(value)
    if not m:
        return None
    scope: Scope = "voi" if m.group(3) == "voi" else "complete"
    side_s = m.group(4)
    side: Side = "L" if side_s == "L" else "R" if side_s == "R" else "-"
    return m.group(1), m.group(2), scope, side


def utc_now() -> str:
    """UTC ISO-8601 with `Z`, second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
