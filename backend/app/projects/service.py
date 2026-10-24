"""Workspace + project service (PRJ-01..06, 10, 11; BE-05, BE-07).

`workspace.json` is the registry; `project.json` is each project's config. Writes run under
the project lock (outer) and the `__workspace__` lock (inner) when the registry changes.
"""

from __future__ import annotations

import asyncio
import builtins
import hashlib
import json
import re
import secrets
import shutil
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any, Final

from pydantic import ValidationError

from app.config import Settings
from app.core.errors import (
    DerivedRootRequired,
    FormatVersionUnsupported,
    JobConflict,
    NotFound,
    PreconditionFailed,
    PreconditionRequired,
    RootsOverlap,
    ValidationProblem,
)
from app.core.fsio import (
    atomic_write_bytes,
    atomic_write_json,
    iter_jsonl,
    read_json,
    write_jsonl_atomic,
)
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.locks import FileLock, LockHeldError, ProjectLocks
from app.core.paths import PathGuard, PathResolver, is_within, realpath
from app.curation.state import case_reviews
from app.ingest.counting import split_cases
from app.projects.bundle import extract_bundle, write_bundle
from app.projects.migrations import check_version, migrate
from app.projects.models import (
    FORMAT_VERSION,
    LabelEntry,
    Modality,
    PathRoot,
    ProjectConfig,
    ProjectDetail,
    ProjectPatch,
    ProjectSummary,
    RootInfo,
    SegmentationSet,
    WorkspaceEntry,
)
from app.projects.presets import get_pack, pack_fields

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
    "tasks/runs",
    "derived",
    "exports",
    "cache",
)


class Workspace:
    def __init__(
        self,
        settings: Settings,
        guard: PathGuard,
        locks: ProjectLocks,
        derived_guard: PathGuard | None = None,
    ) -> None:
        self.settings = settings
        self.guard = guard
        # ALLOWED_DERIVED_ROOTS (OPS-11); empty allows no derived root at all.
        self.derived_guard = derived_guard or PathGuard(
            settings.derived_roots, name="ALLOWED_DERIVED_ROOTS", strict=True
        )
        self.locks = locks
        self.root = Path(settings.workspace_root)
        self.projects_dir = self.root / "projects"
        self.archive_dir = self.projects_dir / ".archive"
        self.registry_path = self.root / "workspace.json"
        # Bundle export/import scratch space; same filesystem as projects/ (atomic rename).
        self.staging_dir = self.root / ".staging"
        self._local_locks: dict[str, FileLock] = {}
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
            "projects": [
                e.model_dump(
                    mode="json", exclude={"dataset_root"} if e.dataset_root is None else set()
                )
                for e in self._entries().values()
            ],
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
        if entry.dataset_root:
            root = self.guard.check(Path(entry.dataset_root))
            part = ".archive" if entry.archived else "projects"
            folder = root / ".workbench" / part / entry.project_id
            if realpath(folder) != folder:
                raise ValidationProblem("Dataset project folders cannot contain symlinks")
            return folder
        return (self.archive_dir if entry.archived else self.projects_dir) / entry.project_id

    def folder(self, project_id: str) -> Path:
        """PRJ-19: the registered project folder, including archived projects."""
        return self._folder(self.entry(project_id))

    def project_derived_guard(self, project_id: str) -> PathGuard:
        cfg = self.get(project_id)
        roots = list(self.derived_guard.allowed_roots)
        if cfg.dataset_root:
            root = self.guard.check(Path(cfg.dataset_root))
            derived = root / "derived"
            if realpath(derived) != derived:
                raise ValidationProblem("Dataset derived folder cannot be a symlink")
            roots.append(derived)
        return PathGuard(
            roots,
            name="ALLOWED_DERIVED_ROOTS or the project managed derived root",
            strict=True,
        )

    def _lock_local(self, pid: str, folder: Path) -> None:
        if pid not in self._local_locks:
            lock = FileLock(folder / ".lock")
            try:
                lock.acquire()
            except LockHeldError:
                raise JobConflict(
                    "This dataset project is open in another running workspace"
                ) from None
            self._local_locks[pid] = lock

    def close(self) -> None:
        for lock in self._local_locks.values():
            lock.release()
        self._local_locks.clear()

    def project_dir(self, project_id: str) -> Path:
        """Active project folder; NotFound if unknown or archived."""
        entry = self.entry(project_id)
        if entry.archived:
            raise NotFound(f"Project {project_id!r} is archived")
        folder = self._folder(entry)
        if entry.dataset_root and folder.is_dir():
            self._lock_local(project_id, folder)
        return folder

    def summary(self, project_id: str) -> ProjectSummary:
        entry = self.entry(project_id)
        folder = self._folder(entry)
        case_ids, excluded = _case_ids(folder / "index" / "cases.jsonl")
        # CUR-08: a case counts once every active item has a decision (partial cases don't)
        reviewed = sum(
            1
            for cid, r in case_reviews(
                folder, _active_items(folder / "index" / "items.jsonl")
            ).items()
            if cid in case_ids and r.state == "reviewed"
        )
        return ProjectSummary(
            **entry.model_dump(),
            n_cases=len(case_ids),
            n_cases_excluded=len(excluded),
            curation_progress=reviewed / len(case_ids) if case_ids else 0.0,
            share_url=self.share_url(project_id),
        )

    def list(self, *, archived: bool = False) -> list[ProjectSummary]:
        rows = [self.summary(e.project_id) for e in tuple(self._entries().values())]
        rows = [r for r in rows if r.archived == archived]
        rows.sort(key=lambda r: r.last_opened_at or r.created_at, reverse=True)
        return rows

    def reserved_derived(self) -> tuple[Path, ...]:
        """Derived subtrees only their owner writes (NFR-11): the write-once `_datasets/`
        (TSK-13) and every project's task tree `{derived root}/{project_id}/` (PROJECT_FORMAT
        §Write rules), archived projects included."""
        roots = [realpath(d) for d in self.settings.dataset_roots]
        for pid, entry in tuple(self._entries().items()):
            # an archived project is not `get`-able, but its task tree stays reserved
            cfg = self.get(pid) if not entry.archived else self._load(self._folder(entry))
            root = cfg.derived_root()
            if root is not None:
                roots.append(realpath(Path(root.path) / pid))
        return tuple(roots)

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

    def view_url(self, token: str) -> str:
        return f"{self.settings.base_url}/v/{token}"

    def detail(self, project_id: str) -> ProjectDetail:
        cfg = self.get(project_id)
        return ProjectDetail(
            **cfg.model_dump(),
            share_url=self.share_url(project_id),
            etag=etag_of(cfg),
            view_url=self.view_url(cfg.view_token) if cfg.view_token else None,
        )

    def check_etag(self, project_id: str, if_match: str | None) -> None:
        """PRJ-15: settings writes need `If-Match` with the current ETag."""
        if not if_match:
            raise PreconditionRequired(
                "Settings writes need If-Match with the project ETag (PRJ-15)",
                actions=["reload"],
            )
        current = etag_of(self.get(project_id))
        if if_match.strip() not in (current, f"W/{current}", "*"):
            raise PreconditionFailed(
                "The project settings were changed by someone else: reload and reapply",
                actions=["reload"],
            )

    def by_view_token(self, token: str) -> str:
        """PRJ-17: the active project whose `view_token` is `token`; NotFound otherwise."""
        if token and VIEW_TOKEN_RE.fullmatch(token):
            for e in tuple(self._entries().values()):
                if e.archived:
                    continue
                t = self.get(e.project_id).view_token
                if t is not None and secrets.compare_digest(t, token):
                    return e.project_id
        raise NotFound("Unknown or revoked view-only link")

    def roots(self, project_id: str) -> builtins.list[RootInfo]:
        return [_root_info(r) for r in self.get(project_id).path_roots]

    def resolver(self, project_id: str) -> PathResolver:
        cfg = self.get(project_id)
        return PathResolver(
            {r.alias: r.path for r in cfg.path_roots},
            self.guard,
            roles={r.alias: r.role for r in cfg.path_roots},
            derived_guard=self.project_derived_guard(project_id),
            source_exclusions=[
                Path(cfg.dataset_root) / ".workbench",
                Path(cfg.dataset_root) / "derived",
                Path(cfg.dataset_root) / "recycle_bin",
            ]
            if cfg.dataset_root
            else (),
        )

    def derived_root(self, project_id: str) -> PathRoot:
        """PRJ-13: the registered derived root, or `derived-root-required` with the next step."""
        root = self.get(project_id).derived_root()
        if root is None:
            raise DerivedRootRequired(
                "This task writes volumes: choose a derived folder for the project first "
                "(inside ALLOWED_DERIVED_ROOTS)",
                actions=["choose_derived_root"],
            )
        return root

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

    async def create(
        self,
        name: str,
        description: str = "",
        default_modality: Modality = "CT",
        packs: builtins.list[str] | None = None,
        dataset_root: str | None = None,
    ) -> ProjectConfig:
        """PRJ-14: neutral; `packs` (scripts, tests) are applied as by API-28."""
        now = utc_now()
        try:
            cfg = ProjectConfig(
                project_id=new_ulid(),
                name=name,
                description=description,
                created_at=now,
                updated_at=now,
                default_modality=default_modality,
            )
            for pack_id in packs or []:
                if get_pack(pack_id) is None:
                    raise ValidationProblem(
                        f"Unknown study pack {pack_id!r}",
                        errors=[{"loc": ["body", "packs"], "msg": f"unknown pack {pack_id!r}"}],
                    )
                cfg = with_pack(cfg, pack_id)
        except ValidationError as exc:
            raise ValidationProblem("Invalid project", errors=_errors(exc)) from None
        if dataset_root:
            root = self._dataset_root(dataset_root, create=True)
            cfg = cfg.model_copy(
                update={
                    "dataset_root": str(root),
                    "path_roots": [
                        PathRoot(alias="DATA", path=str(root), role="source"),
                        PathRoot(alias="DERIVED", path=str(root / "derived"), role="derived"),
                    ],
                }
            )
            (root / "derived").mkdir(exist_ok=True)
            ignore = root / ".gitignore"
            if ignore.is_symlink():
                raise ValidationProblem("Dataset .gitignore cannot be a symlink")
            previous = ignore.read_bytes() if ignore.exists() else b""
            entries = [b"/.workbench/", b"/derived/", b"/recycle_bin/"]
            missing = [line for line in entries if line not in previous.splitlines()]
            if missing:
                atomic_write_bytes(
                    ignore,
                    previous
                    + (b"\n" if previous and not previous.endswith(b"\n") else b"")
                    + b"\n".join(missing)
                    + b"\n",
                )
        entry = WorkspaceEntry(
            project_id=cfg.project_id, name=cfg.name, created_at=now, dataset_root=cfg.dataset_root
        )
        folder = self._folder(entry)
        async with self.locks(cfg.project_id):
            for sub in SUBDIRS:
                (folder / sub).mkdir(parents=True, exist_ok=True)
            self._write_config(folder, cfg)
            if entry.dataset_root:
                self._lock_local(cfg.project_id, folder)
            await self._set_entry(entry)
            self._remember(cfg)
        return cfg

    def _dataset_root(self, raw: str, *, create: bool = False) -> Path:
        path = Path(raw)
        if not path.is_absolute():
            raise ValidationProblem("Dataset folder must be an absolute path")
        root = self.guard.check(path)
        if root != path or any(
            p in {".workbench", "derived", "recycle_bin", ".git"} for p in path.parts
        ):
            raise ValidationProblem("Choose a dataset folder outside managed or symlinked folders")
        if create and not root.exists():
            if not root.parent.is_dir():
                raise ValidationProblem("The parent folder must exist before creating a dataset")
            root.mkdir()
        if not root.is_dir():
            raise ValidationProblem("Dataset folder does not exist")
        for name in (".workbench", "derived", "recycle_bin"):
            if realpath(root / name) != root / name:
                raise ValidationProblem("Managed dataset folders cannot be symlinks")
        return root

    async def open_dataset(self, raw: str) -> builtins.list[ProjectDetail]:
        """PRJ-19: register existing local projects; opening a moved folder rebases its roots."""
        root = self._dataset_root(raw)
        found = []
        for folder in sorted((root / ".workbench/projects").glob("*")):
            if not folder.is_dir() or not is_ulid(folder.name):
                continue
            if folder.is_symlink():
                raise ValidationProblem("Project folders cannot be symlinks")
            self._lock_local(folder.name, folder)
            cfg = self._load(folder)
            if cfg.project_id != folder.name or not cfg.dataset_root:
                raise ValidationProblem("Invalid dataset project identity")
            existing = self._entries().get(cfg.project_id)
            if existing and existing.dataset_root != str(root) and self._folder(existing).exists():
                raise ValidationProblem("A different folder already owns this project ID")
            async with self.locks(cfg.project_id):
                old = realpath(Path(cfg.dataset_root))
                roots = [
                    r.model_copy(update={"path": str(root / realpath(r.path).relative_to(old))})
                    if is_within(realpath(r.path), old)
                    else r
                    for r in cfg.path_roots
                ]
                cfg = cfg.model_copy(update={"dataset_root": str(root), "path_roots": roots})
                if old != root:
                    records = list(iter_jsonl(folder / "sources/imports.jsonl"))
                    for rec in records:
                        path = realpath(rec["root"])
                        if is_within(path, old):
                            rec["root"] = str(root / path.relative_to(old))
                    write_jsonl_atomic(folder / "sources/imports.jsonl", records)
                self._write_config(folder, cfg)
                await self._set_entry(
                    WorkspaceEntry(
                        project_id=cfg.project_id,
                        name=cfg.name,
                        created_at=cfg.created_at,
                        last_opened_at=utc_now(),
                        dataset_root=str(root),
                    )
                )
                self._remember(cfg)
            found.append(self.detail(cfg.project_id))
        if not found:
            raise NotFound("This folder has no saved projects; use New project to create one")
        return found

    async def update(self, project_id: str, patch: ProjectPatch) -> ProjectConfig:
        async with self.locks(project_id):
            cur = self.get(project_id)
            changes = {
                k: v for k, v in patch.model_dump(exclude_unset=True).items() if v is not None
            }
            merged = cur.model_dump() | changes
            check_phase_config(merged)
            try:
                new = ProjectConfig.model_validate(merged)
            except ValidationError as exc:
                raise ValidationProblem("Invalid project update", errors=_errors(exc)) from None
            if new == cur:
                return cur
            new = new.model_copy(update={"updated_at": utc_now()})
            self._save(new)
            if new.name != cur.name:
                entry = self.entry(project_id)
                await self._set_entry(entry.model_copy(update={"name": new.name}))
            return new

    async def apply_pack(self, project_id: str, pack_id: str) -> ProjectConfig:
        """PRJ-16: merge a pack's labels and phase rules; records it in `packs[]`."""
        async with self.locks(project_id):
            cur = self.get(project_id)
            new = with_pack(cur, pack_id).model_copy(update={"updated_at": utc_now()})
            return self._save(new)

    async def set_view_token(self, project_id: str, create: bool) -> ProjectConfig:
        """PRJ-17: create/rotate (a new random token revokes the old one) or revoke."""
        async with self.locks(project_id):
            cur = self.get(project_id)
            token = secrets.token_urlsafe(24) if create else None
            return self._save(cur.model_copy(update={"view_token": token, "updated_at": utc_now()}))

    async def set_root(self, project_id: str, root: PathRoot) -> ProjectConfig:
        """Add or relink an alias (PRJ-05, PRJ-13).

        `source` roots must pass ALLOWED_DATA_ROOTS (OPS-04); the single `derived` root must be
        inside ALLOWED_DERIVED_ROOTS (OPS-11) and must not overlap any source root (ADR-0014).
        """
        path = Path(root.path)
        if not path.is_absolute():
            raise ValidationProblem(
                "Root path must be absolute", errors=[{"loc": ["path"], "msg": "not absolute"}]
            )
        if root.role == "derived":
            derived_guard = self.project_derived_guard(project_id)
            if not derived_guard.allowed_roots:
                raise DerivedRootRequired(
                    "ALLOWED_DERIVED_ROOTS is empty: the server has no writable derived folder "
                    "(OPS-11)",
                    actions=["configure:ALLOWED_DERIVED_ROOTS"],
                )
            derived_guard.check(path)
        else:
            self.guard.check(path)
            cfg = self.get(project_id)
            if cfg.dataset_root and any(
                is_within(realpath(path), realpath(Path(cfg.dataset_root) / name))
                for name in ("derived", ".workbench", "recycle_bin")
            ):
                raise ValidationProblem("Managed dataset artifacts cannot be registered as sources")
        if not path.is_dir():
            raise ValidationProblem(
                "Root path must be an existing directory",
                errors=[{"loc": ["path"], "msg": "not an existing directory"}],
            )
        async with self.locks(project_id):
            cur = self.get(project_id)
            others = [r for r in cur.path_roots if r.alias != root.alias]
            if root.role == "derived" and any(r.role == "derived" for r in others):
                raise ValidationProblem(
                    "The project already has a derived root (PRJ-13); relink that alias instead",
                    errors=[{"loc": ["alias"], "msg": "one derived root per project"}],
                )
            real = realpath(path)
            datasets = [realpath(d) for d in self.settings.dataset_roots]
            for r in others:
                if r.role == root.role:
                    continue
                o = realpath(Path(r.path))
                if any(is_within(p, d) for p in (real, o) for d in datasets):
                    continue  # a write-once dataset: project tasks never write under `_datasets/`
                managed = realpath(Path(cur.dataset_root) / "derived") if cur.dataset_root else None
                if managed is not None and (
                    (root.role == "derived" and real == managed and is_within(managed, o))
                    or (r.role == "derived" and o == managed and is_within(managed, real))
                ):
                    continue
                if is_within(real, o) or is_within(o, real):
                    raise RootsOverlap(
                        f"{root.alias} ({root.role}) overlaps {r.alias} ({r.role}): source and "
                        "derived folders must be separate (ADR-0014)"
                    )
            roots = sorted([*others, root], key=lambda r: r.alias)
            new = cur.model_copy(update={"path_roots": roots, "updated_at": utc_now()})
            return self._save(new)

    async def edit_label_map(
        self,
        project_id: str,
        edit: Callable[[builtins.list[LabelEntry]], builtins.list[LabelEntry]],
    ) -> ProjectConfig:
        """Read-modify-write of the label map under the project lock (AUD-A5-12)."""
        async with self.locks(project_id):
            cur = self.get(project_id)
            label_map = edit(list(cur.label_map))
            if label_map == cur.label_map:
                return cur
            new = cur.model_copy(update={"label_map": label_map, "updated_at": utc_now()})
            return self._save(new)

    async def put_segmentation(self, project_id: str, seg: SegmentationSet) -> ProjectConfig:
        """Add or replace one segmentation set (ADR-0015; task outputs, API-27 PATCH)."""
        async with self.locks(project_id):
            cur = self.get(project_id)
            sets = [s for s in cur.segmentations if s.seg_id != seg.seg_id]
            pos = next(
                (i for i, s in enumerate(cur.segmentations) if s.seg_id == seg.seg_id), len(sets)
            )
            sets.insert(pos, seg)
            new = cur.model_copy(update={"segmentations": sets, "updated_at": utc_now()})
            return self._save(new)

    async def set_annotation_source(
        self, project_id: str, field: str, run_id: str | None, *, only_if_unset: bool = False
    ) -> ProjectConfig:
        """ANZ-04: activate (or clear) the annotation run for one field."""
        async with self.locks(project_id):
            cur = self.get(project_id)
            if only_if_unset and cur.annotation_sources.get(field) is not None:
                return cur
            sources = {**cur.annotation_sources, field: run_id}
            new = cur.model_copy(update={"annotation_sources": sources, "updated_at": utc_now()})
            return self._save(new)

    async def archive(self, project_id: str) -> None:
        """PRJ-06: purge `cache/`, move to `projects/.archive/`. Never deletes project data."""
        async with self.locks(project_id):
            folder = self.project_dir(project_id)
            entry = self.entry(project_id)
            dest = self._folder(entry.model_copy(update={"archived": True}))
            if dest.exists():
                raise ValidationProblem(f"Archive folder already exists for {project_id}")
            _purge(folder / "cache")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(folder, dest)
            self.invalidate(project_id)
            await self._set_entry(entry.model_copy(update={"archived": True}))

    async def unarchive(self, project_id: str) -> ProjectConfig:
        async with self.locks(project_id):
            entry = self.entry(project_id)
            if not entry.archived:
                raise NotFound(f"Project {project_id!r} is not archived")
            dest = self._folder(entry.model_copy(update={"archived": False}))
            if dest.exists():
                raise ValidationProblem(f"Active folder already exists for {project_id}")
            shutil.move(self._folder(entry), dest)
            await self._set_entry(entry.model_copy(update={"archived": False}))
            return self.get(project_id)

    # -- bundles (PRJ-08/09) ------------------------------------------------------------------

    async def export_bundle(self, project_id: str) -> tuple[Path, str]:
        """Write the bundle zip to a staging file; returns (path, download filename).

        The caller deletes the file once sent. Runs under the project lock so appends and
        atomic writes cannot interleave with the snapshot.
        """
        folder = self.project_dir(project_id)
        name = self.get(project_id).name
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        out = self.staging_dir / f"{new_ulid()}.zip"
        async with self.locks(project_id):
            try:
                folders = [str(self.settings.workspace_root), *map(str, self.guard.allowed_roots)]
                folders += map(str, self.derived_guard.allowed_roots)
                await asyncio.to_thread(write_bundle, folder, project_id, out, folders)
            except BaseException:
                out.unlink(missing_ok=True)
                raise
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "project"
        return out, f"{slug}-{project_id}.zip"

    async def import_bundle(self, fileobj: IO[bytes]) -> tuple[ProjectConfig, str]:
        """Extract a bundle as a new project; returns (config, the bundle's project_id).

        The bundle's id is kept unless this workspace already has it (then a new ULID).
        `cache/` is recreated empty; the index and curation history come from the bundle.
        """
        taken = set(self._entries())
        for d in (self.projects_dir, self.archive_dir):
            if d.is_dir():
                taken |= {p.name for p in d.iterdir()}
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        staging = self.staging_dir / new_ulid()
        try:
            cfg, original, _ = await asyncio.to_thread(extract_bundle, fileobj, staging, taken)
            if cfg.dataset_root is not None:
                cfg = cfg.model_copy(update={"dataset_root": None})
                self._write_config(staging, cfg)
            async with self.locks(cfg.project_id):
                dest = self.projects_dir / cfg.project_id
                if dest.exists() or cfg.project_id in self._entries():
                    raise ValidationProblem(f"Project {cfg.project_id} already exists")
                for sub in SUBDIRS:
                    (staging / sub).mkdir(parents=True, exist_ok=True)
                staging.rename(dest)
                entry = WorkspaceEntry(
                    project_id=cfg.project_id, name=cfg.name, created_at=cfg.created_at
                )
                await self._set_entry(entry)
            self.invalidate(cfg.project_id)
            return self.get(cfg.project_id), original  # PRJ-11 migration runs here
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    async def touch_opened(self, project_id: str) -> None:
        async with self.locks(project_id):
            entry = self.entry(project_id)
            if entry.archived:
                raise NotFound(f"Project {project_id!r} is archived")
            await self._set_entry(entry.model_copy(update={"last_opened_at": utc_now()}))


def check_phase_config(cfg: dict[str, Any]) -> None:
    """Priority and mapping targets must use the vocabulary (an empty vocabulary is open)."""
    vocab = cfg["phase_vocabulary"]
    if not vocab:
        return
    for key in ("phase_priority", "phase_mapping"):
        values = cfg[key].values() if key == "phase_mapping" else cfg[key]
        if any(p not in vocab for p in values):
            raise ValidationProblem(
                f"{key} must only use phase_vocabulary values",
                errors=[{"loc": [key], "msg": f"allowed: {vocab}"}],
            )


_active_cache: OrderedDict[Path, tuple[tuple[int, int], dict[str, list[str]]]] = OrderedDict()


def _active_items(path: Path) -> dict[str, list[str]]:
    """Active item ids per case from `index/items.jsonl` (CUR-08 progress), cached by stat."""
    try:
        st = path.stat()
    except FileNotFoundError:
        return {}
    sig = (st.st_mtime_ns, st.st_size)
    hit = _active_cache.get(path)
    if hit is not None and hit[0] == sig:
        _active_cache.move_to_end(path)
        return hit[1]
    out: dict[str, list[str]] = {}
    for r in iter_jsonl(path):
        if r.get("status") == "active":
            out.setdefault(str(r.get("case_id")), []).append(str(r.get("item_id")))
    _active_cache[path] = (sig, out)
    while len(_active_cache) > 16:
        _active_cache.popitem(last=False)
    return out


def _case_ids(path: Path) -> tuple[set[str], set[str]]:
    """Counted case ids in `index/cases.jsonl` (PRJ-02 count and curation-progress
    denominator) and the all-excluded ones (`n_items` 0, AUD-A2-08)."""
    return split_cases((str(r.get("case_id")), r.get("n_items") == 0) for r in iter_jsonl(path))


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
    return RootInfo(
        alias=root.alias, path=root.path, exists=Path(root.path).is_dir(), role=root.role
    )


def _errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]


VIEW_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")


def etag_of(cfg: ProjectConfig) -> str:
    """PRJ-15: a strong ETag over the whole `project.json` content."""
    raw = json.dumps(cfg.model_dump(mode="json"), sort_keys=True).encode()
    return '"' + hashlib.sha256(raw).hexdigest()[:20] + '"'


def with_pack(cfg: ProjectConfig, pack_id: str) -> ProjectConfig:
    """PRJ-16: pack labels replace entries with the same value, others are kept; the phase
    vocabulary, priority and mapping become the pack's (mapping merged); nothing is deleted."""
    pack = get_pack(pack_id)
    if pack is None:
        raise NotFound(f"Study pack {pack_id!r} not found")
    fields = pack_fields(pack)
    labels = {e.value: e for e in cfg.label_map}
    for raw in fields["label_map"]:
        labels[raw["value"]] = LabelEntry.model_validate(raw)
    label_map = sorted(labels.values(), key=lambda e: e.value)
    imported = [
        s.model_copy(
            update={"label_mapping": {**{str(e.value): e.value for e in label_map},
                                      **s.label_mapping}}
        )
        if s.kind == "imported"
        else s
        for s in cfg.segmentations
    ]  # fmt: skip
    update: dict[str, Any] = {
        "label_map": label_map,
        "segmentations": imported,
        "packs": [*[p for p in cfg.packs if p != pack_id], pack_id],
    }
    if pack.phase_vocabulary:
        update |= {
            "phase_vocabulary": fields["phase_vocabulary"],
            "phase_mapping": {**cfg.phase_mapping, **fields["phase_mapping"]},
            "phase_priority": fields["phase_priority"],
        }
    return ProjectConfig.model_validate(cfg.model_copy(update=update).model_dump())
