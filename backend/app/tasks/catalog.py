"""The API consumes trusted runner snapshots without importing its GPU environment."""

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
    if not info.manifest.resources.model_catalog or info.manifest.resources.gpu != "required":
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
    free = max(0, total - used) / 1024
    label = f"GPU {device['index']} · {name} · {free:.1f}/{total / 1024:.0f} GiB free"
    return label + (f" · {device['reason']}" if device.get("reason") else "")


def _profile_label(profile: dict[str, Any]) -> str:
    hours = profile["seconds"] / 3600
    memory = profile["memory_mb"] / 1024
    return (
        f"{profile['name']} · {profile['gpus']} GPU · {profile['cpus']} CPU · "
        f"{memory:g} GiB · {hours:g} h"
    )


def _gpu_fields(info: TaskInfo) -> None:
    """List every host GPU with its state; the runner admits only usable ones.

    A scheduler-managed runner assigns GPUs itself, so the picker is removed.
    """
    execution = info.execution or {}
    schema = info.manifest.settings_schema
    choice = schema.get("properties", {}).get("compute_profile")
    if execution.get("backend") == "slurm":
        schema.get("properties", {}).pop("gpu_ids", None)
        if "gpu_ids" in schema.get("required", []):
            schema["required"] = [name for name in schema["required"] if name != "gpu_ids"]
        if isinstance(choice, dict):
            reported = (execution.get("scheduler") or {}).get("profiles") or []
            valid = [p for p in reported if isinstance(p, dict) and p.get("status") == "valid"]
            choice["enum"] = [p["id"] for p in valid]
            choice["x-enumNames"] = [_profile_label(p) for p in valid]
            schema["required"] = [*schema.get("required", []), "compute_profile"]
            if valid:
                choice["default"] = valid[0]["id"]
            else:
                info.available = False
                info.unavailable_reason = "No compute profile is valid yet; check Settings, Compute"
        return
    schema.get("properties", {}).pop("compute_profile", None)
    inventory = execution.get("inventory") or {}
    devices = [
        d
        for d in inventory.get("devices") or []
        if isinstance(d, dict) and isinstance(d.get("index"), str)
    ]
    ids = schema.get("properties", {}).get("gpu_ids")
    if isinstance(ids, dict) and isinstance(ids.get("items"), dict) and devices:
        ids["items"]["enum"] = [d["index"] for d in devices]
        ids["items"]["x-enumNames"] = [_gpu_label(d) for d in devices]
        ids["items"]["x-enumStatus"] = [
            d.get("status", "unavailable" if d.get("busy") else "ready") for d in devices
        ]
