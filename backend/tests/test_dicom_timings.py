"""D25/D26: stage history is bounded, compatible, idempotent and metadata-only."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.core.fsio import atomic_write_json, read_json
from app.tasks import dicom_timings
from app.tasks.dicom_timings import record_stage


def job(root: Path, name: str, *, cpus: int = 1) -> Path:
    source = root / "source"
    source.mkdir(exist_ok=True)
    work = root / name
    work.mkdir()
    atomic_write_json(work / "job.json", {"source": str(source), "attempt": 1})
    atomic_write_json(work / "resources.json", {"cpu_threads": cpus})
    atomic_write_json(
        work / "timing-history-path.json", {"path": str(root / "timing-history.json")}
    )
    return work


def test_stage_replay_does_not_duplicate_or_replace_measured_time(tmp_path: Path) -> None:
    work = job(tmp_path, "attempt-a")
    original = record_stage(work, "discovery", 2.5, 100)
    history = tmp_path / "stage-timing-history.json"
    digest = hashlib.sha256(history.read_bytes()).hexdigest()
    assert record_stage(work, "discovery", 999, 200) == original
    assert hashlib.sha256(history.read_bytes()).hexdigest() == digest
    assert read_json(work / "stage-timings.json")["stages"]["discovery"] == {
        "seconds": 2.5,
        "work": 100,
        "complete": True,
    }
    raw = history.read_text()
    assert str(tmp_path) not in raw and "source" not in raw


def test_context_separates_stage_concurrency_scope_and_resume(tmp_path: Path) -> None:
    for name, stage, cpus in [
        ("first", "discovery", 1),
        ("second", "discovery", 1),
        ("planning", "planning", 1),
        ("concurrent", "discovery", 2),
    ]:
        assert record_stage(job(tmp_path, name, cpus=cpus), stage, 2, 100)
    for name, changed in [("workspace", {"workspace": True}), ("resumed", {"attempt": 2})]:
        work = job(tmp_path, name)
        atomic_write_json(work / "job.json", {**read_json(work / "job.json"), **changed})
        assert record_stage(work, "discovery", 2, 100)
    samples = read_json(tmp_path / "stage-timing-history.json")["samples"]
    assert samples[0]["context"] == samples[1]["context"]
    assert len({s["context"] for s in samples}) == 5


def test_cancelled_work_retains_duration_without_training_completed_history(tmp_path: Path) -> None:
    work = job(tmp_path, "cancelled")
    result = record_stage(work, "discovery", 4, 12, complete=False)
    assert result and not result["complete"]
    assert (work / "stage-timings.json").is_file()
    assert not (tmp_path / "stage-timing-history.json").exists()


@pytest.mark.parametrize("corrupt", [b'{"version":', b'{"version":1,"samples":[null]}'])
def test_broken_advisory_history_preserves_measurement_and_evidence(
    tmp_path: Path, corrupt: bytes
) -> None:
    history = tmp_path / "stage-timing-history.json"
    history.write_bytes(corrupt)
    work = job(tmp_path, "healthy-work")
    assert record_stage(work, "registration", 2, 10) == {"seconds": 2, "work": 10, "complete": True}
    assert history.read_bytes() == corrupt
    assert read_json(work / "stage-timings.json")["stages"]["registration"]["seconds"] == 2


def test_history_retains_only_the_bounded_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dicom_timings, "MAX_SAMPLES", 2)
    for index in range(3):
        record_stage(job(tmp_path, f"attempt-{index}"), "analyzing", index + 1, 10)
    samples = read_json(tmp_path / "stage-timing-history.json")["samples"]
    assert [s["seconds"] for s in samples] == [2, 3]


@pytest.mark.parametrize("in_project", [False, True])
def test_real_pipeline_records_all_stages_without_changing_sources(
    tmp_path: Path, in_project: bool
) -> None:
    from tests.test_api_ingest import wait
    from tests.test_source_operation_conversion import native_run, prepared_operation

    with prepared_operation(tmp_path, in_project) as prepared:
        client, settings, source, _, record, request = prepared
        before = {
            p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()
        }
        response = client.post(
            f"/api/v1/source-operations/{record['operation_id']}/convert", json=request
        )
        assert response.status_code == 202, response.text
        run = native_run(client, record["operation_id"])
        assert wait(client, run["job_id"]).status == "succeeded"
        history = settings.workspace_root / "plugins/dicom/stage-timing-history.json"
        samples = read_json(history)["samples"]
        assert {s["stage"] for s in samples} >= {
            "discovery",
            "planning",
            "registration",
            "analyzing",
        }, samples
        assert all(s["seconds"] > 0 and s["work"] > 0 for s in samples)
        assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
