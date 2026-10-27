"""R1, PRJ-19, OPS-18: only explicit managed output paths may lie below a source root."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from plugins.runner.supervised import Supervisor


def setup(tmp_path: Path) -> tuple[Supervisor, Path, Path, dict[str, Any]]:
    dataset, models, workspace = [tmp_path / name for name in ("dataset", "models", "workspace")]
    (dataset / ".workbench/projects").mkdir(parents=True)
    (dataset / "nifti").mkdir()
    models.mkdir()
    job = workspace / "queue/J1"
    job.mkdir(parents=True)
    image = dataset / "nifti/one.nii.gz"
    image.write_bytes(b"original synthetic source")
    config = {
        "deployment": 1,
        "backend": "server",
        "environment": str(Path(sys.executable).parent.parent),
        "workspace": str(workspace),
        "source_roots": [str(dataset)],
        "model_roots": [str(models)],
        "derived_roots": [str(dataset / "derived")],
        "managed_datasets": [str(dataset)],
        "state_dir": str(tmp_path / "host-state"),
        "gpu_pool": ["0"],
        "limits": {"cpus": 3, "memory_mb": 128, "tasks": 32, "seconds": 30, "gpus": 1},
    }
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    spec = {
        "items": [{"image": {"path": str(image)}}],
        "output_dir": str(dataset / "derived/P1/R1"),
    }
    return Supervisor(path), job, dataset, spec


def prepare(supervisor: Supervisor, job: Path, spec: dict[str, Any]) -> dict[str, Any]:
    return supervisor.prepare(job, {"runtime": {"command": ["{python}"]}}, job.parent, spec, [])


def test_managed_output_is_permitted_without_writable_input_access(tmp_path: Path) -> None:
    supervisor, job, dataset, spec = setup(tmp_path)
    record = prepare(supervisor, job, spec)
    assert str(dataset) not in record["write_roots"]
    assert record["write_roots"][:2] == [str(job), spec["output_dir"]]
    assert (dataset / "nifti/one.nii.gz").read_bytes() == b"original synthetic source"


def test_managed_output_symlink_cannot_redirect_to_inputs(tmp_path: Path) -> None:
    supervisor, job, dataset, spec = setup(tmp_path)
    (dataset / "derived").symlink_to(dataset / "nifti", target_is_directory=True)
    with pytest.raises(ValueError, match=r"managed|overlap|canonical"):
        prepare(supervisor, job, spec)
    assert not (dataset / "nifti/P1").exists()


def test_generated_data_cannot_be_smuggled_as_source_input(tmp_path: Path) -> None:
    supervisor, job, dataset, spec = setup(tmp_path)
    derived = dataset / "derived"
    derived.mkdir()
    (derived / "generated.nii.gz").write_bytes(b"generated")
    spec["items"] = [{"image": {"path": str(derived / "generated.nii.gz")}}]
    with pytest.raises(ValueError, match=r"input|managed|source"):
        prepare(supervisor, job, spec)
