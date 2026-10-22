"""SEG-02: the API consumes trusted runner snapshots without importing its GPU environment."""

from __future__ import annotations

from pathlib import Path

from app.tasks.models import TaskInfo
from app.tasks.registry import runners


def task_info(info: TaskInfo, queue: Path) -> TaskInfo:
    if info.manifest.runtime.type != "external":
        return info
    hosts = [r for r in runners(queue) if r.fresh and (not r.tasks or info.manifest.id in r.tasks)]
    result = info.model_copy(deep=True, update={"runner_online": bool(hosts)})
    if info.manifest.id != "segment.nnunet" or info.manifest.resources.gpu != "required":
        return result
    catalogs = [host.model_catalog for host in hosts if host.model_catalog is not None]
    generations = {catalog.generation for catalog in catalogs}
    if len(generations) > 1:
        result.available = False
        result.unavailable_reason = (
            "Conflicting runner model catalogs; reconcile the runner installations"
        )
    elif catalogs:
        result.model_catalog = catalogs[0]
        result.execution = hosts[0].execution
    profiles = (
        [p for p in result.model_catalog.profiles if p.available] if result.model_catalog else []
    )
    field = result.manifest.settings_schema["properties"]["profile"]
    field["enum"] = [p.id for p in profiles]
    field["x-enumNames"] = [p.title for p in profiles]
    if field.get("default") not in field["enum"]:
        field.pop("default", None)
        if profiles:
            field["default"] = profiles[0].id
    return result
