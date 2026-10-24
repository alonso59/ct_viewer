"""D34/DCM-09/17: the YAML CLI resumes the pinned run and preserves committed images."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
from plugins.dicom import cli, convert

from tools.dicom_fixtures import MARKER, write_series


def contents(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def configured(tmp_path: Path) -> tuple[Path, Path, Path]:
    source, out = tmp_path / "source", tmp_path / "derived"
    for patient in ("P001", "P002"):
        write_series(source / patient, patient_id=patient, shape=(5, 4, 12), marker=(2, 1, 3))
    config = tmp_path / "converter.yaml"
    config.write_text(f"dataset_root: {source}\noutput_root: {out}\n")
    return source, out, config


def interrupted_cli(config: Path, marker: Path, *, stop: bool = False) -> subprocess.Popen[str]:
    code = """
import os, signal, sys
from pathlib import Path
from plugins.dicom import cli
original = cli.pipeline.run
def interrupted(*args, **kwargs):
    def committed(item_id, status, outputs, message):
        if status == 'ok':
            Path(sys.argv[2]).write_text(item_id)
            os.kill(os.getpid(), signal.SIGSTOP if sys.argv[3] == 'stop' else signal.SIGKILL)
    kwargs['progress'] = committed
    return original(*args, **kwargs)
cli.pipeline.run = interrupted
raise SystemExit(cli.main([sys.argv[1]]))
"""
    return subprocess.Popen(
        [sys.executable, "-c", code, str(config), str(marker), "stop" if stop else "kill"],
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(sys.path),
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS": "1",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.mark.parametrize("change_source", ["none", "added", "replaced", "settings"])
def test_cli_after_sigkill_preserves_commits_and_refuses_an_added_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change_source: str
) -> None:
    source, out, config = configured(tmp_path)
    before_source = contents(source)
    crashed = interrupted_cli(config, tmp_path / "committed")
    _, error = crashed.communicate(timeout=15)
    assert crashed.returncode == -signal.SIGKILL, error
    committed = contents(out / "nifti")
    images = sorted((out / "nifti").glob("*.nii.gz"))
    assert len(images) == 1
    original_image = images[0]
    first_bytes, first_mtime = original_image.read_bytes(), original_image.stat().st_mtime_ns
    written = []
    original = convert.write_nifti

    def tracked(series: Any, path: Path) -> Any:
        written.append(str(path))
        return original(series, path)

    monkeypatch.setattr(convert, "write_nifti", tracked)
    if change_source != "none":
        if change_source == "added":
            write_series(source / "added", patient_id="P000", shape=(5, 4, 12), marker=(2, 1, 3))
        elif change_source == "settings":
            config.write_text(config.read_text() + "outputs:\n  include_modality_prefix: false\n")
        else:
            path = sorted((source / "P002").glob("*"))[-1]
            before = path.stat()
            data = path.read_bytes()
            path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert cli.main([str(config)]) == 1
        assert not written
        # A refusal may update its control journal, but cannot publish or alter an image.
        assert contents(out / "nifti") == committed
        return
    assert cli.main([str(config)]) == 0
    assert len(written) == 1
    assert (
        original_image.read_bytes() == first_bytes
        and original_image.stat().st_mtime_ns == first_mtime
    )
    rows = [json.loads(line) for line in (out / "metadata.jsonl").read_text().splitlines()]
    assert len(rows) == 2 and {row["status"] for row in rows} <= {"converted", "already_converted"}
    assert len({(row["case_id"], row["scan_idx"]) for row in rows}) == 2
    for image in (out / "nifti").glob("*.nii.gz"):
        volume = nib.load(image)
        assert volume.shape == (5, 4, 12) and np.isfinite(volume.affine).all()
        marker = np.argwhere(volume.get_fdata() == MARKER)
        assert marker.shape == (1, 3)
        np.testing.assert_allclose(
            volume.affine @ [*marker[0], 1], [18.6, 29.1, 107.5, 1], atol=1e-4
        )
    assert contents(source) == before_source


def test_cli_completed_run_can_add_cases_without_reassigning_prior_ids(tmp_path: Path) -> None:
    source, out, config = configured(tmp_path)
    assert cli.main([str(config)]) == 0
    saved = contents(out / "nifti")
    registry = json.loads((out / ".rw_identity.json").read_text())
    write_series(source / "new", patient_id="P000", shape=(5, 4, 12), marker=(2, 1, 3))
    assert cli.main([str(config)]) == 0
    current = json.loads((out / ".rw_identity.json").read_text())
    assert all(current["cases"][key] == value for key, value in registry["cases"].items())
    assert current["cases"]["P000"] not in set(registry["cases"].values())
    assert all(contents(out / "nifti")[key] == value for key, value in saved.items())
    assert len(list((out / "nifti").glob("*.nii.gz"))) == 3


@pytest.mark.parametrize("existing_output", [False, True])
def test_cli_dry_run_never_writes_output_or_decodes_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_output: bool
) -> None:
    _source, out, config = configured(tmp_path)
    if existing_output:
        assert cli.main([str(config)]) == 0
    before = contents(out)
    config.write_text(config.read_text() + "mode: dry_run\n")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("CLI dry run must not decode pixels")

    monkeypatch.setattr(convert, "write_nifti", forbidden)
    assert cli.main([str(config)]) == 0
    assert contents(out) == before
    assert out.exists() is existing_output


@pytest.mark.parametrize(
    "defect", ["journal_version", "missing_pin", "corrupt_pin", "changed_identity"]
)
def test_cli_preserves_committed_artifacts_when_recovery_evidence_is_unusable(
    tmp_path: Path, defect: str
) -> None:
    source, out, config = configured(tmp_path)
    before_source = contents(source)
    crashed = interrupted_cli(config, tmp_path / "committed")
    _, error = crashed.communicate(timeout=15)
    assert crashed.returncode == -signal.SIGKILL, error
    journal = out / ".rw_active.json"
    record = json.loads(journal.read_text())
    pin = out / ".rw-runs" / record["run_id"] / "pin.json"
    if defect == "journal_version":
        record["version"] = 999
        journal.write_text(json.dumps(record))
    elif defect == "missing_pin":
        pin.unlink()
    elif defect == "changed_identity":
        frozen = json.loads(pin.read_text())
        frozen["identity"]["cases"]["P001"] = 90
        pin.write_text(json.dumps(frozen))
    else:
        pin.write_text("{}")
    before = contents(out / "nifti"), contents(out / "sidecars")
    assert cli.main([str(config)]) == 1
    assert (contents(out / "nifti"), contents(out / "sidecars")) == before
    assert contents(source) == before_source


def test_cli_keeps_custom_yaml_output_names_and_clean_contract_rows(tmp_path: Path) -> None:
    _, out, config = configured(tmp_path)
    config.write_text(
        config.read_text() + "outputs:\n  nifti_dir: images\n  metadata_file: tables/rows.jsonl\n"
        "  include_modality_prefix: false\n"
    )
    assert cli.main([str(config)]) == 0
    rows = [json.loads(line) for line in (out / "tables/rows.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert all(row["relative_path"].startswith("images/01_case_") for row in rows)
    assert all((out / row["relative_path"]).is_file() for row in rows)
    assert all("phase_guess" not in row and "curated_phase" not in row for row in rows)


@pytest.mark.parametrize("invalid_yaml", [False, True])
def test_cli_configuration_errors_do_not_log_patient_paths_or_yaml_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], invalid_yaml: bool
) -> None:
    """NFR-17: CLI failure messages omit filesystem names and configuration contents."""
    config = tmp_path / "SYNTHETIC_PRIVATE_NAME.yaml"
    if invalid_yaml:
        config.write_text("dataset_root: [SYNTHETIC_PRIVATE_NAME\n")
    assert cli.main([str(config)]) == 1
    error = capsys.readouterr().err
    assert "SYNTHETIC_PRIVATE_NAME" not in error and str(tmp_path) not in error
    assert error.startswith("Conversion refused:")


def test_two_cli_processes_cannot_write_the_same_output_root(tmp_path: Path) -> None:
    source, out, config = configured(tmp_path)
    before_source = contents(source)
    marker = tmp_path / "first-commit"
    first = interrupted_cli(config, marker, stop=True)
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline and first.poll() is None:
            time.sleep(0.02)
        assert marker.exists()
        before = contents(out)
        assert cli.main([str(config)]) == 1
        assert contents(out) == before
    finally:
        if first.poll() is None:
            first.kill()
        first.communicate(timeout=5)
    assert contents(source) == before_source


def test_cli_reports_failed_series_and_can_retry_them_without_overwriting_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, out, config = configured(tmp_path)
    before_source = contents(source)
    original = convert.write_nifti
    calls = 0

    def unavailable(series: Any, path: Path) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("Synthetic unavailable decoder")
        return original(series, path)

    monkeypatch.setattr(convert, "write_nifti", unavailable)
    assert cli.main([str(config)]) == 1
    [committed] = list((out / "nifti").glob("*.nii.gz"))
    saved = committed.read_bytes(), committed.stat().st_mtime_ns
    monkeypatch.setattr(convert, "write_nifti", original)
    assert cli.main([str(config)]) == 0
    assert (committed.read_bytes(), committed.stat().st_mtime_ns) == saved
    assert len(list((out / "nifti").glob("*.nii.gz"))) == 2
    assert contents(source) == before_source


def test_cli_recovers_when_plan_digest_read_fails_before_the_first_pixel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D35: unsuccessful plan verification cannot acknowledge pixel dispatch."""
    _, out, config = configured(tmp_path)
    original = cli.commits.file_digest

    def unavailable(path: Path, root: Path | None = None) -> dict[str, Any]:
        if path.name == "pin.json":
            raise OSError("Synthetic plan read failure")
        return original(path, root)

    monkeypatch.setattr(cli.commits, "file_digest", unavailable)
    assert cli.main([str(config)]) == 1
    assert not list((out / "nifti").glob("*.nii.gz"))
    monkeypatch.setattr(cli.commits, "file_digest", original)
    assert cli.main([str(config)]) == 0
    assert len(list((out / "nifti").glob("*.nii.gz"))) == 2


@pytest.mark.parametrize("bad_output", ["overlap", "metadata", "metadata_root", "nifti"])
def test_cli_rejects_source_and_output_escape_before_entering_the_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_output: str
) -> None:
    source, out, config = configured(tmp_path)
    if bad_output == "overlap":
        config.write_text(f"dataset_root: {source}\noutput_root: {source}\n")
    else:
        key = "metadata_file" if bad_output.startswith("metadata") else "nifti_dir"
        value = "." if bad_output == "metadata_root" else "../source"
        config.write_text(
            f"dataset_root: {source}\noutput_root: {out}\noutputs:\n  {key}: {value}\n"
        )
    before = contents(source)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Invalid CLI destinations must be refused before discovery or output writes")

    monkeypatch.setattr(cli.pipeline, "run", forbidden)
    assert cli.main([str(config)]) == 1
    assert contents(source) == before
    assert not out.exists()
