"""Plugin registry (PLG-01..06): every `{builtin_plugins_root}/*/plugin.json`.

All shipped plugins are first-party, installed per workspace and enabled by default (PLG-04).
Status is computed on request from `requires` (PLG-06); an invalid manifest is listed with its
error and not loaded, like task manifests (TSK-01).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.core.errors import NotFound
from app.plugins.models import InvalidPlugin, PluginInfo, PluginManifest, PluginStatus


def parse_plugin(path: Path) -> PluginManifest:
    """Raise ValueError with a readable reason for any invalid `plugin.json`."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not JSON: {exc}") from None
    try:
        m = PluginManifest.model_validate(raw)
    except ValidationError as exc:
        e = exc.errors()[0]
        loc = ".".join(str(x) for x in e["loc"]) or "manifest"
        raise ValueError(f"{loc}: {e['msg']}") from None
    if m.id != path.parent.name:
        raise ValueError(f"id {m.id!r} must match its folder {path.parent.name!r}")
    return m


@dataclass
class PluginRegistry:
    plugins: dict[str, PluginManifest] = field(default_factory=dict)
    invalid: list[InvalidPlugin] = field(default_factory=list)

    def load(self, root: Path) -> None:
        for p in sorted(root.glob("*/plugin.json")) if root.is_dir() else []:
            try:
                m = parse_plugin(p)
                if m.id in self.plugins:
                    raise ValueError(f"duplicate plugin id {m.id!r}")
            except (OSError, ValueError) as exc:
                self.invalid.append(InvalidPlugin(path=str(p), error=str(exc)))
                continue
            self.plugins[m.id] = m
        known = set(self.plugins)
        for m in list(self.plugins.values()):
            missing = [d for d in m.requires.plugins if d not in known]
            if missing:
                del self.plugins[m.id]
                self.invalid.append(
                    InvalidPlugin(path=m.id, error=f"requires unknown plugins: {missing}")
                )

    def get(self, plugin_id: str) -> PluginManifest:
        m = self.plugins.get(plugin_id)
        if m is None:
            raise NotFound(f"Plugin {plugin_id!r} not found")
        return m

    def task_owner(self) -> dict[str, str]:
        """Task id → owning plugin id (TSK-01: every task belongs to a first-party plugin)."""
        return {t: m.id for m in self.plugins.values() for t in m.contributes.tasks}

    def listed(self) -> list[PluginManifest]:
        return [m for m in self.plugins.values() if not m.hidden]


@dataclass(frozen=True)
class StatusInputs:
    """What status depends on (PLG-06), gathered by the caller."""

    derived_roots: bool
    # task id -> True when it runs externally and no fresh runner lists it
    runner_missing: Callable[[str], bool]
    # None = no project in context (the Library outside a project)
    has_segmentation: bool | None = None


def status_of(m: PluginManifest, inputs: StatusInputs) -> PluginInfo:
    """First unmet requirement wins; each reason says how to satisfy it (UI-18)."""
    caps = set(m.requires.capabilities)
    status: PluginStatus = "ready"
    reason: str | None = None
    actions: list[str] = []
    if m.pending:
        status, reason = "pending", "Not available yet: planned for a later release."
    elif "derived_root" in caps and not inputs.derived_roots:
        status = "needs_derived_root"
        reason = "Writes volumes: set ALLOWED_DERIVED_ROOTS on the server (OPS-11)."
        actions = ["configure:ALLOWED_DERIVED_ROOTS"]
    elif "runner" in caps and any(inputs.runner_missing(t) for t in m.contributes.tasks):
        status = "needs_runner"
        reason = "Runs on the host: start scripts/rw-runner.py in the plugin's environment."
        actions = ["start_runner"]
    elif "segmentation" in caps and inputs.has_segmentation is False:
        status = "needs_segmentation"
        reason = "Needs a segmentation set: import masks or run a segmentation task."
        actions = ["open_tasks"]
    return PluginInfo(manifest=m, status=status, reason=reason, actions=actions)


def build_plugins(root: Path) -> PluginRegistry:
    reg = PluginRegistry()
    reg.load(root)
    return reg
