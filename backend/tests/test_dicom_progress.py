"""DCM-16/17/20/21/25, D26/D27/D36/D37: committed series and stage/resource facts stay distinct."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rw_dicom import commits, pipeline, scan

from app.tasks.dicom_bytes import progress_fields
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
        progress = final["progress"]
        assert progress["bytes_done"] == progress["bytes_total"] > 0


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


def test_discovery_progress_reports_totals_and_rejected_before_the_walk_ends(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    source = tmp_path / "source"
    write_series(source / "a", patient_id="P001", shape=(3, 3, 3), marker=(1, 1, 2))
    write_series(source / "b", patient_id="P002", shape=(3, 3, 2), marker=(1, 1, 1))
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        response = client.post(
            API, json={"path": str(source), "purpose": "discover", "idempotency_key": "totals-key"}
        )
        assert response.status_code == 202, response.text
        record = wait_operation(client, response.json()["operation_id"])
    assert record["status"] == "completed", record
    assert record["progress"]["files_total"] == 5
    assert record["progress"]["folders_total"] == 3
    assert "rejected" in record["progress"]
    assert record["progress_stage"] is None
    assert record["discovery_eta"]["basis"] == "unknown"
    assert record["summary"]["files_total"] == 5


def test_discovery_eta_is_unknown_until_enough_new_files_or_time() -> None:
    from app.tasks.discovery_rate import DiscoveryRate

    rate = DiscoveryRate()
    assert rate.update(0.0, 0, 0, 10_000)["basis"] == "unknown"
    for second in range(1, 12):
        eta = rate.update(float(second), second * 50, second * 50, 10_000)
    assert eta["basis"] == "unknown"  # 550 new files, 11 s
    for second in range(12, 33):
        eta = rate.update(float(second), second * 50, second * 50, 10_000)
    assert eta["basis"] == "recent_rate"  # 30 s of samples
    assert eta["low_s"] == eta["high_s"] == round((10_000 - 32 * 50) / 50)
    fast = DiscoveryRate()
    for second in range(0, 8):
        eta = fast.update(float(second), second * 500, second * 500, 100_000)
    assert eta["basis"] == "recent_rate"  # >= 2,000 new files before 30 s
    assert DiscoveryRate().update(0.0, 0, 0, None)["basis"] == "unknown"


def test_discovery_eta_range_uses_window_extremes_and_ignores_reused_and_downtime() -> None:
    from app.tasks.discovery_rate import DiscoveryRate

    rate = DiscoveryRate()
    now, read = 0.0, 0
    rate.update(now, read, 0, 100_000)
    for per_second in (100, 100, 100, 400, 400, 400, 100):  # 5 s buckets
        for _ in range(5):
            now, read = now + 1, read + per_second
            eta = rate.update(now, read, read, 100_000)
    remaining = 100_000 - read
    assert eta["low_s"] == round(remaining / 400)
    assert eta["high_s"] == round(remaining / 100)
    # A long pause (downtime) and a stretch of reused files without new reads add no samples.
    now += 3600
    files = read
    for _ in range(30):
        now, files = now + 1, files + 1000
        eta = rate.update(now, read, files, 100_000)
    assert eta["high_s"] == round((100_000 - files) / 100)
    assert eta["low_s"] == round((100_000 - files) / 400)
    now, read, files = now + 1, read + 100, files + 100
    eta = rate.update(now, read, files, 100_000)
    assert eta["high_s"] == round((100_000 - files) / 100)


def folder_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def test_bytes_progress_counts_committed_series_and_leaves_out_skips_and_failures(
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
    events: list[dict[str, float]] = []
    run_conversion(source, output, settings=pipeline.Settings(), on_bytes=events.append)
    planned = folder_bytes(source / "valid") + folder_bytes(source / "failure")
    assert events[0] == {"done": 0, "total": planned, "fresh_bytes": 0, "fresh_seconds": 0.0}
    last = events[-1]
    assert last["total"] == planned and last["done"] == folder_bytes(source / "valid")
    assert last["fresh_bytes"] == last["done"] and last["fresh_seconds"] > 0
    assert [e["done"] for e in events] == sorted(e["done"] for e in events)


def test_resumed_attempt_counts_reused_commits_as_done_but_not_as_measured_speed(
    tmp_path: Path,
) -> None:
    source, output = tmp_path / "source", tmp_path / "derived"
    for name in ("a", "b"):
        write_series(source / name, patient_id=f"P-{name}")
    first: list[dict[str, float]] = []
    run_conversion(source, output, on_bytes=first.append)
    resumed: list[dict[str, float]] = []
    result = run_conversion(source, output, on_bytes=resumed.append)
    assert result.counts["already_converted"] == 2
    total = folder_bytes(source / "a") + folder_bytes(source / "b")
    assert first[-1]["done"] == resumed[-1]["done"] == resumed[-1]["total"] == total
    assert resumed[-1]["fresh_bytes"] == 0 and resumed[-1]["fresh_seconds"] == 0
    assert progress_fields(resumed[-1]) == {"bytes_done": total, "bytes_total": total}
    assert progress_fields(first[-1])["bytes_per_s"] > 0


def test_estimate_runs_report_no_bytes(tmp_path: Path) -> None:
    from rw_dicom.identity import Identity

    source = tmp_path / "source"
    write_series(source / "a")
    events: list[dict[str, float]] = []
    pipeline.run(
        source,
        pipeline.Settings(),
        Identity(),
        nifti_dir=tmp_path / "n",
        sidecar_dir=tmp_path / "s",
        ref_rel="dataset",
        ref_alias="DERIVED",
        salt="t",
        previous=[],
        dry_run=True,
        on_bytes=events.append,
    )
    assert events == []


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            {"done": 5, "total": 10, "fresh_bytes": 4_000, "fresh_seconds": 2.0},
            {"bytes_done": 5, "bytes_total": 10, "bytes_per_s": 2000},
        ),
        ({"done": 50, "total": 10}, {"bytes_done": 10, "bytes_total": 10}),
        (
            {"done": 1, "total": 2, "fresh_bytes": 9, "fresh_seconds": 0},
            {"bytes_done": 1, "bytes_total": 2},
        ),
        ({"done": float("nan"), "total": 2}, {}),
        ({"done": -1, "total": 2}, {}),
        ({"total": 2}, {}),
    ],
)
def test_progress_fields_are_bounded_and_withhold_speed_without_measured_work(
    event: dict[str, Any], expected: dict[str, int]
) -> None:
    assert progress_fields(event) == expected
