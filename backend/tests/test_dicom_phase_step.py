"""D29: phase rules run after native commits, with an independent metadata checkpoint."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from plugins.analyzers import phase
from plugins.dicom import pipeline, task
from plugins.dicom.identity import Identity

from app.tasks import protocol
from tools.dicom_fixtures import write_series


def no_phase(*_: Any, **__: Any) -> Any:
    raise AssertionError("Phase must not run inside core conversion or Estimate")


@pytest.mark.parametrize("dry_run", [True, False])
def test_core_conversion_never_infers_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    source = tmp_path / "source"
    write_series(source)
    monkeypatch.setattr(phase, "guess", no_phase)
    monkeypatch.setattr(phase, "analyze", no_phase)
    result = pipeline.run(
        source,
        pipeline.Settings(),
        Identity(),
        nifti_dir=tmp_path / "derived" / "nifti",
        sidecar_dir=tmp_path / "derived" / "sidecars",
        ref_rel="",
        ref_alias="DATA",
        salt="",
        previous=[],
        dry_run=dry_run,
    )
    assert not result.counts["failed"]
    assert result.counts["selected"] == 1
    assert "phase" not in {a["field"] for a in result.annotations}


def make_job(tmp_path: Path, **settings: Any) -> Path:
    source = tmp_path / "source"
    write_series(
        source,
        description="ABDOMEN" if settings.get("anonymize") == "basic" else "NEPHROGRAPHIC ABDOMEN",
        extra={"ProtocolName": "NEPHROGRAPHIC PROTOCOL"},
    )
    job = tmp_path / "workspace" / "attempt"
    protocol.write_job(
        job,
        {
            "source": {"path": str(source)},
            "output_dir": str(tmp_path / "derived"),
            "dataset_dir": str(tmp_path / "derived"),
            "settings": settings,
            "run_id": "synthetic-conversion",
            "workspace": True,
            "context": {"phase_vocabulary": ["NC", "CMP", "NP", "EP", "UNK"]},
        },
    )
    return job


def test_disabled_phase_never_calls_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = make_job(tmp_path, phase_analyzer=False)
    monkeypatch.setattr(phase, "guess", no_phase)
    monkeypatch.setattr(phase, "analyze", no_phase)
    assert task.run(str(job)) == 0
    assert protocol.read_result(job)["status"] == "completed"  # type: ignore[index]
    assert not (job / "phase-analyzer").exists()


def test_phase_checkpoint_io_failure_leaves_conversion_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D29: failure to persist analyzer state does not invalidate committed image outputs."""
    from plugins.analyzers import checkpoint

    job = make_job(tmp_path)

    def unavailable(*_: Any, **__: Any) -> Any:
        raise OSError("synthetic analyzer-state filesystem outage")

    monkeypatch.setattr(checkpoint, "analyze_phase", unavailable)
    assert task.run(str(job)) == 0
    result = protocol.read_result(job)
    assert result is not None and result["status"] == "completed"
    assert result["provenance"]["phase_analyzer"]["status"] == "failed"
    assert result["provenance"]["phase_analyzer"]["total"] == 1
    assert (tmp_path / "derived/dataset.json").is_file()
    assert len(list((tmp_path / "derived/nifti").glob("*.nii.gz"))) == 1


def test_cancelling_only_phase_does_not_cancel_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D29: the analyzer's cancellation flag is independent of the native conversion flag."""
    job = make_job(tmp_path)
    spec = json.loads((job / protocol.JOB).read_text())
    phase_cancel = tmp_path / "workspace/phase-run"
    phase_cancel.mkdir(parents=True)
    protocol.request_cancel(phase_cancel)
    spec["phase_cancel"] = str(phase_cancel / protocol.CANCEL)
    protocol.write_job(job, spec)
    monkeypatch.setattr(phase, "analyze", no_phase)
    assert task.run(str(job)) == 0
    result = protocol.read_result(job)
    assert result is not None and result["status"] == "completed"
    assert result["provenance"]["phase_analyzer"]["status"] == "cancelled"
    assert (tmp_path / "derived/dataset.json").is_file()
    assert not (job / protocol.CANCEL).exists()


def test_phase_runs_only_after_commits_and_before_basic_facts_are_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = make_job(tmp_path, anonymize="basic")
    original = phase.analyze

    def after_commits(rows: Any, config: Any) -> Any:
        assert len(list((tmp_path / "derived" / "nifti").glob("*.nii.gz"))) == 1
        committed = list((tmp_path / "derived" / "nifti").glob(".checkpoints/*/commit.json"))
        assert len(committed) == 1 and json.loads(committed[0].read_text())["status"] == "committed"
        assert rows[0]["protocol_name"] == "NEPHROGRAPHIC PROTOCOL"
        return original(rows, config)

    monkeypatch.setattr(phase, "analyze", after_commits)
    assert task.run(str(job)) == 0
    result = protocol.read_result(job)
    assert result is not None and result["status"] == "completed"
    annotation_rows = [
        json.loads(line) for line in (job / "annotations.jsonl").read_text().splitlines()
    ]
    assert next(a for a in annotation_rows if a["field"] == "phase")["value"] == "NP"
    assert "NEPHROGRAPHIC PROTOCOL" not in (tmp_path / "derived" / "metadata.jsonl").read_text()
    assert not list((tmp_path / "derived").rglob("inputs.json"))
    assert result["provenance"]["phase_analyzer"]["status"] == "completed"


def test_failed_phase_retry_never_reconverts_or_changes_sealed_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = make_job(tmp_path)
    original = phase.analyze

    def unavailable(*_: Any) -> Any:
        raise RuntimeError("synthetic analyzer outage")

    monkeypatch.setattr(phase, "analyze", unavailable)
    assert task.run(str(job)) == 0
    result = protocol.read_result(job)
    assert result is not None and result["status"] == "completed"
    assert result["provenance"]["phase_analyzer"]["status"] == "failed"
    dataset = tmp_path / "derived"
    before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in dataset.rglob("*")
        if p.is_file()
    }
    monkeypatch.setattr(phase, "analyze", original)
    from plugins.analyzers.checkpoint import retry_phase

    retried = retry_phase(job / "phase-analyzer")
    assert retried["status"] == "completed" and retried["attempt"] == 2
    assert before == {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in dataset.rglob("*")
        if p.is_file()
    }


def test_analyzer_checkpoint_resumes_batches_and_refuses_incompatible_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.analyzers.checkpoint import AnalysisConflict, analyze_phase, retry_phase

    rows = [{"item_id": str(i), "series_description": "NONCONTRAST"} for i in range(130)]
    state = tmp_path / "workspace" / "phase"
    calls = []
    original = phase.analyze

    def tracked(batch: Any, config: Any) -> Any:
        calls.extend(row["item_id"] for row in batch)
        return original(batch, config)

    monkeypatch.setattr(phase, "analyze", tracked)
    partial = analyze_phase(state, rows, {}, cancelled=lambda: len(calls) >= 64)
    assert partial["status"] == "cancelled"
    assert partial["done"] == 64 and partial["total"] == 130
    assert retry_phase(state)["status"] == "completed"
    assert calls == [str(i) for i in range(130)]
    monkeypatch.setattr(phase, "RULES_VERSION", "new-rules")
    with pytest.raises(AnalysisConflict, match="rules"):
        retry_phase(state)


def test_analyzer_survives_abrupt_process_exit_without_repeating_committed_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.analyzers.checkpoint import retry_phase

    state = tmp_path / "workspace" / "phase"
    code = """
import os
import sys
from pathlib import Path
from plugins.analyzers import phase
from plugins.analyzers.checkpoint import analyze_phase
original = phase.analyze
def crash(batch, config):
    if batch[0]['item_id'] == '64':
        os._exit(39)
    return original(batch, config)
phase.analyze = crash
rows = [{'item_id': str(i), 'series_description': 'NONCONTRAST'} for i in range(130)]
analyze_phase(Path(sys.argv[1]), rows, {})
"""
    crashed = subprocess.run(
        [sys.executable, "-c", code, str(state)],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        check=False,
        timeout=15,
    )
    assert crashed.returncode == 39
    calls = []
    original = phase.analyze

    def tracked(batch: Any, config: Any) -> Any:
        calls.extend(row["item_id"] for row in batch)
        return original(batch, config)

    monkeypatch.setattr(phase, "analyze", tracked)
    completed = retry_phase(state)
    assert completed["status"] == "completed" and completed["attempt"] == 2
    assert calls == [str(i) for i in range(64, 130)]


def test_analyzer_reuse_ignores_conversion_outcome_but_detects_annotation_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.analyzers.checkpoint import AnalysisConflict, analyze_phase, retry_phase

    state = tmp_path / "workspace" / "phase"
    rows = [
        {
            "item_id": "case.01.complete.-",
            "series_description": "NONCONTRAST",
            "status": "converted",
        }
    ]
    assert analyze_phase(state, rows, {})["status"] == "completed"
    rows[0]["status"] = "already_converted"
    monkeypatch.setattr(phase, "analyze", no_phase)
    assert analyze_phase(state, rows, {})["status"] == "completed"
    checkpoint = state / "batch-0.json"
    checkpoint.write_text("[]")
    with pytest.raises(AnalysisConflict, match="annotations changed"):
        retry_phase(state)
    assert checkpoint.read_text() == "[]"


@pytest.mark.parametrize(
    "field,value", [("batches", []), ("attempt", "bad"), ("status", "unknown")]
)
def test_corrupt_analyzer_records_return_a_conflict(tmp_path: Path, field: str, value: Any) -> None:
    from plugins.analyzers.checkpoint import AnalysisConflict, analyze_phase, retry_phase

    state = tmp_path / "workspace" / "phase"
    analyze_phase(state, [{"item_id": "1", "series_description": "NONCONTRAST"}], {})
    path = state / "checkpoint.json"
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    with pytest.raises(AnalysisConflict):
        retry_phase(state)


def test_completed_analysis_is_idempotent_and_cannot_be_cancelled_retroactively(
    tmp_path: Path,
) -> None:
    from plugins.analyzers.checkpoint import analyze_phase, retry_phase

    state = tmp_path / "workspace" / "phase"
    first = analyze_phase(state, [{"item_id": "1", "series_description": "NONCONTRAST"}], {})
    before = {p.name: p.read_bytes() for p in state.iterdir() if p.is_file()}
    second = retry_phase(state, cancelled=lambda: True)
    assert second == first
    assert {p.name: p.read_bytes() for p in state.iterdir() if p.is_file()} == before


def test_recovery_seed_restores_missing_inputs_and_reuses_committed_phase_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D29: recovery needs only private metadata, including before anonymization."""
    from plugins.analyzers.checkpoint import analyze_phase, retry_phase, write_seed

    rows = [
        {"item_id": str(i), "series_description": "NONCONTRAST", "patient_id": "omit-me"}
        for i in range(130)
    ]
    seed_dir, state = tmp_path / "private-seed", tmp_path / "phase"
    seed = write_seed(seed_dir, rows, {})
    seed_path = seed_dir / "seed.json"
    assert seed_dir.stat().st_mode & 0o077 == 0
    assert "omit-me" not in seed_path.read_text()
    stopped = False

    def progress(done: int, total: int) -> None:
        nonlocal stopped
        stopped = done >= 64

    assert (
        analyze_phase(state, rows, {}, cancelled=lambda: stopped, on_progress=progress)["done"]
        == 64
    )
    (state / "inputs.json").unlink()
    calls = []
    original = phase.analyze

    def tracked(batch: Any, config: Any) -> Any:
        calls.extend(row["item_id"] for row in batch)
        return original(batch, config)

    monkeypatch.setattr(phase, "analyze", tracked)
    recovered = retry_phase(state, seed=seed_path, seed_sha256=seed["sha256"])
    assert recovered["status"] == "completed" and recovered["done"] == 130
    assert calls == [str(i) for i in range(64, 130)]


@pytest.mark.parametrize("conflict", ["content", "rules", "checkpoint"])
def test_invalid_recovery_seed_preserves_the_original_phase_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conflict: str
) -> None:
    """D29: a recovery seed cannot bypass content, rules or checkpoint identity pins."""
    from plugins.analyzers.checkpoint import (
        AnalysisConflict,
        analyze_phase,
        retry_phase,
        write_seed,
    )

    state, seed_dir = tmp_path / "phase", tmp_path / "private-seed"
    rows = [{"item_id": "1", "series_description": "NONCONTRAST"}]
    analyze_phase(state, rows, {})
    (state / "inputs.json").unlink()
    original_checkpoint = (state / "checkpoint.json").read_bytes()
    seed = write_seed(
        seed_dir, [{**rows[0], "item_id": "other"}] if conflict == "checkpoint" else rows, {}
    )
    seed_path = seed_dir / "seed.json"
    if conflict == "content":
        seed_path.write_text("{}")
    elif conflict == "rules":
        monkeypatch.setattr(phase, "RULES_VERSION", "incompatible-rules")
    monkeypatch.setattr(phase, "analyze", no_phase)
    with pytest.raises(AnalysisConflict):
        retry_phase(state, seed=seed_path, seed_sha256=seed["sha256"])
    assert (state / "checkpoint.json").read_bytes() == original_checkpoint
    assert not (state / "inputs.json").exists()
