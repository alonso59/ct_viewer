"""Operator deployment configuration validation."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

BACKENDS = {"local", "server", "slurm"}


def absolute_path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} must be an absolute path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path.parent == path:
        raise ValueError(f"{name} must be a non-root absolute path without traversal")
    return path


def roots(raw: dict[str, Any], key: str) -> list[Path]:
    values = raw.get(key)
    if not isinstance(values, list) or not values:
        raise ValueError(f"{key} requires at least one root")
    return [absolute_path(value, key) for value in values]


def overlaps(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def managed_output(writable: Path, source: Path, datasets: list[Path]) -> bool:
    return source in datasets and writable.is_relative_to(source / "derived")


def validate_config(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "deployment",
        "backend",
        "environment",
        "workspace",
        "derived_roots",
        "managed_datasets",
        "source_roots",
        "model_roots",
        "limits",
        "slurm",
        "gpu_pool",
        "state_dir",
        "profiles_dir",
    }
    if raw.keys() - allowed:
        raise ValueError("unknown deployment configuration keys")
    if type(raw.get("deployment")) is not int or raw["deployment"] != 1:
        raise ValueError("unsupported deployment version")
    if raw.get("backend") not in BACKENDS:
        raise ValueError("unsupported backend")
    absolute_path(raw.get("environment"), "environment")
    workspace = absolute_path(raw.get("workspace"), "workspace")
    derived, sources, models = roots(raw, "derived_roots"), roots(raw, "source_roots"), roots(raw, "model_roots")
    managed = raw.get("managed_datasets", [])
    if not isinstance(managed, list) or len(managed) != len(set(map(str, managed))):
        raise ValueError("managed_datasets must be a unique array")
    datasets = [absolute_path(value, "managed_datasets") for value in managed]
    if any(path not in sources or path / "derived" not in derived for path in datasets):
        raise ValueError("managed datasets require an exact source and derived root")
    readonly = [*sources, *models]
    if "profiles_dir" in raw:
        readonly.append(absolute_path(raw["profiles_dir"], "profiles_dir"))
    if (
        any(overlaps(workspace, root) for root in readonly)
        or any(overlaps(path, root) for path in derived for root in models)
        or any(
            overlaps(path, root) and not managed_output(path, root, datasets) for path in derived for root in sources
        )
    ):
        raise ValueError("writable and source/model roots overlap")
    state = absolute_path(
        raw.get("state_dir", str(Path.home() / ".local/state/radiology-workbench/gpu-pool")), "state_dir"
    )
    if any(overlaps(state.resolve(), root.resolve()) for root in readonly):
        raise ValueError("state root overlaps source/model roots")
    limits = raw.get("limits")
    bounds = {"cpus": 12, "memory_mb": 1048576, "tasks": 1024, "seconds": 604800, "gpus": 4}
    if not isinstance(limits, dict) or limits.keys() != bounds.keys():
        raise ValueError("limits must declare cpus, memory_mb, tasks, seconds and gpus")
    for name, maximum in bounds.items():
        if type(limits[name]) is not int or not 1 <= limits[name] <= maximum:
            raise ValueError(f"invalid {name} limit (maximum {maximum})")
    pool = raw.get("gpu_pool", [])
    if (
        not isinstance(pool, list)
        or len(pool) != len(set(map(str, pool)))
        or any(not isinstance(value, str) or not re.fullmatch(r"(?:[0-6]|GPU-[A-Za-z0-9-]+)", value) for value in pool)
    ):
        raise ValueError("gpu_pool must contain unique approved indices 0..6 or GPU UUIDs")
    scheduler = raw.get("slurm", {})
    if not isinstance(scheduler, dict) or scheduler.keys() - {
        "partition",
        "account",
        "qos",
        "constraint",
        "max_parallel",
    }:
        raise ValueError("unknown slurm configuration")
    for name, value in scheduler.items():
        if name == "max_parallel":
            if type(value) is not int or not 1 <= value <= 64:
                raise ValueError("invalid max_parallel")
        elif not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value):
            raise ValueError(f"invalid slurm {name}")
    return deepcopy(raw)
