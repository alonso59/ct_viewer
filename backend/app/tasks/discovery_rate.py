"""Discovery ETA range from the recent rate of newly read headers.

Reused (unchanged) files and stretches without new reads or progress rows do not count, so
interruption downtime and cached skips never dilute the rate. State is per attempt.
"""

from __future__ import annotations

from collections import deque
from typing import Any

BUCKET_S = 5.0
WINDOW = 12
STALL_S = 10.0
MIN_NEW = 2000
MIN_ACTIVE_S = 30.0


class DiscoveryRate:
    def __init__(self) -> None:
        self._rates: deque[float] = deque(maxlen=WINDOW)
        self._active = 0.0
        self._start: float | None = None
        self._start_read = 0
        self._last: tuple[float, int] | None = None

    def update(self, now: float, read: int, files: int, files_total: int | None) -> dict[str, Any]:
        stalled = self._last is None or now - self._last[0] > STALL_S or read == self._last[1]
        self._last = (now, read)
        if stalled or self._start is None:
            self._start, self._start_read = now, read
        elif now - self._start >= BUCKET_S:
            elapsed = now - self._start
            if read > self._start_read:
                self._rates.append((read - self._start_read) / elapsed)
                self._active += elapsed
            self._start, self._start_read = now, read
        if (
            files_total is None
            or not self._rates
            or (read < MIN_NEW and self._active < MIN_ACTIVE_S)
        ):
            return {"low_s": None, "high_s": None, "basis": "unknown"}
        remaining = max(files_total - files, 0)
        return {
            "low_s": round(remaining / max(self._rates)),
            "high_s": round(remaining / min(self._rates)),
            "basis": "recent_rate",
        }
