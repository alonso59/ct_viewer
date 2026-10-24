"""D27 / BE-16: explicit budgets, bounded native allocation and coordinated host admission."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from tools.dicom_fixtures import write_series


@pytest.mark.parametrize(
    "field,value",
    [
        ("dicom_memory_mb", 0),
        ("dicom_memory_mb", 127),
        ("dicom_cpu_threads", 0),
        ("dicom_cpu_threads", 13),
        ("dicom_header_mb", 0),
        ("dicom_header_mb", 65),
        ("dicom_inventory_mb", 0),
        ("dicom_batch_size", 0),
        ("dicom_cleanup_seconds", 31),
        ("dicom_retention_days", 0),
    ],
)
def test_invalid_dicom_budget_is_rejected_at_startup(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value}, _env_file=None)  # type: ignore[call-arg]


def test_dicom_and_shared_worker_reservations_fit_the_declared_cpu_cap() -> None:
    with pytest.raises(ValidationError, match="12"):
        Settings(job_workers=10, dicom_cpu_threads=4, _env_file=None)  # type: ignore[call-arg]
    assert Settings(job_workers=8, dicom_cpu_threads=4, _env_file=None).dicom_cpu_threads == 4  # type: ignore[call-arg]


@pytest.mark.parametrize("in_project", [False, True])
def test_missing_memory_budget_refuses_conversion_before_allocating_outputs(
    tmp_path: Path, in_project: bool
) -> None:
    source, output = tmp_path / "source", tmp_path / "derived"
    write_series(source / "P0" / "series")
    output.mkdir()
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        allowed_derived_roots=str(output),
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        prefix = "/api/v1"
        if in_project:
            pid = client.post(prefix + "/projects", json={"name": "Budget", "packs": []}).json()[
                "project_id"
            ]
            assert (
                client.put(
                    prefix + f"/projects/{pid}/roots/DERIVED",
                    json={"path": str(output), "role": "derived"},
                ).status_code
                == 200
            )
            prefix += f"/projects/{pid}"
        body = {"selection": {"source": str(source)}}
        dry_run = client.post(prefix + "/tasks/dicom.convert/estimate", json=body)
        assert dry_run.status_code == 200, dry_run.text
        refusal = client.post(prefix + "/task-runs", json={**body, "task_id": "dicom.convert"})
        assert refusal.status_code == 422, refusal.text
        assert "configure:DICOM_MEMORY_MB" in refusal.json()["actions"]
        assert list(output.iterdir()) == []


def test_segmentation_reservation_blocks_dicom_and_dicom_blocks_the_host_slot(
    tmp_path: Path,
) -> None:
    import asyncio

    from plugins.runner.gpu import Pool

    from app.core.fsio import read_json
    from app.tasks import protocol
    from app.tasks.dicom_execution import run_dicom_job

    source, workspace, pool_root = tmp_path / "source", tmp_path / "workspace", tmp_path / "pool"
    write_series(source)
    settings = Settings(workspace_root=workspace, host_allocation_root=pool_root, _env_file=None)  # type: ignore[call-arg]
    pool = Pool(pool_root)
    assert pool.reserve({"attempt": "synthetic-segmentation", "gpus": ["GPU-test"]})
    job = workspace / "attempt"
    protocol.write_job(job, {"operation": "inventory", "source": str(source), "attempt": 1})

    async def scenario() -> None:
        def before_dispatch(_: int) -> None:
            lease = pool.read()
            assert lease and lease["owner"] == "dicom" and lease["gpus"] == []
            assert not pool.reserve({"attempt": "other-workspace", "gpus": ["GPU-test"]})

        execution = asyncio.create_task(
            run_dicom_job(job, workspace=workspace, settings=settings, on_started=before_dispatch)
        )
        await asyncio.sleep(0.2)
        assert not (job / "launch.json").exists()
        assert pool.release("synthetic-segmentation")
        outcome = await asyncio.wait_for(execution, timeout=10)
        assert outcome["exit_code"] == 0 and outcome["cleanup_verified"]
        assert read_json(job / "resources.json")["cpu_threads"] == 4
        assert pool.read() is None

    asyncio.run(scenario())


def test_insufficient_native_budget_queues_without_pixels_and_can_cancel(tmp_path: Path) -> None:
    import time

    from app.core.fsio import read_json
    from tests.test_api_ingest import wait

    source, output = tmp_path / "source", tmp_path / "derived"
    write_series(source / "P0" / "series", shape=(128, 128, 16), marker=(1, 1, 2))
    output.mkdir()
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        allowed_derived_roots=str(output),
        dicom_memory_mb=512,
        _env_file=None,
    )  # type: ignore[call-arg]
    before = sorted(os.sched_getaffinity(0))
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        started = client.post(
            "/api/v1/task-runs",
            json={
                "task_id": "dicom.convert",
                "name": "bounded",
                "selection": {"source": str(source)},
            },
        )
        assert started.status_code == 202, started.text
        rid = started.json()["run_id"]
        deadline = time.monotonic() + 12
        run = {}
        while time.monotonic() < deadline:
            run = client.get("/api/v1/task-runs/" + rid).json()
            if run["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert run["status"] == "waiting_for_resources", run
        assert not [p for p in output.rglob("*.nii.gz") if p.is_file()]
        assert not list(output.rglob("dataset.json"))
        assert not (settings.allocation_root / "lease.json").exists()
        evidence = next(
            settings.workspace_root.glob("plugins/dicom/runs/*/attempts/*/worker-resources.json")
        )
        native = read_json(evidence)
        assert len(native["affinity"]) <= 4 and native["pixel_memory_mb"] == 512
        assert native["address_space_limit_mb"] <= 512
        response = client.post("/api/v1/task-runs/" + rid + "/cancel")
        assert response.status_code == 200
        wait(client, started.json()["job_id"])
        assert client.get("/api/v1/task-runs/" + rid).json()["status"] == "cancelled"
        settings.dicom_memory_mb = 1024
        resumed = client.post("/api/v1/task-runs/" + rid + "/resume")
        assert resumed.status_code == 202, resumed.text
        wait(client, resumed.json()["job_id"])
        assert client.get("/api/v1/task-runs/" + rid).json()["status"] == "completed"
    assert sorted(os.sched_getaffinity(0)) == before


def test_supervisor_rejects_a_different_pool_and_never_recovers_a_dicom_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import sys

    from plugins.runner import service
    from plugins.runner.gpu import Pool
    from plugins.runner.supervised import Supervisor

    from app.tasks.dicom_resources import initialize

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    pool_path = tmp_path / "pool"
    initialize(Settings(workspace_root=workspace, host_allocation_root=pool_path, _env_file=None))  # type: ignore[call-arg]
    conf = tmp_path / "deployment.json"
    raw = {
        "deployment": 1,
        "backend": "server",
        "workspace": str(workspace),
        "environment": str(Path(sys.executable).parent.parent),
        "source_roots": [str(tmp_path / "source")],
        "derived_roots": [str(tmp_path / "derived")],
        "model_roots": [str(tmp_path / "models")],
        "state_dir": str(tmp_path / "different-pool"),
        "limits": {"cpus": 4, "memory_mb": 1024, "tasks": 32, "seconds": 60, "gpus": 1},
    }
    conf.write_text(json.dumps(raw))
    conf.chmod(0o600)
    with pytest.raises(ValueError, match="shared HOST_ALLOCATION_ROOT"):
        Supervisor(conf).verify_allocation_policy()
    raw["state_dir"] = str(pool_path)
    conf.write_text(json.dumps(raw))
    supervisor = Supervisor(conf)
    supervisor.verify_allocation_policy()
    pool = Pool(pool_path)
    reservation = {
        "owner": "dicom",
        "workspace": str(workspace),
        "attempt": "dicom-test",
        "gpus": [],
    }
    assert pool.reserve(reservation)

    def never_signal(*_: object) -> None:
        raise AssertionError("A host supervisor must not control the in-image DICOM writer")

    monkeypatch.setattr(service, "show", never_signal)
    supervisor.recover()
    assert supervisor.record is None and pool.read() == reservation


def test_container_pixel_work_requires_an_explicit_shared_allocation(tmp_path: Path) -> None:
    from app.core.errors import ValidationProblem
    from app.tasks.dicom_resources import require_pixel_budget

    settings = Settings(
        container_mode=True,
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(tmp_path / "source"),
        dicom_memory_mb=1024,
        _env_file=None,
    )  # type: ignore[call-arg]
    with pytest.raises(ValidationProblem) as refused:
        require_pixel_budget(settings)
    assert refused.value.actions == ["configure:HOST_ALLOCATION_ROOT"]
