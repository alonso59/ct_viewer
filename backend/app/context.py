"""Service container built in the lifespan and exposed to routers via `api.v1.deps`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.config import Settings
from app.core.locks import FileLock, ProjectLocks
from app.core.paths import PathGuard
from app.events.bus import EventBus
from app.ingest.store import IndexStore
from app.jobs.manager import JobManager
from app.projects.service import Workspace

IndexHook = Callable[[str], Awaitable[None]]


@dataclass
class AppContext:
    settings: Settings
    guard: PathGuard
    locks: ProjectLocks
    bus: EventBus
    jobs: JobManager
    workspace: Workspace
    index: IndexStore
    server_lock: FileLock
    # Called with project_id after a successful index rebuild (e.g. thumbnails, IMP-12).
    after_index: list[IndexHook] = field(default_factory=list)


def build_context(settings: Settings, *, inline_jobs: bool = False) -> AppContext:
    guard = PathGuard(settings.allowed_roots)
    locks = ProjectLocks()
    bus = EventBus()
    workspace = Workspace(settings, guard, locks)
    return AppContext(
        settings=settings,
        guard=guard,
        locks=locks,
        bus=bus,
        jobs=JobManager(bus, settings.job_workers, inline=inline_jobs),
        workspace=workspace,
        index=IndexStore(workspace.project_dir, settings.project_cache_max),
        server_lock=FileLock(settings.workspace_root / ".server.lock"),
    )
