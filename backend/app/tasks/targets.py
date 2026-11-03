"""Deterministic targets: a typed item id, case id or path becomes a TaskSelection.

Exact matches only; identity is never inferred from file names. A target that cannot be resolved
safely is a problem with next actions, never a guess. Paths stay out of problem texts (NFR-17).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.core.errors import NotFound, ValidationProblem
from app.ingest.models import Item
from app.projects.models import ProjectConfig
from app.tasks.models import TaskManifest, TaskSelection
from app.tasks.registry import RADIOMICS_TASK
from app.tasks.service import TaskService

ALL = "all"
TargetKind = Literal["items", "case", "all", "path", "source"]
DEFAULT_SEG = "default"


@dataclass
class Target:
    """What a command acts on; `selection` is what the task service receives."""

    kind: TargetKind
    selection: TaskSelection
    item_ids: list[str] = field(default_factory=list)


@dataclass
class TargetOptions:
    seg: str | None = None
    labels: list[str] = field(default_factory=list)
    scope: str | None = None
    phase: list[str] = field(default_factory=list)


def resolve(
    tasks: TaskService,
    pid: str | None,
    m: TaskManifest,
    raw: str | None,
    opts: TargetOptions,
) -> Target:
    if m.input == "source":
        if raw is None:
            raise ValidationProblem("Name the folder or file to convert", actions=["choose_source"])
        selection = TaskSelection(source=raw)
        return Target("source", selection.model_copy(update={"source": tasks._source(selection)}))
    if pid is None:
        raise ValidationProblem(
            f"{m.id} needs a project; open or create one first",
            actions=["choose_project", "create_project"],
        )
    cfg = tasks.workspace.get(pid)
    items = [i for i in tasks.store.load(pid).items if i.status == "active"]
    kind, chosen = _items(tasks, pid, items, raw)
    if opts.scope:
        chosen = [i for i in chosen if i.scope == opts.scope]
    if opts.phase:
        chosen = [i for i in chosen if i.phase.canonical in opts.phase]
    if not chosen:
        raise ValidationProblem("The target selects no active item")
    selection = TaskSelection(item_ids=[i.item_id for i in chosen])
    if kind == "all" and not (opts.scope or opts.phase):
        selection = TaskSelection()  # all active items, as the GUI sends it
    if m.requires.seg is not None:
        selection.seg_id = _seg(cfg, chosen, opts.seg)
    elif opts.seg:
        raise ValidationProblem(f"{m.id} reads no masks; drop -seg")
    if m.id == RADIOMICS_TASK:
        selection.labels = _labels(cfg, opts.labels)
    return Target(kind, selection, [i.item_id for i in chosen])


def _items(
    tasks: TaskService, pid: str, items: list[Item], raw: str | None
) -> tuple[TargetKind, list[Item]]:
    if raw is None or raw == ALL:
        return "all", items
    by_id = {i.item_id: i for i in items}
    if raw in by_id:
        return "items", [by_id[raw]]
    case = [i for i in items if i.case_id == raw]
    if case:
        return "case", case
    if "/" not in raw:
        raise NotFound(f"No active case or item {raw!r} in this project")
    if not Path(raw).is_absolute():
        raise ValidationProblem("Write the path in full, starting with /")
    path = tasks.workspace.guard.check(Path(raw))
    resolver = tasks.workspace.resolver(pid)
    under = [i for i in items if i.image and _within(resolver.resolve(i.image.ref), path)]
    if not under:
        raise ValidationProblem(
            "This path is not an imported source of the current project",
            actions=["create_project", "import_source"],
        )
    return "path", under


def _within(image: Path, path: Path) -> bool:
    return image == path or path in image.parents


def _seg(cfg: ProjectConfig, items: list[Item], chosen: str | None) -> str:
    if chosen == DEFAULT_SEG:
        chosen = cfg.default_seg
    if chosen is not None:
        if cfg.segmentation(chosen) is None:
            raise NotFound(f"Unknown segmentation set {chosen!r}")
        return chosen
    covering = [
        s.seg_id for s in cfg.segmentations if s.active and all(s.seg_id in i.masks for i in items)
    ]
    if len(covering) == 1:
        return covering[0]
    if not covering:
        raise ValidationProblem(
            "No segmentation set covers every selected item; segment them or narrow the target",
            actions=["run_segmentation"],
        )
    raise ValidationProblem(
        "Several segmentation sets match; choose one with -seg",
        errors=[{"loc": ["option", "seg"], "msg": f"one of: {', '.join(covering)}, default"}],
    )


def _labels(cfg: ProjectConfig, wanted: list[str]) -> list[int]:
    by_name = {e.name: e.value for e in cfg.label_map}
    known = ", ".join(f"{e.name} ({e.value})" for e in cfg.label_map) or "none"
    if not wanted:
        raise ValidationProblem(
            "Choose the labels to extract with -labels",
            errors=[{"loc": ["option", "labels"], "msg": f"labels: {known}"}],
        )
    out: list[int] = []
    for w in wanted:
        value = int(w) if w.isdigit() else by_name.get(w)
        if value is None or value not in by_name.values():
            raise ValidationProblem(
                f"Unknown label {w!r}",
                errors=[{"loc": ["option", "labels"], "msg": f"labels: {known}"}],
            )
        out.append(value)
    return sorted(set(out))
