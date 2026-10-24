"""D23/DCM-17: Retry failed preserves verified output and leaves unattempted series pending."""

import json
from pathlib import Path
from typing import Any

import pytest
from plugins.dicom import convert, task
from plugins.protocol import Job

from app.core.errors import JobConflict
from app.tasks import protocol, records
from tests.test_dicom_resume import digest, run_conversion
from tools.dicom_fixtures import write_series


def test_retry_failed_never_dispatches_an_unattempted_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, out = tmp_path / "source", tmp_path / "derived"
    for n in range(3):
        write_series(source / f"P{n}", patient_id=f"P{n}", shape=(3, 3, 3), marker=(1, 1, 2))
    original = convert.write_nifti

    def fail_second(series: Any, path: Path) -> Any:
        if series.dicom_dir.name == "P1":
            raise OSError("Synthetic decoder failure")
        return original(series, path)

    monkeypatch.setattr(convert, "write_nifti", fail_second)
    outcomes = []
    checkpoint = out / "run/pin.json"
    first = run_conversion(
        source,
        out,
        checkpoint=checkpoint,
        progress=lambda iid, status, *_: outcomes.append((iid, status)),
        cancelled=lambda: len(outcomes) == 2,
    )
    assert first.counts["converted"] == first.counts["failed"] == 1
    [saved] = list((out / "nifti").glob("*.nii.gz"))
    before = digest(saved), saved.stat().st_mtime_ns
    failed = [iid for iid, status in outcomes if status == "failed"]
    dispatched = []

    def tracked(series: Any, path: Path) -> Any:
        dispatched.append(series.dicom_dir.name)
        return original(series, path)

    monkeypatch.setattr(convert, "write_nifti", tracked)
    retried = run_conversion(
        source, out, checkpoint=checkpoint, retry_item_ids=failed, previous=first.rows
    )
    assert dispatched == ["P1"]
    assert (
        retried.counts["converted"]
        == retried.counts["already_converted"]
        == retried.counts["pending"]
        == 1
    )
    assert retried.counts["failed"] == 0
    assert len(list((out / "nifti").glob("*.nii.gz"))) == 2
    assert (digest(saved), saved.stat().st_mtime_ns) == before
    assert sum(row.get("status") == "pending" for row in retried.rows) == 1
    dispatched.clear()
    resumed = run_conversion(source, out, checkpoint=checkpoint, previous=retried.rows)
    assert dispatched == ["P2"]
    assert resumed.counts["pending"] == 0 and resumed.counts["already_converted"] == 2


@pytest.mark.parametrize("ids", [[], ["unknown.01.complete.-"]])
def test_retry_refuses_empty_or_unrecognized_selection_without_writing_images(
    tmp_path: Path, ids: list[str]
) -> None:
    source, out = tmp_path / "source", tmp_path / "derived"
    write_series(source)
    with pytest.raises(ValueError, match=r"[Rr]etry"):
        run_conversion(source, out, retry_item_ids=ids)
    assert not list((out / "nifti").glob("*.nii.gz"))


@pytest.mark.parametrize("workspace", [True, False])
def test_partial_retry_never_seals_dataset_or_starts_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workspace: bool
) -> None:
    source, dataset = tmp_path / "source", tmp_path / "derived"
    for n in range(3):
        write_series(source / f"P{n}", patient_id=f"P{n}")
    spec = {
        "task": {"id": "dicom.convert"},
        "source": {"path": str(source)},
        "dataset_dir": str(dataset),
        "output_dir": str(dataset),
        "settings": {"convert_excluded": True},
        "workspace": workspace,
    }
    first = tmp_path / "attempt-1"
    protocol.write_job(first, spec)
    original = convert.write_nifti

    def fail_second(series: Any, path: Path) -> Any:
        if series.dicom_dir.name == "P1":
            raise OSError("Synthetic decoder failure")
        return original(series, path)

    def cancelled(job: Job) -> bool:
        return (
            sum(
                json.loads(line).get("t") == "item"
                for line in (job.dir / protocol.PROGRESS).read_text().splitlines()
            )
            >= 2
        )

    with monkeypatch.context() as initial:
        initial.setattr(convert, "write_nifti", fail_second)
        initial.setattr(Job, "cancelled", cancelled)
        assert task.run(str(first)) == 0
    events = [json.loads(line) for line in (first / protocol.PROGRESS).read_text().splitlines()]
    failed = [event["item_id"] for event in events if event.get("status") == "failed"]
    assert len(failed) == 1
    dispatched = []

    def tracked(series: Any, path: Path) -> Any:
        dispatched.append(series.dicom_dir.name)
        return original(series, path)

    def forbidden_phase(*_: Any, **__: Any) -> Any:
        pytest.fail("Incomplete retry must not run the phase analyzer")

    monkeypatch.setattr(convert, "write_nifti", tracked)
    monkeypatch.setattr(task.checkpoint, "analyze_phase", forbidden_phase)
    retry = tmp_path / "attempt-2"
    protocol.write_job(retry, {**spec, "retry_item_ids": failed})
    assert task.run(str(retry)) == 0
    assert dispatched == ["P1"]
    result = protocol.read_result(retry)
    assert result is not None and result["status"] == "interrupted"
    assert result["estimate"]["pending"] == 1
    assert result["counts"]["ok"] == 2 and result["counts"]["failed"] == 0
    assert "Resume" in result["error"]
    assert not (dataset / "dataset.json").exists()
    assert not (retry / "phase-inputs").exists()


def attempt_log(run: Path, name: str, epoch: int, events: list[dict[str, Any]]) -> Path:
    job = run / "attempts" / name
    protocol.write_job(job, {"run_id": run.name, "task": {"id": "dicom.convert"}, "attempt": epoch})
    progress = job / protocol.PROGRESS
    progress.write_text("".join(json.dumps(event) + "\n" for event in events))
    return progress


def test_retry_uses_latest_complete_native_outcomes_in_attempt_order(tmp_path: Path) -> None:
    run = tmp_path / "run"
    attempt_log(
        run,
        "z-old",
        1,
        [
            {"t": "item", "item_id": "fixed", "status": "failed"},
            {"t": "item", "item_id": "still-failed", "status": "failed"},
        ],
    )
    last = attempt_log(
        run,
        "a-new",
        2,
        [
            {"t": "total", "n": 3},
            {"t": "item", "item_id": "fixed", "status": "ok"},
        ],
    )
    with last.open("a") as fh:
        fh.write('{"t":"item","item_id":"torn","status":"failed"')
    attempt_log(
        run, "future-undispatched", 3, [{"t": "item", "item_id": "future", "status": "failed"}]
    )
    outcomes, total = records.dicom_history(run, 2)
    assert total == 3
    assert {iid for iid, event in outcomes.items() if event["status"] == "failed"} == {
        "still-failed"
    }
    assert outcomes["fixed"]["status"] == "ok"


@pytest.mark.parametrize("damage", ["duplicate_epoch", "wrong_run", "corrupt_line"])
def test_retry_refuses_ambiguous_or_corrupt_native_outcomes(tmp_path: Path, damage: str) -> None:
    run = tmp_path / "run"
    progress = attempt_log(
        run, "first", 1, [{"t": "item", "item_id": "failed", "status": "failed"}]
    )
    if damage == "duplicate_epoch":
        attempt_log(run, "second", 1, [])
    elif damage == "wrong_run":
        spec = json.loads((progress.parent / protocol.JOB).read_text())
        protocol.write_job(progress.parent, {**spec, "run_id": "other"})
    else:
        with progress.open("a") as fh:
            fh.write("corrupt complete line\n")
    with pytest.raises(JobConflict, match=r"[Oo]utcome"):
        records.dicom_history(run, 1)
