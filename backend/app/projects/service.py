"""Workspace + project service (PRJ-01..06, 10, 11). SKELETON: lane sub-agent A."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.core.locks import ProjectLocks
from app.core.paths import PathGuard, PathResolver
from app.projects.models import PathRoot, ProjectConfig, ProjectPatch, ProjectSummary


class Workspace:
    def __init__(self, settings: Settings, guard: PathGuard, locks: ProjectLocks) -> None:
        self.settings = settings
        self.guard = guard
        self.locks = locks
        self.root = Path(settings.workspace_root)
        self.projects_dir = self.root / "projects"

    def open(self) -> None:
        """Create `projects/`, `projects/.archive/`, `workspace.json` if missing."""
        raise NotImplementedError

    def list(self, *, archived: bool = False) -> list[ProjectSummary]:
        raise NotImplementedError

    def project_dir(self, project_id: str) -> Path:
        """Active project folder; NotFound if unknown or archived."""
        raise NotImplementedError

    def get(self, project_id: str) -> ProjectConfig:
        """Cached (LRU, BE-07); runs PRJ-11 migrations on first open."""
        raise NotImplementedError

    def resolver(self, project_id: str) -> PathResolver:
        raise NotImplementedError

    async def create(self, name: str, description: str = "") -> ProjectConfig:
        raise NotImplementedError

    async def update(self, project_id: str, patch: ProjectPatch) -> ProjectConfig:
        raise NotImplementedError

    async def set_root(self, project_id: str, root: PathRoot) -> ProjectConfig:
        """Add or relink an alias (PRJ-05). Path must pass the guard (OPS-04)."""
        raise NotImplementedError

    async def archive(self, project_id: str) -> None:
        raise NotImplementedError

    async def unarchive(self, project_id: str) -> ProjectConfig:
        raise NotImplementedError

    async def touch_opened(self, project_id: str) -> None:
        raise NotImplementedError
