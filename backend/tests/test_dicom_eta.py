"""D25/D26, TSK-05/DCM-06: compatible measured time, never a pixel calibration."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.tasks.dicom_eta import ConversionTimer, context_signature


def timer(
    path: Path, signature: str = "environment-a", attempt: str = "attempt-a"
) -> ConversionTimer:
    return ConversionTimer(path, signature, attempt)


def plan(t: ConversionTimer, *classes: str) -> dict[str, Any]:
    return t(
        {
            "t": "plan",
            "units": [{"id": str(i), "class": c, "work": 100} for i, c in enumerate(classes)],
        }
    )


def seed(
    path: Path, signature: str = "environment-a", category: str = "native-regular", n: int = 5
) -> None:
    t = timer(path, signature, f"seed-{signature}-{category}")
    plan(t, *([category] * n))
    for i in range(n):
        t({"t": "unit", "id": str(i), "seconds": 10 + i % 3})


def test_unknown_until_five_compatible_completed_observations(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    seed(path, n=4)
    cold = plan(timer(path), "native-regular")
    assert cold["basis"] == "unknown" and cold["estimated_s"] is None
    t = timer(path, attempt="fifth")
    plan(t, "native-regular")
    t({"t": "unit", "id": "0", "seconds": 12})
    warm = plan(timer(path), "native-regular", "native-regular")
    assert warm["basis"] == "history" and warm["sample_count"] == 5
    assert warm["remaining_units"] == 2
    assert 0 < warm["lower_s"] <= warm["estimated_s"] <= warm["upper_s"]
    assert warm["confidence"] == "low"


@pytest.mark.parametrize(
    "change", ["host", "storage", "reader", "concurrency", "codec", "geometry"]
)
def test_incompatible_context_or_series_cannot_supply_an_eta(tmp_path: Path, change: str) -> None:
    path = tmp_path / "history.json"
    seed(path)
    different_series = change in {"codec", "geometry"}
    t = timer(path, "environment-a" if different_series else change)
    result = plan(t, change if different_series else "native-regular")
    assert result["basis"] == "unknown" and result["sample_count"] == 0


@pytest.mark.parametrize(
    "change", ["host", "runtime", "source_root", "output_root", "reader", "concurrency"]
)
def test_measured_context_signature_tracks_execution_and_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from plugins.dicom import commits

    source, output = tmp_path / "source", tmp_path / "derived"
    source.mkdir()
    output.mkdir()
    settings, limits = {"sidecars": True}, {"cpu_threads": 1}
    before = context_signature(source, output, settings, limits)
    if change == "host":
        monkeypatch.setattr("app.tasks.dicom_eta.platform.node", lambda: "another-host")
    elif change == "runtime":
        monkeypatch.setattr("app.tasks.dicom_eta._runtime", lambda: {"python": "another-runtime"})
    elif change == "reader":
        monkeypatch.setattr(commits, "reader_versions", lambda _: {"reader": "changed"})
    elif change == "concurrency":
        limits["cpu_threads"] = 2
    else:
        other = tmp_path / "another-root"
        other.mkdir()
        if change == "source_root":
            source = other
        else:
            output = other
    assert context_signature(source, output, settings, limits) != before


@pytest.mark.parametrize("seconds", [None, 0, -1, math.nan, math.inf])
def test_failed_reused_and_interrupted_units_cannot_train_history(
    tmp_path: Path, seconds: float | None
) -> None:
    path = tmp_path / "history.json"
    t = timer(path)
    plan(t, *(["native-regular"] * 6))
    for i in range(5):
        t({"t": "unit", "id": str(i), "seconds": seconds})
    # Unit 5 was interrupted and never acknowledged. Restart/downtime contributes no sample.
    assert plan(timer(path, attempt="restart"), "native-regular")["basis"] == "unknown"


def test_remaining_work_and_sample_replay_are_independent(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    seed(path)
    t = timer(path, attempt="resume")
    before = plan(t, "native-regular", "native-regular")
    after = t({"t": "unit", "id": "0", "seconds": None})  # verified existing commit
    assert after["remaining_units"] == 1
    assert after["estimated_s"] == pytest.approx(before["estimated_s"] / 2)
    assert after["sample_count"] == 5
    completed = t({"t": "unit", "id": "1", "seconds": 11})
    assert completed["basis"] == "complete" and completed["estimated_s"] == 0
    replay = timer(path, attempt="resume")
    plan(replay, "native-regular", "native-regular")
    replay({"t": "unit", "id": "1", "seconds": 999})
    assert plan(timer(path), "native-regular")["sample_count"] == 6


def test_failed_series_remain_pending_without_training_or_shortening_the_estimate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.json"
    seed(path)
    t = timer(path, attempt="partially-failed")
    before = plan(t, "native-regular", "native-regular")
    failed = t({"t": "unit", "id": "0", "seconds": 999, "committed": False})
    assert failed == before
    reused = t({"t": "unit", "id": "1", "seconds": None, "committed": True})
    assert reused["remaining_units"] == 1 and reused["estimated_s"] == before["estimated_s"] / 2
    assert t({"t": "finish"})["remaining_units"] == 1
    assert len(json.loads(path.read_text())["samples"]) == 5


def test_real_decode_failure_keeps_a_pending_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.dicom import convert

    from tests.test_dicom_resume import run_conversion
    from tools.dicom_fixtures import write_series

    source, output, history = tmp_path / "source", tmp_path / "derived", tmp_path / "history.json"
    write_series(source, shape=(3, 3, 3), marker=(1, 1, 2))

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("Synthetic decode failure")

    monkeypatch.setattr(convert, "write_nifti", fail)
    result = run_conversion(source, output, on_timing=timer(history))
    assert result.counts["failed"] == 1 and result.counts["converted"] == 0
    assert result.conversion_time["remaining_units"] == 1
    assert result.conversion_time["basis"] == "unknown"
    assert not history.exists()


@pytest.mark.parametrize(
    "damaged", ["{", '{"version":999,"samples":[]}', '{"version":1,"samples":[{}]}']
)
def test_unusable_history_is_unknown_and_is_not_overwritten(tmp_path: Path, damaged: str) -> None:
    path = tmp_path / "history.json"
    path.write_text(damaged)
    t = timer(path)
    assert plan(t, "native-regular")["basis"] == "unknown"
    t({"t": "unit", "id": "0", "seconds": 10})
    assert path.read_text() == damaged


def test_history_is_bounded_and_contains_no_source_or_patient_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "history.json"
    monkeypatch.setattr("app.tasks.dicom_eta.MAX_SAMPLES", 8)
    seed(path, n=20)
    stored = json.loads(path.read_text())
    assert len(stored["samples"]) <= 8
    assert all(set(s) == {"context", "class", "event", "rate"} for s in stored["samples"])
    assert all(
        len(s["event"]) == 64 and len(s["context"]) == 64 and len(s["class"]) == 64
        for s in stored["samples"]
    )


def test_advisory_history_batches_writes_and_flushes_when_the_last_unit_is_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tasks import dicom_eta

    path = tmp_path / "history.json"
    write = dicom_eta.atomic_write_json
    calls = []

    def observed_write(target: Path, value: Any) -> None:
        calls.append(len(value["samples"]))
        write(target, value)

    monkeypatch.setattr(dicom_eta, "atomic_write_json", observed_write)
    t = timer(path)
    plan(t, *(["native-regular"] * 20))
    for i in range(19):
        t({"t": "unit", "id": str(i), "seconds": 10})
        if i == 4:
            assert len(json.loads(path.read_text())["samples"]) == 5
    t({"t": "unit", "id": "19", "seconds": None})
    assert len(json.loads(path.read_text())["samples"]) == 19
    assert len(calls) <= 5  # A full history file must not be rewritten for every tiny series.


def test_regular_interruption_flushes_completed_samples_without_timing_unfinished_work(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.json"
    t = timer(path)
    plan(t, *(["native-regular"] * 20))
    for i in range(6):
        t({"t": "unit", "id": str(i), "seconds": 10})
    interrupted = t({"t": "finish"})
    assert interrupted["remaining_units"] == 14 and interrupted["basis"] == "history"
    assert len(json.loads(path.read_text())["samples"]) == 6


def test_storage_failure_keeps_committed_work_but_withdraws_the_eta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "history.json"
    seed(path)
    t = timer(path, attempt="disk-full")
    assert plan(t, "native-regular", "native-regular")["basis"] == "history"

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("synthetic ENOSPC")

    monkeypatch.setattr("app.tasks.dicom_eta.atomic_write_json", fail)
    result = t({"t": "unit", "id": "0", "seconds": 10})
    assert result["remaining_units"] == 1 and result["basis"] == "unknown"
    assert len(json.loads(path.read_text())["samples"]) == 5


def test_deterministic_holdout_reports_coverage_and_range_width(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    seed(path)
    prediction = plan(timer(path), "native-regular")
    held_out = [9, 10, 11, 12, 13]
    coverage = sum(
        prediction["lower_s"] <= actual <= prediction["upper_s"] for actual in held_out
    ) / len(held_out)
    mean_error = sum(abs(prediction["estimated_s"] - actual) / actual for actual in held_out) / len(
        held_out
    )
    width = prediction["upper_s"] - prediction["lower_s"]
    assert coverage >= 0.8 and mean_error < 0.2 and width / prediction["estimated_s"] < 1
    assert prediction["confidence"] == "low"  # This synthetic corpus cannot certify reference P06.


def test_prepared_commit_adoption_does_not_train_a_decode_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.dicom import commits, convert

    from tests.test_dicom_resume import run_conversion
    from tools.dicom_fixtures import write_series

    source, output, history = tmp_path / "source", tmp_path / "derived", tmp_path / "history.json"
    write_series(source, shape=(3, 3, 3), marker=(1, 1, 2))
    publish = commits._publish

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("Synthetic failure after prepared commit")

    monkeypatch.setattr(commits, "_publish", fail)
    first = run_conversion(source, output, on_timing=timer(history, attempt="failed-publication"))
    assert first.counts["failed"] == 1 and not history.exists()
    monkeypatch.setattr(commits, "_publish", publish)
    monkeypatch.setattr(convert, "write_nifti", fail)
    resumed = run_conversion(source, output, on_timing=timer(history, attempt="adoption"))
    assert resumed.counts["converted"] == 1 and resumed.counts["failed"] == 0
    assert not history.exists()


def test_real_commits_train_history_but_dry_run_and_verified_resume_do_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.dicom import convert
    from plugins.dicom.identity import Identity

    from tests.test_dicom_resume import digest, run_conversion
    from tools.dicom_fixtures import write_series

    source, output, history = tmp_path / "source", tmp_path / "derived", tmp_path / "history.json"
    for i in range(6):
        write_series(
            source / f"P{i}" / "series", patient_id=f"P{i}", shape=(3, 3, 3), marker=(1, 1, 2)
        )
    before = {p: digest(p) for p in source.rglob("*") if p.is_file()}
    forecasts = []
    t = timer(history, attempt="real-conversion")

    def observe(event: dict[str, Any]) -> dict[str, Any]:
        result = t(event)
        forecasts.append(result)
        return result

    completed = run_conversion(source, output, on_timing=observe)
    assert completed.counts["converted"] == 6
    assert any(f["basis"] == "history" and f["remaining_units"] == 1 for f in forecasts)
    samples = json.loads(history.read_text())["samples"]
    assert len(samples) == 6 and all(s["rate"] > 0 for s in samples)
    images = {p: (digest(p), p.stat().st_mtime_ns) for p in (output / "nifti").glob("*.nii.gz")}

    def no_pixels(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Estimate/resume must not decode pixels")

    monkeypatch.setattr(convert, "write_nifti", no_pixels)
    from plugins.dicom import pipeline

    dry = pipeline.run(
        source,
        pipeline.Settings(convert_excluded=True),
        Identity(),
        nifti_dir=output / "nifti",
        sidecar_dir=output / "sidecars",
        ref_rel="dataset",
        ref_alias="DERIVED",
        salt="test",
        previous=[],
        dry_run=True,
        on_timing=timer(history, attempt="dry-run"),
    )
    assert dry.conversion_time["basis"] == "history" and dry.conversion_time["sample_count"] == 6
    resumed = run_conversion(source, output, on_timing=timer(history, attempt="resume"))
    assert resumed.counts["already_converted"] == 6
    assert resumed.conversion_time["remaining_units"] == 0
    assert json.loads(history.read_text())["samples"] == samples
    assert images == {p: (digest(p), p.stat().st_mtime_ns) for p in images}
    assert before == {p: digest(p) for p in before}


@pytest.mark.parametrize("in_project", [False, True])
def test_owned_api_conversion_supplies_history_to_a_later_header_only_plan(
    tmp_path: Path, in_project: bool
) -> None:
    from tests.test_source_operation_conversion import prepared_operation
    from tests.test_source_operations_api import API, control, wait_operation

    with prepared_operation(tmp_path, in_project, series_count=6) as prepared:
        client, settings, source, _, record, request = prepared
        oid = record["operation_id"]
        assert record["estimate"]["conversion_time"]["basis"] == "unknown"
        response = client.post(f"{API}/{oid}/convert", json=request)
        assert response.status_code == 202, response.text
        completed = wait_operation(client, oid)
        assert completed["stage"] == "result", completed
        assert completed["conversion_run"]["conversion_time"]["basis"] == "complete"
        history = settings.workspace_root / "plugins" / "dicom" / "timing-history.json"
        assert len(json.loads(history.read_text())["samples"]) == 6
        response = client.post(
            API,
            json={
                "path": str(source),
                "project_id": record["project_id"],
                "idempotency_key": "historical-next-operation",
            },
        )
        assert response.status_code == 202, response.text
        next_id = response.json()["operation_id"]
        wait_operation(client, next_id)
        assert control(client, next_id, "estimate").status_code == 202
        estimated = wait_operation(client, next_id)["estimate"]
        assert estimated["conversion_time"]["basis"] == "history", estimated
        assert (
            estimated["basis"] == "sample"
        )  # Keep the existing estimate enum readable by older clients.
        assert estimated["conversion_time"]["sample_count"] == 6
        assert estimated["conversion_time"]["remaining_units"] == estimated["n_units"]
        assert len(json.loads(history.read_text())["samples"]) == 6
