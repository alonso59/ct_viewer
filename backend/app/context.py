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
from app.plugins.registry import PluginRegistry, build_plugins
from app.projects.service import Workspace
from app.sources.open import OpenSessions
from app.tasks.registry import Registry, build_registry

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
    registry: Registry
    plugins: PluginRegistry
    open_sessions: OpenSessions = field(default_factory=OpenSessions)
    # Called with project_id after a successful index rebuild (e.g. thumbnails, IMP-12).
    after_index: list[IndexHook] = field(default_factory=list)


def build_context(settings: Settings, *, inline_jobs: bool = False) -> AppContext:
    guard = PathGuard(settings.allowed_roots)
    derived_guard = PathGuard(settings.derived_roots, name="ALLOWED_DERIVED_ROOTS", strict=True)
    locks = ProjectLocks()
    bus = EventBus()
    workspace = Workspace(settings, guard, locks, derived_guard)
    plugins = build_plugins(settings.builtin_plugins_root)
    return AppContext(
        settings=settings,
        guard=guard,
        locks=locks,
        bus=bus,
        jobs=JobManager(bus, settings.job_workers, inline=inline_jobs),
        workspace=workspace,
        index=IndexStore(
            workspace.project_dir,
            settings.project_cache_max,
            default_seg=lambda pid: workspace.get(pid).default_seg,
        ),
        server_lock=FileLock(settings.workspace_root / ".server.lock"),
        registry=build_registry(
            settings.builtin_plugins_root, settings.plugins_root, plugins.task_owner()
        ),
        plugins=plugins,
    )
