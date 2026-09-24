"""Layer providers (ADR-0020 §3): each returns the active layers of one plugin for a project.

A layer is one column keyed by item (or case) with provenance. Providers register in
`PROVIDERS`; the labeling plugin adds its columns the same way (LBL-06).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any, Literal

from app.core.fsio import iter_jsonl, read_json
from app.curation import state as curation_state

Level = Literal["item", "case", "scan"]


@dataclass
class Layer:
    id: str  # `{plugin or task}:{field}`, e.g. `analyzer.phase:phase`, `curation:status`
    plugin: str
    field: str
    level: Level
    source: str  # human-readable provenance, e.g. `run 01J… (analyzer.phase 1.0.0)`
    values: dict[str, Any] = dc_field(default_factory=dict)  # item_id / case_id → value

    @property
    def column(self) -> str:
        """Dataset-table header: the field and the layer that produced it (ADR-0020 §4)."""
        return f"{self.field}@{self.id}"

    def describe(self) -> dict[str, Any]:
        return {"column": self.column, "id": self.id, "plugin": self.plugin, "field": self.field,
                "level": self.level, "source": self.source}  # fmt: skip


@dataclass(frozen=True)
class LayerContext:
    project_dir: Path
    annotation_sources: dict[str, str | None]
    task_owner: dict[str, str]  # task id → plugin id


Provider = Callable[[LayerContext], list[Layer]]


def annotation_layers(ctx: LayerContext) -> list[Layer]:
    """Active analyzer runs per field (ANZ-04): phase, target_match, output_role, readiness…"""
    out: list[Layer] = []
    for fld, run_id in sorted(ctx.annotation_sources.items()):
        if not run_id:
            continue
        run_dir = ctx.project_dir / "tasks" / "runs" / run_id
        try:
            task = read_json(run_dir / "run.json").get("task") or {}
        except (OSError, ValueError):
            task = {}
        task_id, version = str(task.get("id") or "task"), str(task.get("version") or "")
        values = {
            str(r["item_id"]): r.get("value")
            for r in iter_jsonl(run_dir / "annotations.jsonl")
            if r.get("field") == fld and r.get("item_id")
        }
        out.append(
            Layer(
                id=f"{task_id}:{run_id}",
                plugin=ctx.task_owner.get(task_id, task_id.split(".")[0]),
                field=fld,
                level="item",
                source=f"run {run_id} ({task_id} {version})".strip(),
                values=values,
            )
        )
    return out


def curation_layers(ctx: LayerContext) -> list[Layer]:
    """Curation & QC state (ADR-0022): the latest item status and its reviewer."""
    items = curation_state.item_states(ctx.project_dir)
    if not items:
        return []
    return [
        Layer("curation", "curation", "curation_status", "item", "curation events (CUR-08)",
              {i: s.status for i, s in items.items()}),
        Layer("curation", "curation", "curation_reviewer", "item", "curation events (CUR-08)",
              {i: s.reviewer for i, s in items.items()}),
    ]  # fmt: skip


PROVIDERS: list[Provider] = [annotation_layers, curation_layers]


def active_layers(ctx: LayerContext) -> list[Layer]:
    return [layer for provider in PROVIDERS for layer in provider(ctx)]
