"""CTF-15: reviewer and origin on source operations, their conversion and phase runs, and batch
plans; records written before attribution existed still load, with no origin."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.reviewer import Origin
from app.main import create_app
from app.tasks.models import TaskRunRecord
from app.tasks.source_batches import PlanRecord
from app.tasks.source_operations import SourceOperation
from app.tasks.workspace_runs import WorkspaceRun
from tests.test_api_ingest import wait
from tests.test_source_batches import PLANS, app_client, create_plan, patients, wait_plan
from tests.test_source_operations_api import API, control, wait_operation
from tools.dicom_fixtures import write_series


@pytest.mark.parametrize("in_project", [False, True])
def test_conversion_run_is_stamped_by_whoever_converts_and_inherits_the_origin(
    tmp_path: Path, in_project: bool
) -> None:
    source, derived = tmp_path / "source", tmp_path / "derived"
    write_series(source)
    derived.mkdir()
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        allowed_derived_roots=str(derived),
        dicom_memory_mb=1024,
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        project = None
        if in_project:
            project = client.post("/api/v1/projects", json={"name": "C", "packs": []}).json()[
                "project_id"
            ]
            roots = f"/api/v1/projects/{project}/roots/DERIVED"
            assert client.put(roots, json={"path": str(derived), "role": "derived"}).is_success
        started = client.post(
            API,
            json={"path": str(source), "project_id": project, "idempotency_key": "attribution-1"},
            headers={"X-Reviewer": "Starter"},
        )
        assert started.status_code == 202, started.text
        operation = started.json()["operation_id"]
        assert started.json()["reviewer"] == "Starter"
        assert started.json()["origin"]["client"] == "gui"
        wait_operation(client, operation)
        assert control(client, operation, "estimate").status_code == 202
        planned = wait_operation(client, operation)
        converted = client.post(
            f"{API}/{operation}/convert",
            json={
                "expected_revision": planned["revision"],
                "expected_attempt": planned["attempt"],
                "inventory_generation": planned["summary"]["generation"],
                "plan_attempt": planned["plan_attempt"],
            },
            headers={"X-Reviewer": "Converter"},
        )
        assert converted.status_code == 202, converted.text
        run = None
        deadline = time.monotonic() + 15
        while run is None and time.monotonic() < deadline:
            run = client.get(f"{API}/{operation}").json().get("conversion_run")
            time.sleep(0.02)
        assert run is not None
        wait(client, run["job_id"])
        final = client.get(f"{API}/{operation}").json()
        assert final["reviewer"] == "Starter"
        conversion = final["conversion_run"]
        assert conversion["reviewer"] == "Converter" and conversion["origin"]["client"] == "gui"
        prefix = f"/api/v1/projects/{project}" if project else "/api/v1"
        phase = client.get(f"{prefix}/task-runs/{conversion['phase_run_id']}").json()
        assert phase["reviewer"] == "Converter" and phase["origin"]["client"] == "gui"


def test_batch_plan_stamps_itself_and_its_operations(tmp_path: Path) -> None:
    source = tmp_path / "source"
    patients(source, ["a", "b"])
    with app_client(tmp_path) as client:
        created = client.post(
            PLANS,
            json={"path": str(source), "batch_size": 1, "name": "att"},
            headers={"X-Reviewer": "Planner"},
        )
        assert created.status_code == 201, created.text
        plan = created.json()
        assert plan["reviewer"] == "Planner" and plan["origin"]["client"] == "gui"
        assert client.post(f"{PLANS}/{plan['plan_id']}/start").status_code == 202
        ready = wait_plan(client, plan["plan_id"], lambda p: p["batches"][0]["operation_id"])
        operation = client.get(f"{API}/{ready['batches'][0]['operation_id']}").json()
        assert operation["reviewer"] == "Planner" and operation["origin"]["client"] == "gui"
        unnamed = create_plan(client, source, batch_size=1, name="anon")
        assert unnamed["reviewer"] is None


def test_records_from_before_attribution_still_load_without_an_origin() -> None:
    base = {"run_id": "r", "name": "n", "status": "completed", "created_at": "t"}
    task = {"id": "t.x", "version": "1", "manifest_hash": "h"}
    old_run = TaskRunRecord.model_validate(
        {**base, "task": task, "runtime": "builtin", "settings": {}, "settings_hash": "h",
         "selection": {}}
    )  # fmt: skip
    old_workspace = WorkspaceRun.model_validate(
        {**base, "task": task, "plugin": "dicom", "source": "/s", "dataset_dir": "/d",
         "settings": {}, "settings_hash": "h"}
    )  # fmt: skip
    old_operation = SourceOperation.model_validate(
        {"operation_id": "o", "source": "/s", "project_id": None, "purpose": "convert",
         "created_at": "t", "updated_at": "t", "request_hash": "h"}
    )  # fmt: skip
    old_plan = PlanRecord.model_validate(
        {"plan_id": "p", "source": "/s", "settings": {}, "batch_size": 1, "name": "n",
         "auto": False, "salt": "s", "created_at": "t", "updated_at": "t", "batches": []}
    )  # fmt: skip
    for record in (old_run, old_workspace, old_operation, old_plan):
        assert record.origin is None and record.reviewer is None
    assert Origin().client == "gui"
