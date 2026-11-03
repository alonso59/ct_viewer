"""Interactive console sessions (CTF-08): variables, procedures and the current project, kept in
server memory with an idle timeout. A server restart clears them; durable work is never here."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.core.errors import NotFound
from app.core.ids import new_ulid
from app.ctflow.lang import Proc

IDLE_S = 4 * 3600
MAX_SESSIONS = 64


@dataclass
class Session:
    id: str
    vars: dict[str, str] = field(default_factory=dict)
    procs: dict[str, Proc] = field(default_factory=dict)
    project: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    used: float = field(default_factory=time.monotonic)


class Sessions:
    def __init__(self, idle_s: float = IDLE_S, limit: int = MAX_SESSIONS) -> None:
        self.idle_s, self.limit = idle_s, limit
        self._all: dict[str, Session] = {}

    def get(self, sid: str | None) -> Session:
        """The session named, or a new one when none is named; an unknown or expired one is a
        problem, so the client can say its variables and procedures are gone."""
        now = time.monotonic()
        for key in [k for k, s in self._all.items() if now - s.used > self.idle_s]:
            del self._all[key]
        if sid is None:
            while len(self._all) >= self.limit:
                del self._all[min(self._all, key=lambda k: self._all[k].used)]
            session = Session(new_ulid())
            self._all[session.id] = session
            return session
        found = self._all.get(sid)
        if found is None:
            raise NotFound(
                "This console session ended (idle or server restart); its variables and"
                " procedures are gone",
                actions=["new_session"],
            )
        found.used = now
        return found
