"""OPS-18/20, SEG-07: three deployments share bounded, operator-owned configuration."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from plugins.runner.deployment import validate_config


def config(backend: str = "server") -> dict[str, Any]:
    return {
        "deployment": 1,
        "backend": backend,
        "environment": "/opt/operator/conda/envs/nnunet",
        "workspace": "/lustre/operator/workbench",
        "derived_roots": ["/lustre/operator/derived"],
        "source_roots": ["/lustre/operator/source"],
        "model_roots": ["/lustre/operator/models"],
        "limits": {"cpus": 4, "memory_mb": 8192, "tasks": 64, "seconds": 3600, "gpus": 1},
        "slurm": {"partition": "gpu", "account": "research", "max_parallel": 2},
    }


@pytest.mark.parametrize("backend", ["local", "server", "slurm"])
def test_supported_backends_accept_one_gpu_without_touching_host_paths(backend: str) -> None:
    raw = config(backend)
    original = deepcopy(raw)
    assert validate_config(raw) == original
    assert raw == original


def test_explicit_managed_dataset_supports_its_prj19_derived_folder() -> None:
    raw = config()
    raw["managed_datasets"] = ["/lustre/operator/source"]
    raw["derived_roots"] = ["/lustre/operator/source/derived"]
    assert validate_config(raw) == raw


@pytest.mark.parametrize("path", ["/lustre/operator/source/outputs", "/lustre/operator/source"])
def test_managed_dataset_exception_cannot_approve_other_source_writes(path: str) -> None:
    raw = config()
    raw["managed_datasets"] = ["/lustre/operator/source"]
    raw["derived_roots"] = [path]
    with pytest.raises(ValueError, match=r"overlap|managed"):
        validate_config(raw)


@pytest.mark.parametrize("backend", ["docker-daemon", "ssh-shell", "", "SLURM"])
def test_unknown_backend_is_refused(backend: str) -> None:
    with pytest.raises(ValueError, match="backend"):
        validate_config(config(backend))


@pytest.mark.parametrize(
    "field,value",
    [
        ("gpus", 0),
        ("gpus", 5),
        ("cpus", 0),
        ("memory_mb", -1),
        ("tasks", True),
        ("seconds", "unlimited"),
    ],
)
def test_unbounded_or_ambiguous_resource_requests_are_refused(field: str, value: Any) -> None:
    raw = config()
    raw["limits"][field] = value
    with pytest.raises(ValueError, match=field):
        validate_config(raw)


@pytest.mark.parametrize(
    "root", ["/lustre/operator/source", "/lustre/operator", "/lustre/operator/source/outputs", "/"]
)
def test_output_cannot_overlap_sources_or_models(root: str) -> None:
    raw = config()
    raw["derived_roots"] = [root]
    with pytest.raises(ValueError, match=r"overlap|root"):
        validate_config(raw)


@pytest.mark.parametrize("path", ["relative/env", "/opt/env/../other", "/opt/env\nmalicious"])
def test_environment_must_be_an_unambiguous_absolute_path(path: str) -> None:
    raw = config()
    raw["environment"] = path
    with pytest.raises(ValueError, match="environment"):
        validate_config(raw)


def test_scheduler_settings_cannot_contain_extra_flags_or_shell_text() -> None:
    raw = config("slurm")
    raw["slurm"]["partition"] = "gpu\n#SBATCH --exclusive"
    with pytest.raises(ValueError, match="partition"):
        validate_config(raw)


def test_browser_commands_and_unrecognized_configuration_are_refused() -> None:
    raw = config()
    raw["command"] = ["sh", "-c", "anything"]
    with pytest.raises(ValueError, match="unknown"):
        validate_config(raw)


def test_default_pool_state_cannot_be_written_inside_a_source_root() -> None:
    raw = config()
    raw["source_roots"] = [str(Path.home())]
    with pytest.raises(ValueError, match=r"state.*overlap"):
        validate_config(raw)
