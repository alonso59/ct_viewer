"""API-49 Plugin Library (PLG-05/06): installed first-party plugins with their status."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.deps import Ctx
from app.context import AppContext
from app.plugins.models import PluginInfo, PluginList
from app.plugins.registry import StatusInputs, status_of
from app.tasks import registry as tasks_registry

router = APIRouter(tags=["plugins"])


def _inputs(ctx: AppContext, project: str | None) -> StatusInputs:
    queue = ctx.settings.workspace_root / "queue"

    def runner_missing(task_id: str) -> bool:
        info = ctx.registry.tasks.get(task_id)
        if info is not None and info.manifest.runtime.type != "external":
            return False
        return not tasks_registry.runner_online(queue, task_id)

    has_seg: bool | None = None
    if project is not None:
        ctx.workspace.get(project)  # 404 for an unknown project
        has_seg = any(i.masks for i in ctx.index.load(project).items)
    return StatusInputs(
        derived_roots=bool(ctx.settings.derived_roots),
        runner_missing=runner_missing,
        has_segmentation=has_seg,
    )


@router.get("/plugins", response_model=PluginList)
def list_plugins(ctx: Ctx, project: str | None = None) -> PluginList:
    inputs = _inputs(ctx, project)
    return PluginList(
        plugins=[status_of(m, inputs) for m in ctx.plugins.listed()],
        invalid=list(ctx.plugins.invalid),
    )


@router.get("/plugins/{plugin_id}", response_model=PluginInfo)
def get_plugin(ctx: Ctx, plugin_id: str, project: str | None = None) -> PluginInfo:
    return status_of(ctx.plugins.get(plugin_id), _inputs(ctx, project))
