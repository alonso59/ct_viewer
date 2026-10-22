"""SEG-02: the API consumes trusted runner snapshots without importing its GPU environment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
    _gpu_fields(result)
    return result


def _gpu_label(device: dict[str, Any]) -> str:
    used, total = device.get("used_mb") or 0, device.get("total_mb") or 0
    name = device.get("name") or "GPU"
    label = f"GPU {device['index']} · {name} · {used / 1024:.1f}/{total / 1024:.0f} GB"
    return label + (" · busy" if device.get("busy") else "")


def _gpu_fields(info: TaskInfo) -> None:
    """G1: offer and accept only the runner's approved devices; the cap fits limit and pool."""
    execution = info.execution or {}
    inventory = execution.get("inventory") or {}
    devices = [
        d
        for d in inventory.get("devices") or []
        if isinstance(d, dict) and isinstance(d.get("index"), str)
    ]
    props = info.manifest.settings_schema.get("properties", {})
    bounds = [len(devices) or None, (execution.get("limits") or {}).get("gpus")]
    cap = props.get("gpu_cap")
    if isinstance(cap, dict):
        bound = min(b for b in [cap.get("maximum"), *bounds] if isinstance(b, int) and b > 0)
        cap["maximum"] = bound
        if isinstance(cap.get("default"), int) and cap["default"] > bound:
            cap["default"] = bound
    ids = props.get("gpu_ids")
    if isinstance(ids, dict) and isinstance(ids.get("items"), dict) and devices:
        ids["items"]["enum"] = [d["index"] for d in devices]
        ids["items"]["x-enumNames"] = [_gpu_label(d) for d in devices]
        if isinstance(cap, dict):
            ids["maxItems"] = min(ids.get("maxItems", cap["maximum"]), cap["maximum"])
