"""D29/ANZ-02/04: conversion and its optional phase analyzer have distinct run records."""

import hashlib
import time
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.fsio import atomic_write_json, read_json
from app.core.ids import new_ulid
from app.main import create_app
from app.tasks.workspace_runs import WorkspaceRun
from tests.test_api_ingest import ctx_of, wait
from tests.test_source_operation_conversion import prepared_operation
from tests.test_source_operations_api import API, wait_operation


def digests(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("in_project", [False, True])
def test_converted_phase_is_registered_as_its_own_analyzer_run(
    tmp_path: Path, in_project: bool
) -> None:
    with prepared_operation(tmp_path, in_project) as (client, settings, _, _, ready, request):
        oid = ready["operation_id"]
        response = client.post(f"{API}/{oid}/convert", json=request)
        assert response.status_code == 202, response.text
        completed = wait_operation(client, oid)
        conversion = completed["conversion_run"]
        assert conversion["status"] == "completed", conversion
        phase_id = conversion.get("phase_run_id")
        assert phase_id and phase_id != conversion["run_id"], conversion
        if in_project:
            pid = ready["project_id"]
            detail = client.get(f"/api/v1/projects/{pid}/task-runs/{phase_id}")
            project = client.get(f"/api/v1/projects/{pid}").json()
            assert project["annotation_sources"]["phase"] == phase_id
            directory = ctx_of(client).workspace.project_dir(pid) / "tasks/runs" / phase_id
        else:
            detail = client.get(f"/api/v1/task-runs/{phase_id}")
            directory = settings.workspace_root / "plugins/analyzers/runs" / phase_id
        assert detail.status_code == 200, detail.text
        analyzer = detail.json()
        assert analyzer["task"]["id"] == "analyzer.phase"
        assert analyzer["status"] == "completed"
        assert analyzer["counts"]["ok"] == 1
        assert analyzer["provenance"]["source_conversion_run_id"] == conversion["run_id"]
        assert completed["phase_run"]["run_id"] == phase_id
        assert (directory / "annotations.jsonl").is_file()
        if not in_project:
            persisted = WorkspaceRun.model_validate(read_json(directory / "run.json"))
            assert persisted.source == analyzer["source"]
            assert persisted.plugin == "analyzers"
            assert persisted.cleanup_verified


@pytest.mark.parametrize("in_project", [False, True])
@pytest.mark.parametrize("cancel_retry", [False, True])
def test_failed_analyzer_retries_metadata_without_reconverting_or_rewriting_the_dataset(
    tmp_path: Path, in_project: bool, cancel_retry: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.runner.gpu import Pool

    from app.tasks.dicom_phase import PhaseRuns

    with prepared_operation(tmp_path, in_project) as (
        client,
        settings,
        source,
        derived,
        ready,
        request,
    ):
        before_source = digests(source)
        oid = ready["operation_id"]
        original = PhaseRuns.prepare
        state: Path | None = None

        def fail_first_batch(self, pid, parent):
            nonlocal state
            original(self, pid, parent)
            if state is None:
                parent_dir = (
                    self.workspace.project_dir(pid) / "tasks/runs"
                    if pid
                    else settings.workspace_root / "plugins/dicom/runs"
                ) / parent.run_id
                state = parent_dir / "phase-analyzer"
                state.mkdir(mode=0o700, exist_ok=True)
                # A real batch-publication failure, injected before the owned worker starts.
                (state / "batch-0.json").mkdir()

        monkeypatch.setattr(PhaseRuns, "prepare", fail_first_batch)
        started = client.post(f"{API}/{oid}/convert", json=request)
        assert started.status_code == 202, started.text
        completed = wait_operation(client, oid)
        assert completed["conversion_run"]["status"] == "completed", completed
        analyzer = completed["phase_run"]
        assert analyzer["status"] == "failed", analyzer
        manual_item = None
        if in_project:
            pid = ready["project_id"]
            manual_item = client.get(f"/api/v1/projects/{pid}/items").json()["items"][0]
            selected = client.post(
                f"/api/v1/projects/{pid}/phase/events",
                json={
                    "case_id": manual_item["case_id"],
                    "scan_idx": manual_item["scan_idx"],
                    "value": "NC",
                },
                headers={"X-Reviewer": "D29 test"},
            )
            assert selected.status_code == 201, selected.text
        assert state is not None
        assert (state / "inputs.json").is_file()
        (state / "batch-0.json").rmdir()
        before_outputs = digests(derived)
        phase_id = analyzer["run_id"]
        url = (
            f"/api/v1/projects/{ready['project_id']}/task-runs/{phase_id}"
            if in_project
            else f"/api/v1/task-runs/{phase_id}"
        )
        assert client.post(f"{url}/resume", json={}).status_code == 409
        assert client.post(f"{url}/resume", json={"expected_attempt": 0}).status_code == 409
        if not in_project and not cancel_retry:
            inputs = state / "inputs.json"
            original_inputs = inputs.read_bytes()
            inputs.write_text("{}")
            rejected = client.post(f"{url}/resume", json={"expected_attempt": analyzer["attempts"]})
            assert rejected.status_code == 202, rejected.text
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                rejected_run = client.get(url).json()
                if rejected_run["status"] == "failed":
                    break
                time.sleep(0.02)
            assert rejected_run["status"] == "failed", rejected_run
            assert rejected_run["error"] and rejected_run["counts"]["items"] == 1
            assert digests(derived) == before_outputs
            inputs.write_bytes(original_inputs)
            analyzer = rejected_run
        with Pool(settings.allocation_root).locked() if cancel_retry else nullcontext():
            resumed = client.post(f"{url}/resume", json={"expected_attempt": analyzer["attempts"]})
            assert resumed.status_code == 202, resumed.text
            duplicate = client.post(
                f"{url}/resume", json={"expected_attempt": analyzer["attempts"]}
            )
            assert (
                duplicate.status_code == 202
                and duplicate.json()["job_id"] == resumed.json()["job_id"]
            )
            if cancel_retry:
                attempt = analyzer["attempts"] + 1
                assert (
                    client.post(f"{url}/cancel", json={"expected_attempt": attempt - 1}).status_code
                    == 409
                )
                cancelled = client.post(f"{url}/cancel", json={"expected_attempt": attempt})
                assert cancelled.status_code == 200, cancelled.text
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    paused = client.get(url).json()
                    if paused["status"] == "cancelled":
                        break
                    time.sleep(0.02)
                assert paused["status"] == "cancelled", paused
                assert digests(derived) == before_outputs
        if cancel_retry:
            analyzer = paused
            resumed = client.post(f"{url}/resume", json={"expected_attempt": analyzer["attempts"]})
            assert resumed.status_code == 202, resumed.text
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            current = client.get(url).json()
            if current["status"] in {"completed", "failed", "cancelled", "cleanup_pending"}:
                break
            time.sleep(0.02)
        assert current["status"] == "completed", current
        assert current["run_id"] == phase_id and current["attempts"] == analyzer["attempts"] + 1
        assert current["counts"]["ok"] == 1
        unchanged = client.get(f"{API}/{oid}").json()["conversion_run"]
        assert unchanged["run_id"] == completed["conversion_run"]["run_id"]
        assert unchanged["attempts"] == completed["conversion_run"]["attempts"]
        assert digests(derived) == before_outputs
        assert digests(source) == before_source
        if manual_item is not None:
            item = client.get(
                f"/api/v1/projects/{ready['project_id']}/items/{manual_item['item_id']}"
            ).json()
            assert item["phase"]["canonical"] == "NC" and item["phase"]["source"] == "manual"
        if not in_project and not cancel_retry:
            project = client.post("/api/v1/projects", json={"name": "Retried phase", "packs": []})
            pid = project.json()["project_id"]
            dataset = unchanged["dataset_dir"]
            preview = client.post(
                f"/api/v1/projects/{pid}/imports/preview", json={"root": dataset, "detect": True}
            )
            assert preview.status_code == 200, preview.text
            imported = client.post(
                f"/api/v1/projects/{pid}/imports", json={"preview_id": preview.json()["preview_id"]}
            )
            assert imported.status_code == 202, imported.text
            wait(client, imported.json()["job_id"])
            item = client.get(f"/api/v1/projects/{pid}/items").json()["items"][0]
            assert item["phase"]["source"].startswith("analyzer:"), item
            source_run = item["phase"]["source"].removeprefix("analyzer:")
            layer = client.get(f"/api/v1/projects/{pid}/task-runs/{source_run}").json()
            assert layer["task"]["id"] == "analyzer.phase", layer
            assert digests(derived) == before_outputs


@pytest.mark.parametrize("in_project", [False, True])
@pytest.mark.parametrize("cleanup_known", [False, True])
def test_phase_restart_requires_cleanup_proof_before_enabling_retry(
    tmp_path: Path, in_project: bool, cleanup_known: bool
) -> None:
    """D29/BE-06: an orphan attempt is recovered without trusting a cancelled future."""
    with prepared_operation(tmp_path, in_project) as (client, settings, _, derived, ready, request):
        assert (
            client.post(f"{API}/{ready['operation_id']}/convert", json=request).status_code == 202
        )
        completed = wait_operation(client, ready["operation_id"])
        analyzer = completed["phase_run"]
        rid = analyzer["run_id"]
        directory = (
            ctx_of(client).workspace.project_dir(ready["project_id"]) / "tasks/runs"
            if in_project
            else settings.workspace_root / "plugins/analyzers/runs"
        ) / rid
        record = read_json(directory / "run.json")
        job_id = new_ulid()
        job = directory / "attempts" / job_id
        atomic_write_json(job / "reserved.json", {"attempt": 2})
        if not cleanup_known:
            (job / "dispatch").touch()
        record.update(status="running", attempts=2, job_id=job_id, finished_at=None)
        record["execution"].update(shared_conversion_job=False, cleanup_verified=False)
        atomic_write_json(directory / "run.json", record)
        before = digests(derived)
    with TestClient(create_app(settings, inline_jobs=True)) as restarted:
        url = (
            f"/api/v1/projects/{ready['project_id']}/task-runs/{rid}"
            if in_project
            else f"/api/v1/task-runs/{rid}"
        )
        recovered = restarted.get(url)
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["status"] == ("interrupted" if cleanup_known else "cleanup_pending")
        if not cleanup_known:
            refused = restarted.post(f"{url}/resume", json={"expected_attempt": 2})
            assert refused.status_code == 409, refused.text
            assert not list((directory / "attempts").glob("*/job.json"))
            assert digests(derived) == before
            return
        accepted = restarted.post(f"{url}/resume", json={"expected_attempt": 2})
        assert accepted.status_code == 202, accepted.text
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = restarted.get(url).json()
            if current["status"] == "completed":
                break
            time.sleep(0.02)
        assert current["status"] == "completed", current
        assert digests(derived) == before
