"""Workspace + project service (PRJ-01..06, 10, 11; BE-05, BE-07).

`workspace.json` is the registry; `project.json` is each project's config. Writes run under
the project lock (outer) and the `__workspace__` lock (inner) when the registry changes.
"""

from __future__ import annotations

import builtins
import shutil
from collections import OrderedDict
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from app.config import Settings
from app.core.errors import FormatVersionUnsupported, NotFound, ValidationProblem
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.core.paths import PathGuard, PathResolver
from app.projects.migrations import check_version, migrate
from app.projects.models import (
    FORMAT_VERSION,
    PathRoot,
    ProjectConfig,
    ProjectDetail,
    ProjectPatch,
    ProjectSummary,
    RootInfo,
    WorkspaceEntry,
)

WORKSPACE_FORMAT: Final = "radiology-workbench-workspace"
WORKSPACE_FORMAT_VERSION: Final = 1
WORKSPACE_LOCK: Final = "__workspace__"
PROJECT_FILE: Final = "project.json"
SUBDIRS: Final = (
    "sources",
    "index",
    "curation",
    "radiomics/profiles",
    "radiomics/runs",
    "exports",
    "cache",
)


class Workspace:
    def __init__(self, settings: Settings, guard: PathGuard, locks: ProjectLocks) -> None:
        self.settings = settings
        self.guard = guard
        self.locks = locks
        self.root = Path(settings.workspace_root)
        self.projects_dir = self.root / "projects"
        self.archive_dir = self.projects_dir / ".archive"
        self.registry_path = self.root / "workspace.json"
        self._registry: dict[str, WorkspaceEntry] | None = None
        self._cache: OrderedDict[str, ProjectConfig] = OrderedDict()

    # -- registry ---------------------------------------------------------------------------

    def open(self) -> None:
        """Create `projects/`, `projects/.archive/`, `workspace.json` if missing."""
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._registry = {}
            self._write_registry()
        self._registry = None
        self._entries()

    def _entries(self) -> dict[str, WorkspaceEntry]:
        if self._registry is None:
            if not self.registry_path.exists():
                self._registry = {}
                return self._registry
            raw = read_json(self.registry_path)
            if not isinstance(raw, dict) or raw.get("format") != WORKSPACE_FORMAT:
                raise FormatVersionUnsupported(f"Not a {WORKSPACE_FORMAT} document")
            if raw.get("format_version") != WORKSPACE_FORMAT_VERSION:
                raise FormatVersionUnsupported("Unsupported workspace.json format_version")
            entries = [WorkspaceEntry.model_validate(e) for e in raw.get("projects", [])]
            self._registry = {e.project_id: e for e in entries}
        return self._registry

    def _write_registry(self) -> None:
        doc = {
            "format": WORKSPACE_FORMAT,
            "format_version": WORKSPACE_FORMAT_VERSION,
            "projects": [e.model_dump(mode="json") for e in self._entries().values()],
        }
        atomic_write_json(self.registry_path, doc)

    async def _set_entry(self, entry: WorkspaceEntry) -> None:
        async with self.locks(WORKSPACE_LOCK):
            self._entries()[entry.project_id] = entry
            self._write_registry()

    def entry(self, project_id: str) -> WorkspaceEntry:
        entry = self._entries().get(project_id) if is_ulid(project_id) else None
        if entry is None:
            raise NotFound(f"Project {project_id!r} not found")
        return entry

    # -- reads ------------------------------------------------------------------------------

    def share_url(self, project_id: str) -> str:
        return f"{self.settings.base_url}/p/{project_id}"

    def _folder(self, entry: WorkspaceEntry) -> Path:
        return (self.archive_dir if entry.archived else self.projects_dir) / entry.project_id

    def project_dir(self, project_id: str) -> Path:
        """Active project folder; NotFound if unknown or archived."""
        entry = self.entry(project_id)
        if entry.archived:
            raise NotFound(f"Project {project_id!r} is archived")
        return self._folder(entry)

    def summary(self, project_id: str) -> ProjectSummary:
        entry = self.entry(project_id)
        return ProjectSummary(
            **entry.model_dump(),
            n_cases=_count_lines(self._folder(entry) / "index" / "cases.jsonl"),
            share_url=self.share_url(project_id),
        )

    def list(self, *, archived: bool = False) -> list[ProjectSummary]:
        rows = [self.summary(e.project_id) for e in self._entries().values()]
        rows = [r for r in rows if r.archived == archived]
        rows.sort(key=lambda r: r.last_opened_at or r.created_at, reverse=True)
        return rows

    def get(self, project_id: str) -> ProjectConfig:
        """Cached (LRU, BE-07); runs PRJ-11 migrations on first open."""
        hit = self._cache.get(project_id)
        if hit is not None:
            self._cache.move_to_end(project_id)
            return hit
        cfg = self._load(self.project_dir(project_id))
        if cfg.project_id != project_id:
            raise ValidationProblem("project.json project_id does not match its folder")
        self._remember(cfg)
        return cfg

    def detail(self, project_id: str) -> ProjectDetail:
        cfg = self.get(project_id)
        return ProjectDetail(**cfg.model_dump(), share_url=self.share_url(project_id))

    def roots(self, project_id: str) -> builtins.list[RootInfo]:
        return [_root_info(r) for r in self.get(project_id).path_roots]

    def resolver(self, project_id: str) -> PathResolver:
        cfg = self.get(project_id)
        return PathResolver({r.alias: r.path for r in cfg.path_roots}, self.guard)

    def invalidate(self, project_id: str) -> None:
        self._cache.pop(project_id, None)

    def _remember(self, cfg: ProjectConfig) -> None:
        self._cache[cfg.project_id] = cfg
        self._cache.move_to_end(cfg.project_id)
        while len(self._cache) > self.settings.project_cache_max:
            self._cache.popitem(last=False)

    def _load(self, folder: Path) -> ProjectConfig:
        path = folder / PROJECT_FILE
        if not path.exists():
            raise NotFound("project.json is missing")
        raw: Any = read_json(path)
        version = check_version(raw)
        if version < FORMAT_VERSION:
            shutil.copy2(path, path.with_name(f"{PROJECT_FILE}.v{version}.bak"))
            raw = migrate(raw, version)
        try:
            cfg = ProjectConfig.model_validate(raw)
        except ValidationError as exc:
            raise ValidationProblem("project.json is invalid", errors=_errors(exc)) from None
        if version < FORMAT_VERSION:
            self._write_config(folder, cfg)
        return cfg

    # -- writes -----------------------------------------------------------------------------

    def _write_config(self, folder: Path, cfg: ProjectConfig) -> None:
        atomic_write_json(folder / PROJECT_FILE, cfg.model_dump(mode="json"), backup=True)

    def _save(self, cfg: ProjectConfig) -> ProjectConfig:
        self._write_config(self.project_dir(cfg.project_id), cfg)
        self.invalidate(cfg.project_id)
        self._remember(cfg)
        return cfg

    async def create(self, name: str, description: str = "") -> ProjectConfig:
        now = utc_now()
        try:
            cfg = ProjectConfig(
                project_id=new_ulid(),
                name=name,
                description=description,
                created_at=now,
                updated_at=now,
            )
        except ValidationError as exc:
            raise ValidationProblem("Invalid project", errors=_errors(exc)) from None
        folder = self.projects_dir / cfg.project_id
        async with self.locks(cfg.project_id):
            for sub in SUBDIRS:
                (folder / sub).mkdir(parents=True, exist_ok=True)
            self._write_config(folder, cfg)
            entry = WorkspaceEntry(project_id=cfg.project_id, name=cfg.name, created_at=now)
            await self._set_entry(entry)
            self._remember(cfg)
        return cfg

    async def update(self, project_id: str, patch: ProjectPatch) -> ProjectConfig:
        async with self.locks(project_id):
            cur = self.get(project_id)
            changes = {
                k: v for k, v in patch.model_dump(exclude_unset=True).items() if v is not None
            }
            merged = cur.model_dump() | changes
            vocab = merged["phase_vocabulary"]
            if any(p not in vocab for p in merged["phase_priority"]):
                raise ValidationProblem(
                    "phase_priority must only use phase_vocabulary values",
                    errors=[{"loc": ["phase_priority"], "msg": f"allowed: {vocab}"}],
                )
            new = ProjectConfig.model_validate(merged)
            if new == cur:
                return cur
            new = new.model_copy(update={"updated_at": utc_now()})
            self._save(new)
            if new.name != cur.name:
                entry = self.entry(project_id)
                await self._set_entry(entry.model_copy(update={"name": new.name}))
            return new

    async def set_root(self, project_id: str, root: PathRoot) -> ProjectConfig:
        """Add or relink an alias (PRJ-05). Path must pass the guard (OPS-04)."""
        path = Path(root.path)
        if not path.is_absolute():
            raise ValidationProblem(
                "Root path must be absolute", errors=[{"loc": ["path"], "msg": "not absolute"}]
            )
        self.guard.check(path)
        if not path.is_dir():
            raise ValidationProblem(
                "Root path must be an existing directory",
                errors=[{"loc": ["path"], "msg": "not an existing directory"}],
            )
        async with self.locks(project_id):
            cur = self.get(project_id)
            roots = [r for r in cur.path_roots if r.alias != root.alias] + [root]
            roots.sort(key=lambda r: r.alias)
            new = cur.model_copy(update={"path_roots": roots, "updated_at": utc_now()})
            return self._save(new)

    async def archive(self, project_id: str) -> None:
        """PRJ-06: purge `cache/`, move to `projects/.archive/`. Never deletes project data."""
        async with self.locks(project_id):
            folder = self.project_dir(project_id)
            entry = self.entry(project_id)
            dest = self.archive_dir / project_id
            if dest.exists():
                raise ValidationProblem(f"Archive folder already exists for {project_id}")
            _purge(folder / "cache")
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(folder, dest)
            self.invalidate(project_id)
            await self._set_entry(entry.model_copy(update={"archived": True}))

    async def unarchive(self, project_id: str) -> ProjectConfig:
        async with self.locks(project_id):
            entry = self.entry(project_id)
            if not entry.archived:
                raise NotFound(f"Project {project_id!r} is not archived")
            dest = self.projects_dir / project_id
            if dest.exists():
                raise ValidationProblem(f"Active folder already exists for {project_id}")
            shutil.move(self._folder(entry), dest)
            await self._set_entry(entry.model_copy(update={"archived": False}))
            return self.get(project_id)

    async def touch_opened(self, project_id: str) -> None:
        async with self.locks(project_id):
            entry = self.entry(project_id)
            if entry.archived:
                raise NotFound(f"Project {project_id!r} is archived")
            await self._set_entry(entry.model_copy(update={"last_opened_at": utc_now()}))


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as fh:
        return sum(1 for line in fh if line.strip())


def _purge(cache: Path) -> None:
    """Delete `cache/` contents (PRJ-10: always safe); keep the directory."""
    if not cache.is_dir():
        return
    for child in cache.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _root_info(root: PathRoot) -> RootInfo:
    return RootInfo(alias=root.alias, path=root.path, exists=Path(root.path).is_dir())


def _errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
