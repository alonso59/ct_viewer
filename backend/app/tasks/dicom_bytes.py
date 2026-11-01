"""Byte-based conversion progress read from the worker's `bytes` events."""

from __future__ import annotations

import math
from typing import Any


def _count(value: Any) -> int | None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    return int(value)


def progress_fields(event: dict[str, Any]) -> dict[str, int]:
    """`bytes_done`, `bytes_total` and, once this attempt converted something, `bytes_per_s`.

    Throughput divides the bytes this attempt converted by the seconds its series took, so
    verified reuse and downtime between attempts do not inflate or dilute it.
    """
    total, done = _count(event.get("total")), _count(event.get("done"))
    if total is None or done is None:
        return {}
    fields = {"bytes_done": min(done, total), "bytes_total": total}
    fresh, seconds = _count(event.get("fresh_bytes")), event.get("fresh_seconds")
    if (
        fresh is not None
        and fresh > 0
        and isinstance(seconds, int | float)
        and math.isfinite(seconds)
        and seconds > 0
    ):
        fields["bytes_per_s"] = max(1, round(fresh / seconds))
    return fields
