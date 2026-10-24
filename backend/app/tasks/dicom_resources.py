"""BE-16: operator budgets are explicit; read-only planning remains usable without pixels."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import Settings
from app.core.errors import ValidationProblem


def require_pixel_budget(settings: Settings) -> None:
    if settings.dicom_memory_mb is None:
        raise ValidationProblem(
            "DICOM conversion requires an explicit DICOM_MEMORY_MB budget; "
            "discovery and Estimate remain available",
            actions=["configure:DICOM_MEMORY_MB"],
        )
    if settings.container_mode and settings.host_allocation_root is None:
        raise ValidationProblem(
            "Container pixel conversion requires a shared HOST_ALLOCATION_ROOT "
            "visible to the participating runner",
            actions=["configure:HOST_ALLOCATION_ROOT"],
        )


def initialize(settings: Settings) -> None:
    from plugins.runner.gpu import RESOURCE_POLICY, Pool

    from app.core.fsio import atomic_write_json

    atomic_write_json(
        settings.workspace_root / RESOURCE_POLICY,
        {"policy": 1, "pool": Pool(settings.allocation_root).identity(), "cpu_cap": 12},
    )


def apply_worker(job: Path) -> None:
    """Linux limits apply to the owned child only, before native imports or pixel reads."""
    import os
    import resource

    from app.core.fsio import atomic_write_json, read_json

    path = job / "resources.json"
    limits: dict[str, Any] = (
        read_json(path) if path.exists() else {"cpu_threads": 1, "header_mb": 8, "memory_mb": None}
    )
    cpus = int(limits["cpu_threads"])
    affinity = sorted(os.sched_getaffinity(0))[:cpus]
    os.sched_setaffinity(0, affinity)
    spec = read_json(job / "job.json")
    pixels = spec.get("operation") == "open" or (
        spec.get("operation", "task") == "task" and spec.get("mode") != "estimate"
    )
    memory = limits.get("memory_mb")
    bound = None
    if pixels:
        if memory is None:
            raise ValueError("DICOM_MEMORY_MB is required before pixel conversion")
        bound = int(memory) * 1024**2
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if soft != resource.RLIM_INFINITY:
            bound = min(bound, soft)
        resource.setrlimit(resource.RLIMIT_AS, (bound, hard))
    atomic_write_json(
        job / "worker-resources.json",
        {
            "affinity": affinity,
            "native_threads": 1,
            "pixel_memory_mb": memory if pixels else None,
            "address_space_limit_mb": bound // 1024**2 if bound is not None else None,
        },
    )
    from plugins.dicom import scan

    scan.READ_THREADS = min(cpus, 4)
    scan.MAX_HEADER_BYTES = int(limits.get("header_mb", 8)) * 1024**2
