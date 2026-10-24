"""DCM-16/17, D26/D27: committed series and stage/resource facts stay distinct."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from plugins.dicom import commits, pipeline, scan

from app.tasks.records import Live
from tests.test_api_ingest import ctx_of, wait
from tests.test_dicom_resume import run_conversion
from tests.test_source_operation_conversion import native_run, prepared_operation
from tests.test_source_operations_api import API, control, wait_operation
from tools.dicom_fixtures import write_series


def test_native_series_progress_excludes_skips_and_failed_publications(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "source", tmp_path / "derived"
    write_series(source / "valid", patient_id="P001")
    write_series(source / "scout", patient_id="P002", description="LOCALIZER")
    write_series(source / "failure", patient_id="P003")
    original = commits.commit_series

    def fail_one(series: scan.Series, *args: Any, **kwargs: Any) -> Any:
        if series.dicom_dir.name == "failure":
            raise OSError("synthetic publication failure")
        return original(series, *args, **kwargs)

    monkeypatch.setattr(commits, "commit_series", fail_one)
    totals: list[int] = []
    stages: list[tuple[str, int, int]] = []
    result = run_conversion(
        source,
        output,
        settings=pipeline.Settings(),
        on_total=totals.append,
        on_stage=lambda *row: stages.append(row),
    )
    assert result.counts["converted"] == result.counts["failed"] == result.counts["skipped"] == 1
    assert totals == [2]
    assert [row for row in stages if row[0] == "converting"][-1] == ("converting", 1, 2)


@pytest.mark.parametrize("in_project", [False, True])
def test_api_progress_retains_committed_total_after_native_completion(
    tmp_path: Path, in_project: bool
) -> None:
    with prepared_operation(tmp_path, in_project) as prepared:
        client, _, source, _, record, _ = prepared
        operation = record["operation_id"]
        write_series(source / "scout", description="LOCALIZER")
        assert control(client, operation, "estimate").status_code == 202
        ready = wait_operation(client, operation)
        assert ready["estimate"]["n_units"] == ready["estimate"]["n_skipped"] == 1
        assert (
            client.post(
                f"{API}/{operation}/convert",
                json={
                    "expected_revision": ready["revision"],
                    "expected_attempt": ready["attempt"],
                    "inventory_generation": ready["summary"]["generation"],
                    "plan_attempt": ready["plan_attempt"],
                    "name": "committed-progress",
                },
            ).status_code
            == 202
        )
        native = native_run(client, operation)
        wait(client, native["job_id"])
        final = client.get(f"{API}/{operation}").json()["conversion_run"]
        assert final["status"] == "completed", final
        assert final["progress"]["done"] == final["progress"]["total"] == 1
        assert final["counts"]["skipped"] == 1


@pytest.mark.parametrize("in_project", [False, True])
def test_api_memory_wait_preserves_stage_and_actionable_budget(
    tmp_path: Path, in_project: bool
) -> None:
    with prepared_operation(tmp_path, in_project) as prepared:
        client, settings, _, _, record, request = prepared
        settings.dicom_memory_mb = 512
        operation = record["operation_id"]
        assert client.post(f"{API}/{operation}/convert", json=request).status_code == 202
        native = native_run(client, operation)
        waiting = wait_operation(client, operation)
        assert waiting["status"] == "waiting_for_resources"
        run = waiting["conversion_run"]
        assert run["progress"]["stage"] == "waiting_for_resources"
        detail = (
            (run.get("execution") or {}).get("resource_wait")
            if in_project
            else run["resource_wait"]
        )
        assert detail["budget_mb"] == 512 and detail["required_mb"] > 512
        assert run["resource_wait"]["budget_mb"] == detail["budget_mb"]
        assert run["resource_wait"]["required_mb"] == detail["required_mb"]
        assert control(client, operation, "cancel").status_code == 200
        wait(client, native["job_id"])


@pytest.mark.parametrize(
    "in_project,callback",
    [(True, "progress"), (True, "finish"), (False, "finish"), (True, "completed_progress")],
)
def test_late_attempt_callbacks_cannot_regress_a_resumed_run(
    tmp_path: Path, in_project: bool, callback: str
) -> None:
    with prepared_operation(tmp_path, in_project) as prepared:
        client, settings, _, _, record, request = prepared
        operation = record["operation_id"]
        settings.dicom_memory_mb = 512
        assert client.post(f"{API}/{operation}/convert", json=request).status_code == 202
        old = native_run(client, operation)
        assert wait_operation(client, operation)["status"] == "waiting_for_resources"
        assert control(client, operation, "cancel").status_code == 200
        wait(client, old["job_id"])
        settings.dicom_memory_mb = 1024
        resumed = control(client, operation, "resume")
        assert resumed.status_code == 202, resumed.text
        wait(client, resumed.json()["conversion_run"]["job_id"])
        current = client.get(f"{API}/{operation}").json()["conversion_run"]
        assert current["status"] == "completed" and current["attempts"] == 2
        context = ctx_of(client)
        operations = context.source_operations
        service = operations.tasks if in_project else operations.workspace_tasks
        run_dir = (
            service.runs.run_dir(record["project_id"], old["run_id"])
            if in_project
            else service._find(old["run_id"])
        )
        before = (run_dir / "run.json").read_bytes()
        info = context.jobs.get(old["job_id"])
        if in_project:
            live = Live(
                record["project_id"],
                old["run_id"],
                run_dir,
                run_dir
                / "attempts"
                / (current["job_id"] if callback == "completed_progress" else old["job_id"]),
                service.get("dicom.convert").manifest,
                None,
            )
            if callback.endswith("progress"):
                client.portal.call(
                    service._on_lines,
                    live,
                    [
                        {
                            "t": "stage",
                            "stage": "waiting_for_resources",
                            "done": 0,
                            "total": 0,
                            "resource_wait": {"reason": "late old attempt"},
                        }
                    ],
                )
            else:
                client.portal.call(service._finish, live, info)
        else:
            service._finish(run_dir, run_dir / "attempts" / old["job_id"], info)
        assert (run_dir / "run.json").read_bytes() == before
