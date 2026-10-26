"""D18-D23/D35: strong per-series commits, interruption and immutable outputs."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest
from plugins.dicom import convert, pipeline
from plugins.dicom.identity import Identity

from tools.dicom_fixtures import write_series


def run_conversion(source: Path, output: Path, **kwargs: Any) -> pipeline.Result:
    return pipeline.run(
        source,
        kwargs.pop("settings", pipeline.Settings(convert_excluded=True)),
        kwargs.pop("identity", Identity()),
        nifti_dir=output / "nifti",
        sidecar_dir=output / "sidecars",
        ref_rel="dataset",
        ref_alias="DERIVED",
        salt="test",
        previous=kwargs.pop("previous", []),
        dry_run=False,
        **kwargs,
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("mutation", ["input", "output", "sidecar", "settings"])
def test_resume_rejects_changed_artifacts_instead_of_existence_skip(
    tmp_path: Path, mutation: str
) -> None:
    source, output = tmp_path / "source", tmp_path / "derived"
    write_series(source / "series", shape=(3, 3, 3), marker=(1, 1, 2))
    first = run_conversion(source, output)
    assert first.counts["converted"] == 1
    image = next((output / "nifti").glob("*.nii.gz"))
    sidecar = next((output / "sidecars").glob("*.dicom.json"))
    settings = pipeline.Settings(convert_excluded=True)
    if mutation == "input":
        path = next(source.rglob("*.dcm"))
        stat = path.stat()
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif mutation == "output":
        image.write_bytes(b"corrupted image")
    elif mutation == "sidecar":
        sidecar.unlink()
    else:
        settings.anonymize = "basic"
    previous_bytes = image.read_bytes()
    resumed = run_conversion(source, output, settings=settings)
    assert resumed.counts["failed"] == 1
    assert resumed.counts["already_converted"] == 0
    assert "conflict" in resumed.rows[0].get("raw_metadata_error", "").lower()
    assert image.read_bytes() == previous_bytes


def test_resume_preserves_completed_hashes_and_restarts_pending_series(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "derived"
    for index in range(3):
        write_series(
            source / f"P{index}" / "series",
            patient_id=f"P{index}",
            shape=(3, 3, 3),
            marker=(1, 1, 2),
        )
    identity = Identity()
    committed = 0

    def completed(*_: Any) -> None:
        nonlocal committed
        committed += 1

    partial = run_conversion(
        source, output, identity=identity, cancelled=lambda: committed >= 1, progress=completed
    )
    assert partial.counts["converted"] == 1
    image = next((output / "nifti").glob("*.nii.gz"))
    before = (digest(image), image.stat().st_mtime_ns)
    resumed = run_conversion(source, output, identity=identity)
    assert resumed.counts["already_converted"] == 1 and resumed.counts["converted"] == 2
    assert (digest(image), image.stat().st_mtime_ns) == before
    uninterrupted = run_conversion(source, tmp_path / "other-derived")
    assert {r["filename"] for r in resumed.rows} == {r["filename"] for r in uninterrupted.rows}
    for path in (output / "nifti").glob("*.nii.gz"):
        assert digest(path) == digest(tmp_path / "other-derived" / "nifti" / path.name)


def test_resume_does_not_trust_an_unjournaled_existing_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "source", tmp_path / "derived"
    write_series(source / "series", shape=(3, 3, 3), marker=(1, 1, 2))
    plan = run_conversion(source, output)
    checkpoints = output / "nifti" / ".checkpoints"
    assert checkpoints.is_dir()
    import shutil

    shutil.rmtree(checkpoints)
    image = next((output / "nifti").glob("*.nii.gz"))
    before = digest(image)
    resumed = run_conversion(source, output)
    assert resumed.counts["failed"] == 1 and resumed.counts["already_converted"] == 0
    assert image.exists() and digest(image) == before
    assert plan.counts["converted"] == 1


@pytest.mark.parametrize("barrier", ["sidecar_publication", "commit_record"])
def test_recovery_finishes_prepared_artifacts_without_decoding_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, barrier: str
) -> None:
    """D18/D35: crash between image, sidecar and journal publication is recoverable."""
    from plugins.dicom import commits

    source, output = tmp_path / "source", tmp_path / "derived"
    write_series(source / "series", shape=(3, 3, 3), marker=(1, 1, 2))
    original_link, original_write = os.link, commits._write
    failed_once = False

    def fail_sidecar(src: Any, dst: Any, **kwargs: Any) -> None:
        nonlocal failed_once
        if not failed_once and Path(dst).parent == output / "sidecars":
            failed_once = True
            raise OSError(28, "synthetic disk full")
        original_link(src, dst, **kwargs)

    def fail_commit(path: Path, record: dict[str, Any]) -> None:
        nonlocal failed_once
        if not failed_once and record["status"] == "committed":
            failed_once = True
            raise OSError(28, "synthetic disk full")
        original_write(path, record)

    monkeypatch.setattr(os, "link", fail_sidecar)
    if barrier == "commit_record":
        monkeypatch.setattr(os, "link", original_link)
        monkeypatch.setattr(commits, "_write", fail_commit)
    failed = run_conversion(source, output)
    assert failed_once and failed.counts["failed"] == 1
    image = next((output / "nifti").glob("*.nii.gz"))
    before = digest(image), image.stat().st_mtime_ns

    def no_pixels(*_: Any, **__: Any) -> Any:
        raise AssertionError("Recover a prepared commit without another pixel conversion")

    monkeypatch.setattr(convert, "write_nifti", no_pixels)
    resumed = run_conversion(source, output)
    assert resumed.counts["failed"] == 0 and resumed.counts["converted"] == 1
    assert (digest(image), image.stat().st_mtime_ns) == before
    assert len(list((output / "sidecars").glob("*.dicom.json"))) == 1
    verified = run_conversion(source, output)
    assert verified.counts["already_converted"] == 1


def test_same_run_pins_pending_input_and_registry_before_the_first_pixel_unit(
    tmp_path: Path,
) -> None:
    """D11/D19/D21: interruption cannot silently admit a changed not-yet-converted input."""
    from plugins.dicom.commits import CommitConflict

    source, output = tmp_path / "source", tmp_path / "derived"
    for index in range(2):
        write_series(
            source / f"P{index}", patient_id=f"P{index}", shape=(3, 3, 3), marker=(1, 1, 2)
        )
    checkpoint = output / "run" / "pin.json"
    committed = 0

    def completed(*_: Any) -> None:
        nonlocal committed
        committed += 1

    partial = run_conversion(
        source, output, checkpoint=checkpoint, progress=completed, cancelled=lambda: committed == 1
    )
    assert partial.counts["converted"] == 1 and checkpoint.exists()
    image = next((output / "nifti").glob("*.nii.gz"))
    before = digest(image)
    file = next((source / "P1").glob("*.dcm"))
    original, stat = file.read_bytes(), file.stat()
    data = bytearray(original)
    data[-1] ^= 1
    file.write_bytes(data)
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(CommitConflict, match="conflict"):
        run_conversion(source, output, checkpoint=checkpoint)
    assert digest(image) == before and len(list((output / "nifti").glob("*.nii.gz"))) == 1
    file.write_bytes(original)
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    fresh_identity = Identity()
    resumed = run_conversion(source, output, checkpoint=checkpoint, identity=fresh_identity)
    assert resumed.counts["already_converted"] == 1 and resumed.counts["converted"] == 1
    assert fresh_identity.cases == {"P0": 0, "P1": 1}
    write_series(source / "P2", patient_id="P2", shape=(3, 3, 3), marker=(1, 1, 2))
    with pytest.raises(CommitConflict, match="conflict"):
        run_conversion(source, output, checkpoint=checkpoint)


@pytest.mark.parametrize("in_project", [False, True])
def test_dicom_conversion_and_estimate_use_owned_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, in_project: bool
) -> None:
    """BE-16/D17: source tasks never run native DICOM work in the shared executor."""
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.jobs.manager import JobManager
    from app.main import create_app
    from app.tasks.builtin import run_entry
    from tests.test_api_ingest import wait

    source, output = tmp_path / "source", tmp_path / "derived"
    write_series(source / "P0" / "series")
    output.mkdir()
    original = JobManager.run_in_worker

    async def reject_shared_dicom(self: Any, fn: Any, *args: Any) -> Any:
        if fn is run_entry and args[0] == "plugins.dicom.task:run":
            raise AssertionError("DICOM was dispatched to the shared worker pool")
        return await original(self, fn, *args)

    monkeypatch.setattr(JobManager, "run_in_worker", reject_shared_dicom)
    settings = Settings(
        dicom_memory_mb=1024,
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        allowed_derived_roots=str(output),
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        prefix = "/api/v1"
        if in_project:
            pid = client.post(prefix + "/projects", json={"name": "Owned", "packs": []}).json()[
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
        estimated = client.post(
            prefix + "/tasks/dicom.convert/estimate", json={"selection": {"source": str(source)}}
        )
        assert estimated.status_code == 200, estimated.text
        assert estimated.json()["n_units"] == 1
        started = client.post(
            prefix + "/task-runs",
            json={"task_id": "dicom.convert", "selection": {"source": str(source)}},
        )
        assert started.status_code == 202, started.text
        wait(client, started.json()["job_id"])
        result = client.get(prefix + "/task-runs/" + started.json()["run_id"]).json()
        assert result["status"] == "completed", result


@pytest.mark.parametrize("in_project", [False, True])
def test_api_resume_reuses_run_and_output_and_keeps_completed_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, in_project: bool
) -> None:
    """D19/D20/D24: an actual native process resumes the same API run in both contexts."""
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.core.fsio import read_json
    from app.main import create_app
    from app.tasks import driver, workspace_runs
    from tests.test_api_ingest import wait

    source, output = tmp_path / "source", tmp_path / "derived"
    for n in range(2):
        write_series(source / f"P{n}" / "series", patient_id=f"P{n}")
    output.mkdir()
    original = driver.run_dicom_job
    obstruction: Path | None = None

    async def fail_once(job: Path, **kwargs: Any) -> dict[str, Any]:
        nonlocal obstruction
        if obstruction is None:

            def before_dispatch(_: int) -> None:
                nonlocal obstruction
                dataset = Path(read_json(job / "job.json")["dataset_dir"])
                obstruction = dataset / "nifti/01_CT_case_00001_0000.nii.gz"
                obstruction.parent.mkdir(parents=True, exist_ok=True)
                obstruction.write_bytes(b"unexpected existing artifact")

            kwargs["on_started"] = before_dispatch
        return await original(job, **kwargs)

    monkeypatch.setattr(driver, "run_dicom_job", fail_once)
    monkeypatch.setattr(workspace_runs, "run_dicom_job", fail_once)
    settings = Settings(
        dicom_memory_mb=1024,
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        allowed_derived_roots=str(output),
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        prefix = "/api/v1"
        pid = None
        if in_project:
            pid = client.post(prefix + "/projects", json={"name": "Resume", "packs": []}).json()[
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
        started = client.post(
            prefix + "/task-runs",
            json={
                "task_id": "dicom.convert",
                "name": "resume-demo",
                "selection": {"source": str(source)},
            },
        )
        assert started.status_code == 202, started.text
        rid = started.json()["run_id"]
        wait(client, started.json()["job_id"])
        partial = client.get(prefix + "/task-runs/" + rid).json()
        assert partial["status"] == "completed_with_errors", partial
        assert obstruction is not None
        dataset = obstruction.parent.parent
        assert not (dataset / "dataset.json").exists()
        completed = dataset / "nifti/01_CT_case_00000_0000.nii.gz"
        before = digest(completed), completed.stat().st_mtime_ns
        obstruction.unlink()  # remove the test's unrelated obstruction; never change the inputs
        resumed = client.post(prefix + "/task-runs/" + rid + "/resume")
        assert resumed.status_code == 202, resumed.text
        assert (
            resumed.json()["run_id"] == rid and resumed.json()["job_id"] != started.json()["job_id"]
        )
        wait(client, resumed.json()["job_id"])
        finished = client.get(prefix + "/task-runs/" + rid).json()
        assert finished["status"] == "completed", finished
        assert (digest(completed), completed.stat().st_mtime_ns) == before
        assert len(list(dataset.glob("nifti/*.nii.gz"))) == 2
        if in_project:
            assert finished["output_dir"] == partial["output_dir"]
            imports = [o for o in finished["outputs"] if o["kind"] == "import"]
            assert len({o["ref"] for o in imports}) == 1
        else:
            assert finished["dataset_dir"] == partial["dataset_dir"] == str(dataset)
            assert (dataset / "dataset.json").is_file()
            assert sorted(p.name for p in (output / "_datasets").iterdir()) == ["resume-demo"]
        assert client.post(prefix + "/task-runs/" + rid + "/resume").status_code == 409


def test_fresh_pinned_conversion_hashes_sources_twice_and_reuses_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections import Counter

    from plugins.dicom import commits

    source = tmp_path / "source"
    write_series(source, seed="preflight-read-count")
    output = tmp_path / "derived"
    inputs = sorted(source.glob("*.dcm"))
    reads: Counter[Path] = Counter()
    original = commits.file_digest

    def measured(path: Path, root: Path | None = None) -> dict[str, Any]:
        if path.is_relative_to(source):
            reads[path] += 1
        return original(path, root)

    monkeypatch.setattr(commits, "file_digest", measured)
    result = run_conversion(source, output, checkpoint=output / "pin.json")
    assert result.counts["converted"] == 1
    assert reads == Counter({path: 2 for path in inputs})
    hashes = {path: digest(path) for path in (output / "nifti").glob("*.nii.gz")}
    reads.clear()
    resumed = run_conversion(source, output, checkpoint=output / "pin.json")
    assert resumed.counts["already_converted"] == 1
    assert reads == Counter({path: 2 for path in inputs})
    assert hashes == {path: digest(path) for path in hashes}


@pytest.mark.parametrize("already_committed", [False, True])
def test_input_change_after_run_preflight_cannot_be_committed_or_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, already_committed: bool
) -> None:
    import pydicom
    from plugins.dicom import commits

    source = tmp_path / "source"
    write_series(source, seed="preflight-mutation")
    output = tmp_path / "derived"
    checkpoint = output / "pin.json"
    if already_committed:
        assert run_conversion(source, output, checkpoint=checkpoint).counts["converted"] == 1
    committed = {p: digest(p) for p in (output / "nifti").glob("*.nii.gz")}
    original = commits.pin_run

    def change_after_pin(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        path = next(source.glob("*.dcm"))
        ds = pydicom.dcmread(path)
        ds.PatientName = "SYNTHETIC EXTERNAL CHANGE"
        ds.save_as(path, enforce_file_format=True)

    monkeypatch.setattr(commits, "pin_run", change_after_pin)
    result = run_conversion(source, output, checkpoint=checkpoint)
    assert result.counts["failed"] == 1
    assert not result.counts["converted"] and not result.counts["already_converted"]
    assert committed == {p: digest(p) for p in (output / "nifti").glob("*.nii.gz")}
