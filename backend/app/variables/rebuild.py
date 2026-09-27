"""Coalesced variable-catalog rebuilds after layer writes (LBL-06, PHS-03 → VAR-12)."""

from __future__ import annotations

import asyncio
from typing import Any, Final

REBUILD_DELAY_S: Final = 1.0
_rebuilds: dict[str, asyncio.Task[None]] = {}


def rebuild_pending(pid: str) -> bool:
    """A scheduled rebuild has not finished yet (tests wait on this, not on a sleep)."""
    t = _rebuilds.get(pid)
    return t is not None and not t.done()


def schedule_variables_rebuild(pid: str, rebuild: Any) -> None:
    """Rebuild the variable catalog once writes settle (coalesced per project)."""
    old = _rebuilds.get(pid)
    if old is not None and not old.done():
        old.cancel()

    async def later() -> None:
        await asyncio.sleep(REBUILD_DELAY_S)
        await rebuild(pid)

    task = asyncio.get_running_loop().create_task(later())
    _rebuilds[pid] = task
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
