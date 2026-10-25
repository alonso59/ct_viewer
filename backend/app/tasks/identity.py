"""Create and check the API-owned identity of supervised nnU-Net runs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from app.core.errors import ValidationProblem
from app.tasks.models import TaskInfo, TaskRunOutput


def create_identity(
    info: TaskInfo, settings: dict[str, Any], items: list[dict[str, Any]]
) -> dict[str, Any]:
    if info.manifest.id != "segment.nnunet" or info.manifest.resources.gpu != "required":
        return {}
    from plugins.runner.identity import freeze

    profiles = info.model_catalog.profiles if info.model_catalog else []
    selected = next((p for p in profiles if p.id == settings.get("profile") and p.available), None)
    if selected is None:
        raise ValidationProblem("A fresh validated runner model catalog is required")
    try:
        return freeze(info.manifest_hash, selected.model_dump(), items)
    except (OSError, ValueError) as exc:
        raise ValidationProblem("Cannot pin segmentation run inputs or model identity") from exc


def committed_outputs(
    outputs: Sequence[TaskRunOutput], resolve: Callable[[str], Path]
) -> dict[str, str]:
    files: dict[str, str] = {}
    for output in outputs:
        if output.kind != "mask":
            continue
        if not output.ref or not output.sha256:
            raise ValueError("committed output has no verified identity")
        files[str(resolve(output.ref))] = (
            output.sha256 if output.sha256.startswith("sha256:") else "sha256:" + output.sha256
        )
    return files


def verify_resume(
    pin: dict[str, Any],
    info: TaskInfo,
    settings: dict[str, Any],
    items: list[dict[str, Any]],
    outputs: dict[str, str],
) -> None:
    from plugins.runner.identity import verify_files, verify_inputs, verify_profile

    current = create_identity(info, settings, items)
    if not pin or current.get("manifest_hash") != pin.get("manifest_hash"):
        raise ValueError("pinned task manifest changed or identity missing; start a new run")
    verify_profile(pin, current["profile"])
    verify_inputs(pin, items)
    verify_files(outputs)
