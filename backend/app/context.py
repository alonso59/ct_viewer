"""Service container built in the lifespan and exposed to routers via `api.v1.deps`."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings
from app.core.cache_budget import PROJECT_POOLS, CacheBudget, Pool, workspace_pools
from app.core.locks import FileLock, ProjectLocks
from app.core.paths import PathGuard
from app.events.bus import EventBus
from app.ingest.service import IndexHook
from app.ingest.store import IndexStore
from app.jobs.manager import JobManager
from app.plugins.registry import PluginRegistry, build_plugins
from app.projects.service import Workspace
from app.sources.open import OpenSessions
from app.tasks.registry import Registry, build_registry
from app.tasks.service import TaskService
from app.tasks.source_operations import SourceOperations
from app.tasks.workspace_runs import WorkspaceTasks


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
    source_operations: SourceOperations
    # CACHE_MAX_GB: one LRU budget over Open scratch and every project `cache/`
    cache_budget: CacheBudget
    open_sessions: OpenSessions = field(default_factory=OpenSessions)
    # Called with project_id after a successful index rebuild (e.g. thumbnails).
    after_index: list[IndexHook] = field(default_factory=list)


def build_context(settings: Settings, *, inline_jobs: bool = False) -> AppContext:
    guard = PathGuard(settings.readable_roots)
    derived_guard = PathGuard(settings.derived_roots, name="ALLOWED_DERIVED_ROOTS", strict=True)
    locks = ProjectLocks()
    bus = EventBus()
    workspace = Workspace(settings, guard, locks, derived_guard)
    plugins = build_plugins(settings.builtin_plugins_root)
    jobs = JobManager(bus, settings.job_workers, inline=inline_jobs)
    index = IndexStore(
        workspace.project_dir,
        settings.project_cache_max,
        default_seg=lambda pid: workspace.get(pid).default_seg,
        phase_vocabulary=lambda pid: workspace.get(pid).phase_vocabulary,
    )
    registry = build_registry(
        settings.builtin_plugins_root, settings.plugins_root, plugins.task_owner()
    )
    tasks = TaskService(settings, registry, workspace, index, jobs, bus, locks)
    return AppContext(
        settings=settings,
        guard=guard,
        locks=locks,
        bus=bus,
        jobs=jobs,
        workspace=workspace,
        index=index,
        server_lock=FileLock(settings.workspace_root / ".server.lock"),
        registry=registry,
        plugins=plugins,
        source_operations=SourceOperations(
            settings,
            guard,
            jobs,
            workspace,
            locks,
            tasks,
            WorkspaceTasks(
                settings, registry, guard, jobs, plugins.task_owner(), tasks.phase_runs, locks
            ),
        ),
        cache_budget=CacheBudget(
            lambda: [
                *workspace_pools(settings.workspace_root, workspace.projects_dir),
                *(
                    Pool(workspace.folder(p.project_id) / "cache" / name, "file")
                    for p in workspace.list()
                    if p.dataset_root
                    for name in PROJECT_POOLS
                ),
            ],
            settings.cache_max_gb,
        ),
    )
