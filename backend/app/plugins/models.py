"""`plugin.json` manifest and Library payloads (PLUGINS.md, PLG-02/05/06; API-49)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PLUGIN_ID_RE = r"^[a-z][a-z0-9_-]{0,63}$"
Capability = Literal["derived_root", "runner", "segmentation", "event_store", "features_run"]
PluginStatus = Literal[
    "ready", "needs_runner", "needs_derived_root", "needs_segmentation", "pending"
]


class Contributes(BaseModel):
    """Contribution points (PLUGINS.md §Contribution points). Values are ids."""

    model_config = ConfigDict(extra="forbid")

    tasks: list[str] = Field(default_factory=list)
    views: list[str] = Field(default_factory=list)
    editors: list[str] = Field(default_factory=list)
    overlays: list[str] = Field(default_factory=list)
    panels: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    packs: list[str] = Field(default_factory=list)


class PluginRequires(BaseModel):
    model_config = ConfigDict(extra="forbid")

    core: str = ">=3.0"
    plugins: list[str] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)


class PluginManifest(BaseModel):
    """`plugins/<id>/plugin.json` (PLG-02). Unknown keys are refused like task manifests."""

    model_config = ConfigDict(extra="forbid")

    plugin: Literal[1] = 1
    id: str = Field(pattern=PLUGIN_ID_RE)
    version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    icon: str = "extensions"  # a codicon name
    scope: Literal["workspace", "project"] = "project"
    contributes: Contributes = Field(default_factory=lambda: Contributes())
    requires: PluginRequires = Field(default_factory=lambda: PluginRequires())
    # Listed with its requirements but cannot be opened (PLG-09).
    pending: bool = False
    # CI plugins (segment.threshold): loaded for their tasks, never shown in the Library.
    hidden: bool = False


class PluginInfo(BaseModel):
    """API-49 row: the manifest plus the computed status (PLG-05/06)."""

    manifest: PluginManifest
    status: PluginStatus
    # Why the plugin is not ready and how to satisfy it (UI-18); null when ready.
    reason: str | None = None
    actions: list[str] = Field(default_factory=list)


class InvalidPlugin(BaseModel):
    path: str
    error: str


class PluginList(BaseModel):
    plugins: list[PluginInfo]
    invalid: list[InvalidPlugin]
