"""D18/D19/D23/D35: actual worker death at native publication barriers and verified recovery."""

from __future__ import annotations

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
from plugins.dicom import commits, convert, sidecar

from tests.test_dicom_resume import digest, run_conversion
from tools.dicom_fixtures import MARKER, write_series


def native_writer_child(job: Path, point: float) -> None:
    from app.core.fsio import atomic_write_json
    from app.tasks.dicom_worker import main

    original = convert.write_nifti

    def convert_at_barrier(series: Any, output: Path, **kwargs: Any) -> Any:
        import SimpleITK as sitk

        if series.dicom_dir.name != "P1":
            return original(series, output, **kwargs)

        def write(image: Any, filename: str, compression: bool) -> None:
            writer = sitk.ImageFileWriter()
            writer.SetFileName(filename)
            writer.SetUseCompression(compression)

            def progress() -> None:
                if writer.GetProgress() == point:
                    atomic_write_json(
                        job / "native-writer-barrier.json",
                        {"pid": os.getpid(), "progress": point, "temporary": filename},
                    )
                    os.kill(os.getpid(), signal.SIGSTOP)

            writer.AddCommand(sitk.sitkProgressEvent, progress)
            writer.Execute(image)

        sitk.WriteImage = write
        return original(series, output, **kwargs)

    convert.write_nifti = convert_at_barrier
    raise SystemExit(main(job))


def native_api_child(root: Path, in_project: bool, point: float) -> None:
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.core.fsio import atomic_write_json
    from app.main import create_app
    from app.tasks import dicom_process
    from tests.test_api_ingest import wait
    from tests.test_source_operation_conversion import native_run
    from tests.test_source_operations_api import API, wait_operation

    original = dicom_process.asyncio.create_subprocess_exec
    code = (
        "import sys; from pathlib import Path; "
        "from tests.test_dicom_operation_recovery import native_writer_child; "
        "native_writer_child(Path(sys.argv[1]), float(sys.argv[2]))"
    )

    async def launch(*args: Any, **kwargs: Any) -> Any:
        if args[1:3] == ("-m", "app.tasks.dicom_worker"):
            return await original(args[0], "-c", code, args[3], str(point), **kwargs)
        return await original(*args, **kwargs)

    dicom_process.asyncio.create_subprocess_exec = launch
    settings = Settings(
        workspace_root=root / "workspace",
        allowed_data_roots=str(root / "source"),
        allowed_derived_roots=str(root / "derived"),
        dicom_memory_mb=1024,
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        pid = None
        if in_project:
            pid = client.post(
                "/api/v1/projects", json={"name": "Native crash", "packs": []}
            ).json()["project_id"]
            response = client.put(
                f"/api/v1/projects/{pid}/roots/DERIVED",
                json={"path": str(root / "derived"), "role": "derived"},
            )
            assert response.status_code == 200, response.text
        response = client.post(
            API,
            json={
                "path": str(root / "source"),
                "project_id": pid,
                "purpose": "convert",
                "idempotency_key": "native-writer-api-crash",
                "prepare_plan": True,
                "settings": {"phase_analyzer": False},
            },
        )
        assert response.status_code == 202, response.text
        oid = response.json()["operation_id"]
        ready = wait_operation(client, oid)
        response = client.post(
            f"{API}/{oid}/convert",
            json={
                "expected_revision": ready["revision"],
                "expected_attempt": ready["attempt"],
                "inventory_generation": ready["summary"]["generation"],
                "plan_attempt": ready["plan_attempt"],
                "name": "native-crash",
            },
        )
        assert response.status_code == 202, response.text
        run = native_run(client, oid)
        atomic_write_json(
            root / "started.json", {"operation_id": oid, "project_id": pid, "run": run}
        )
        wait(client, run["job_id"])
        raise AssertionError("The native writer barrier was not reached")


@pytest.mark.parametrize("in_project", [False, True])
@pytest.mark.parametrize("point", [0.0, 1.0])
def test_api_sigkill_inside_native_writer_resumes_pending_units_without_rewriting_commits(
    tmp_path: Path, in_project: bool, point: float
) -> None:
    """D17/D19/D23 / DCM-17/18: real ITK callbacks, API death and parent-death cleanup."""
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from app.tasks.dicom_process import group_running, process_identity, signal_owned
    from tests.test_source_operation_conversion import native_run
    from tests.test_source_operations_api import API, control, wait_operation

    source, output = tmp_path / "source", tmp_path / "derived"
    output.mkdir()
    for index in range(2):
        write_series(
            source / f"P{index}", patient_id=f"P{index}", shape=(5, 4, 12), marker=(2, 1, 3)
        )
    inputs = {path: digest(path) for path in source.rglob("*") if path.is_file()}
    code = (
        "import sys; from pathlib import Path; "
        "from tests.test_dicom_operation_recovery import native_api_child; "
        "native_api_child(Path(sys.argv[1]), sys.argv[2] == 'True', float(sys.argv[3]))"
    )
    sentinel = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
        stdin=subprocess.PIPE,
        start_new_session=True,
    )
    owner = None
    with (tmp_path / "native-api.log").open("w") as log:
        api = subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path), str(in_project), str(point)],
            env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            # Setup includes four owned worker boots; shared CI load is not a cleanup deadline.
            deadline = time.monotonic() + 90
            barriers: list[Path] = []
            while time.monotonic() < deadline:
                assert api.poll() is None, (tmp_path / "native-api.log").read_text()
                barriers = list((tmp_path / "workspace").rglob("native-writer-barrier.json"))
                if barriers and (tmp_path / "started.json").exists():
                    break
                time.sleep(0.02)
            assert len(barriers) == 1, (tmp_path / "native-api.log").read_text()
            barrier = json.loads(barriers[0].read_text())
            owner = process_identity(barrier["pid"])
            assert barrier["progress"] == point
            saved = {
                p: (digest(p), p.stat().st_mtime_ns)
                for p in output.rglob("*.nii.gz")
                if p.is_file()
                and not any(part.startswith(".") for part in p.relative_to(output).parts)
            }
            assert len(saved) == 1
            api.kill()
            api.wait(timeout=5)
            deadline = time.monotonic() + 5
            while group_running(owner["group"]) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not group_running(owner["group"]), "Native writer survived API death"
            assert sentinel.poll() is None
            started = json.loads((tmp_path / "started.json").read_text())
            settings = Settings(
                workspace_root=tmp_path / "workspace",
                allowed_data_roots=str(source),
                allowed_derived_roots=str(output),
                dicom_memory_mb=1024,
                _env_file=None,
            )  # type: ignore[call-arg]
            with TestClient(create_app(settings, inline_jobs=True)) as client:
                oid = started["operation_id"]
                interrupted = client.get(f"{API}/{oid}").json()
                assert interrupted["status"] == "interrupted" and interrupted["cleanup_verified"], (
                    interrupted
                )
                assert control(client, oid, "resume").status_code == 202
                completed = wait_operation(client, oid)
                assert completed["status"] == "completed", completed
                run = native_run(client, oid)
                assert run["run_id"] == started["run"]["run_id"]
                assert run["attempts"] == started["run"]["attempts"] + 1
                if in_project:
                    imports = client.get(f"/api/v1/projects/{started['project_id']}/imports").json()
                    assert imports["total"] == 1
                else:
                    assert client.get("/api/v1/projects").json() == []
                    assert len(list(output.glob("_datasets/*/dataset.json"))) == 1
            assert saved == {p: (digest(p), p.stat().st_mtime_ns) for p in saved}
            images = [
                p
                for p in output.rglob("*.nii.gz")
                if not any(part.startswith(".") for part in p.relative_to(output).parts)
            ]
            assert len(images) == 2 and not list(output.rglob("*.tmp.nii.gz"))
            for path in images:
                image = nib.load(path)
                [marker] = np.argwhere(image.get_fdata() == MARKER)
                np.testing.assert_allclose(
                    image.affine @ [*marker, 1], [18.6, 29.1, 107.5, 1], atol=1e-4
                )
            assert inputs == {path: digest(path) for path in inputs}
        finally:
            if api.poll() is None:
                api.kill()
                api.wait(timeout=5)
            if owner is not None:
                signal_owned(owner, signal.SIGKILL)
            sentinel.terminate()
            sentinel.wait(timeout=5)


def kill_at_publication(source: Path, output: Path, barrier: str) -> None:
    code = """
import os, signal, sys
from pathlib import Path
from plugins.dicom import commits, convert, sidecar
from tests.test_dicom_resume import run_conversion
source, output, barrier = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
original_image, original_side = convert.write_nifti, sidecar.write_sidecar
original_record, original_link = commits._write, os.link
def stop():
    os.kill(os.getpid(), signal.SIGKILL)
def image(series, path):
    result = original_image(series, path)
    if barrier == 'staging_image' and series.dicom_dir.name == 'P1': stop()
    return result
def side(header, path):
    original_side(header, path)
    if barrier == 'staging_sidecar' and 'case_00001' in str(path): stop()
def record(path, value):
    original_record(path, value)
    if 'case_00001' in str(path) and barrier == value.get('status') + '_record': stop()
def link(src, dst, **kwargs):
    result = original_link(src, dst, **kwargs)
    path = Path(dst)
    if 'case_00001' in path.name:
        if barrier == 'image_publication' and path.parent == output / 'nifti': stop()
        if barrier == 'sidecar_publication' and path.parent == output / 'sidecars': stop()
    return result
def progress(iid, status, outputs, message):
    if barrier == 'progress_ack' and iid.startswith('case_00001.') and status == 'ok': stop()
convert.write_nifti, sidecar.write_sidecar, commits._write, os.link = image, side, record, link
run_conversion(source, output, checkpoint=output / 'run/pin.json', progress=progress)
raise SystemExit('The requested SIGKILL barrier was not reached')
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(source), str(output), barrier],
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(sys.path),
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS": "1",
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == -signal.SIGKILL, result.stdout + result.stderr


@pytest.mark.parametrize(
    "barrier",
    [
        "staging_image",
        "staging_sidecar",
        "prepared_record",
        "image_publication",
        "sidecar_publication",
        "committed_record",
        "progress_ack",
    ],
)
def test_sigkill_at_each_publication_barrier_preserves_commits_and_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, barrier: str
) -> None:
    source, output = tmp_path / "source", tmp_path / "derived"
    for n in range(2):
        write_series(source / f"P{n}", patient_id=f"P{n}", shape=(5, 4, 12), marker=(2, 1, 3))
    before_source = {p: digest(p) for p in source.rglob("*") if p.is_file()}
    kill_at_publication(source, output, barrier)
    saved = {p: (digest(p), p.stat().st_mtime_ns) for p in (output / "nifti").glob("*.nii.gz")}
    assert any("case_00000" in p.name for p in saved)
    assert not (output / "dataset.json").exists()
    original = convert.write_nifti
    decoded = []

    def tracked(series: Any, path: Path) -> Any:
        decoded.append(series.dicom_dir.name)
        return original(series, path)

    with monkeypatch.context() as trace:
        trace.setattr(convert, "write_nifti", tracked)
        resumed = run_conversion(source, output, checkpoint=output / "run/pin.json")
    assert resumed.counts["failed"] == resumed.counts["pending"] == 0
    assert decoded == (["P1"] if barrier.startswith("staging_") else [])
    assert saved == {p: (digest(p), p.stat().st_mtime_ns) for p in saved}
    reference = tmp_path / "reference-derived"
    uninterrupted = run_conversion(source, reference)
    assert [{k: v for k, v in row.items() if k != "status"} for row in resumed.rows] == [
        {k: v for k, v in row.items() if k != "status"} for row in uninterrupted.rows
    ]
    assert len(list((output / "nifti").glob("*.nii.gz"))) == 2
    for image in (output / "nifti").glob("*.nii.gz"):
        actual, expected = nib.load(image), nib.load(reference / "nifti" / image.name)
        np.testing.assert_array_equal(actual.get_fdata(), expected.get_fdata())
        np.testing.assert_allclose(actual.affine, expected.affine, atol=1e-6)
        [marker] = np.argwhere(actual.get_fdata() == MARKER)
        np.testing.assert_allclose(actual.affine @ [*marker, 1], [18.6, 29.1, 107.5, 1], atol=1e-4)
        side = image.name + ".dicom.json"
        assert json.loads((output / "sidecars" / side).read_text()) == json.loads(
            (reference / "sidecars" / side).read_text()
        )
    assert before_source == {p: digest(p) for p in source.rglob("*") if p.is_file()}


def test_source_polling_does_not_wait_for_index_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.jobs.manager import JobManager
    from tests.test_api_ingest import wait
    from tests.test_source_operation_conversion import native_run, prepared_operation
    from tests.test_source_operations_api import API

    original = JobManager._execute
    entered = threading.Event()
    release = asyncio.Event()

    async def delayed(manager: Any, job: Any) -> None:
        if job.info.kind == "index":
            entered.set()
            await release.wait()
        await original(manager, job)

    monkeypatch.setattr(JobManager, "_execute", delayed)
    with prepared_operation(tmp_path, True) as prepared:
        client, _, _, _, record, request = prepared
        oid = record["operation_id"]
        assert client.post(f"{API}/{oid}/convert", json=request).status_code == 202
        native = native_run(client, oid)
        with ThreadPoolExecutor(max_workers=1) as threads:
            try:
                assert entered.wait(10)
                future = threads.submit(client.get, f"{API}/{oid}")
                response = future.result(timeout=1)
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "reconciling"
                assert response.json()["stage"] == "registering"
            finally:
                client.portal.call(release.set)
        wait(client, native["job_id"])
        final = client.get(f"{API}/{oid}").json()
        assert final["status"] == "completed" and final["error"] is None


def test_native_completion_marks_registration_pending_before_finalization_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D24: native success cannot expose an empty project as a completed import."""
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.tasks.registration import RegistrationBase
    from tests.test_api_ingest import wait
    from tests.test_source_operation_conversion import native_run, prepared_operation
    from tests.test_source_operations_api import API

    original = RegistrationBase._finalize_dicom
    entered, release = threading.Event(), asyncio.Event()

    async def finalize(service: Any, live: Any, result: Any) -> None:
        async with service.locks(f"_dicom_registration:{live.pid}:{live.rid}"):
            entered.set()
            await release.wait()
        await original(service, live, result)

    monkeypatch.setattr(RegistrationBase, "_finalize_dicom", finalize)
    with prepared_operation(tmp_path, True) as prepared:
        client, _, _, _, record, request = prepared
        oid = record["operation_id"]
        assert client.post(f"{API}/{oid}/convert", json=request).status_code == 202
        native = native_run(client, oid)
        requests = ThreadPoolExecutor(max_workers=1)
        try:
            assert entered.wait(10)
            response = requests.submit(client.get, f"{API}/{oid}").result(1)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "reconciling", response.json()
            assert response.json()["stage"] == "registering"
        finally:
            client.portal.call(release.set)
            requests.shutdown(wait=True)
        wait(client, native["job_id"])
        assert client.get(f"{API}/{oid}").json()["status"] == "completed"


@pytest.mark.parametrize("lost_response", [None, "before", "after"])
@pytest.mark.parametrize("fault_kind", ["worker", "busy"])
def test_failed_index_retries_only_registration_and_replays_a_lost_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost_response: str | None, fault_kind: str
) -> None:
    from app.core.errors import JobConflict
    from app.ingest import service as ingest_module
    from tests.test_api_ingest import ctx_of, wait
    from tests.test_dicom_registration import wait_registration
    from tests.test_source_operation_conversion import native_run, prepared_operation
    from tests.test_source_operations_api import API

    def fail_index(*_args: Any) -> Any:
        raise OSError("Synthetic index failure")

    async def busy_index(*_args: Any, **_kwargs: Any) -> Any:
        raise JobConflict("An index job is already active: synthetic")

    with prepared_operation(tmp_path, True) as prepared:
        client, _, _, derived, record, request = prepared
        oid, pid = record["operation_id"], record["project_id"]
        with monkeypatch.context() as fault:
            if fault_kind == "worker":
                fault.setattr(ingest_module.indexer, "probe_batch", fail_index)
            else:
                fault.setattr(ingest_module.IngestService, "import_generated", busy_index)
            assert client.post(f"{API}/{oid}/convert", json=request).status_code == 202
            native = native_run(client, oid)
            wait(client, native["job_id"])
        failed = client.get(f"{API}/{oid}").json()
        assert failed["status"] == "failed" and "index" in failed["error"], failed
        before = {
            p: (digest(p), p.stat().st_mtime_ns) for p in derived.rglob("*.nii.gz") if p.is_file()
        }
        assert len(before) == 1
        command = {
            "expected_revision": failed["revision"],
            "expected_attempt": failed["attempt"],
            "expected_run_attempt": 1,
        }
        service = ctx_of(client).source_operations.tasks
        original_get = service.get_run

        async def lost(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("retry_registration") and lost_response == "before":
                raise OSError("Lost registration response")
            result = await original_get(*args, **kwargs)
            if kwargs.get("retry_registration") and lost_response == "after":
                raise OSError("Lost registration response")
            return result

        if lost_response:
            with monkeypatch.context() as fault:
                fault.setattr(service, "get_run", lost)
                with pytest.raises(OSError, match="Lost registration response"):
                    client.post(f"{API}/{oid}/resume", json=command)
        response = client.post(f"{API}/{oid}/resume", json=command)
        assert response.status_code == 202, response.text
        restored = wait_registration(client, pid, native["run_id"])
        assert restored["status"] == "completed" and restored["error"] is None, restored
        assert restored["attempts"] == 1 and restored["job_id"] == native["job_id"]
        assert client.post(f"{API}/{oid}/resume", json=command).status_code == 202
        jobs = client.get(f"/api/v1/jobs?project={pid}").json()
        assert (
            len([job for job in jobs if job.get("key") == f"dicom.registration:{native['run_id']}"])
            == 1
        )
        assert client.get(f"{API}/{oid}").json()["status"] == "completed"
        assert client.get(f"/api/v1/projects/{pid}/items").json()["total"] == 1
        assert before == {p: (digest(p), p.stat().st_mtime_ns) for p in before}


def test_prepared_commit_requires_staging_directory_sync_after_sidecar_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "source", tmp_path / "derived"
    write_series(source)
    original_side, original_sync, original_record = (
        sidecar.write_sidecar,
        commits._sync,
        commits._write,
    )
    side_written = False
    staging_synced = False

    def side(header: Any, path: Path) -> Any:
        nonlocal side_written
        result = original_side(header, path)
        side_written = True
        return result

    def sync(path: Path) -> None:
        nonlocal staging_synced
        original_sync(path)
        if path.name == "staged" and side_written:
            staging_synced = True

    def record(path: Path, value: dict[str, Any]) -> None:
        if value["status"] == "prepared":
            assert staging_synced, "Prepared manifest preceded durable sidecar directory entry"
        original_record(path, value)

    monkeypatch.setattr(sidecar, "write_sidecar", side)
    monkeypatch.setattr(commits, "_sync", sync)
    monkeypatch.setattr(commits, "_write", record)
    result = run_conversion(source, output)
    assert result.counts["failed"] == 0
    assert result.counts["converted"] == 1 and staging_synced


def test_recovery_syncs_adopted_publications_before_committing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "source", tmp_path / "derived"
    for n in range(2):
        write_series(source / f"P{n}", patient_id=f"P{n}")
    kill_at_publication(source, output, "sidecar_publication")
    original_sync, original_record = commits._sync, commits._write
    synced = set()

    def sync(path: Path) -> None:
        original_sync(path)
        synced.add(path)

    def record(path: Path, value: dict[str, Any]) -> None:
        if value["status"] == "committed" and "case_00001" in str(path):
            assert {output / "nifti", output / "sidecars"} <= synced, (
                "Adopted links need durable parents"
            )
        original_record(path, value)

    monkeypatch.setattr(commits, "_sync", sync)
    monkeypatch.setattr(commits, "_write", record)
    result = run_conversion(source, output, checkpoint=output / "run/pin.json")
    assert result.counts["failed"] == 0 and result.counts["already_converted"] == 1


def registration_child(root: Path, barrier: str) -> None:
    """A disposable API process; faults kill the API itself."""
    import asyncio

    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.ingest import service as ingest_module
    from app.ingest import store as index_store
    from app.jobs.manager import JobManager
    from app.jobs.runs import RunStore
    from app.main import create_app
    from app.tasks import registration
    from tests.test_api_ingest import wait

    original_append = ingest_module.append_jsonl
    original_run = RunStore.write
    original_registration = registration.atomic_write_json
    original_execute = JobManager._execute
    original_index_rows = index_store.write_jsonl_atomic
    original_index_status = index_store.atomic_write_json
    original_identity = registration.identity_store.save
    original_annotations = registration.write_jsonl_atomic
    pending: tuple[Path, dict[str, Any]] | None = None

    async def execute(manager: Any, job: Any) -> None:
        if barrier == "legacy_registration_complete" and job.info.kind == "index":
            await (
                asyncio.Event().wait()
            )  # Keep an unfinished index behind an old completion receipt.
        await original_execute(manager, job)

    def stop() -> None:
        os.kill(os.getpid(), signal.SIGKILL)

    def append(path: Path, rows: Any) -> None:
        if path.name == "imports.jsonl" and barrier == "before_import":
            stop()
        original_append(path, rows)
        if path.name == "imports.jsonl" and barrier == "after_import":
            stop()

    def run(store: Any, path: Path, record: Any) -> None:
        if barrier == "after_index" and any(o.kind == "import" for o in record.outputs):
            stop()
        original_run(store, path, record)
        if barrier == "legacy_registration_complete" and any(
            o.kind == "import" for o in record.outputs
        ):
            assert pending is not None
            original_registration(pending[0], {**pending[1], "status": "completed"})
            stop()

    def checkpoint(path: Path, record: Any) -> None:
        nonlocal pending
        original_registration(path, record)
        if path.name == "registration.json" and record.get("status") == "pending":
            pending = path, record
        if (
            path.name == "registration.json"
            and record.get("status") == "completed"
            and barrier == "registration_complete"
        ):
            stop()

    def index_rows(path: Path, rows: Any) -> None:
        original_index_rows(path, rows)
        if (barrier, path.name) in {
            ("index_warnings", index_store.WARNINGS),
            ("index_cases", index_store.CASES),
            ("index_items", index_store.ITEMS),
        }:
            stop()

    def index_status(path: Path, record: Any) -> None:
        original_index_status(path, record)
        if barrier == "index_ready" and record.get("state") == "ready":
            stop()

    def identity(path: Path, registry: Any) -> None:
        original_identity(path, registry)
        if barrier == "identity_commit":
            stop()

    def annotations(path: Path, rows: Any) -> None:
        original_annotations(path, rows)
        if barrier == "annotations_commit":
            stop()

    ingest_module.append_jsonl = append
    RunStore.write = run
    registration.atomic_write_json = checkpoint
    JobManager._execute = execute
    index_store.write_jsonl_atomic = index_rows
    index_store.atomic_write_json = index_status
    registration.identity_store.save = identity
    registration.write_jsonl_atomic = annotations
    settings = Settings(
        workspace_root=root / "workspace",
        allowed_data_roots=str(root / "source"),
        allowed_derived_roots=str(root / "derived"),
        dicom_memory_mb=1024,
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        pid = client.post("/api/v1/projects", json={"name": "Crash", "packs": []}).json()[
            "project_id"
        ]
        response = client.put(
            f"/api/v1/projects/{pid}/roots/DERIVED",
            json={"path": str(root / "derived"), "role": "derived"},
        )
        assert response.status_code == 200, response.text
        response = client.post(
            f"/api/v1/projects/{pid}/task-runs",
            json={
                "task_id": "dicom.convert",
                "selection": {"source": str(root / "source")},
                "settings": {"phase_analyzer": False},
            },
        )
        assert response.status_code == 202, response.text
        (root / "started.json").write_text(json.dumps({"pid": pid, **response.json()}))
        wait(client, response.json()["job_id"])
        raise AssertionError("Registration SIGKILL barrier was not reached")


@pytest.mark.parametrize(
    "barrier",
    [
        "before_import",
        "after_import",
        "after_index",
        "registration_complete",
        "legacy_registration_complete",
        "identity_commit",
        "annotations_commit",
        "index_warnings",
        "index_cases",
        "index_items",
        "index_ready",
    ],
)
def test_api_sigkill_during_registration_recovers_exactly_one_indexed_import(
    tmp_path: Path, barrier: str
) -> None:
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from tests.test_api_ingest import wait
    from tests.test_dicom_registration import wait_registration

    source, derived = tmp_path / "source", tmp_path / "derived"
    write_series(source, shape=(5, 4, 12), marker=(2, 1, 3))
    derived.mkdir()
    before_source = {p: digest(p) for p in source.rglob("*") if p.is_file()}
    code = (
        "import sys; from pathlib import Path; "
        "from tests.test_dicom_operation_recovery import registration_child; "
        "registration_child(Path(sys.argv[1]), sys.argv[2])"
    )
    process = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), barrier],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert process.returncode == -signal.SIGKILL, process.stdout + process.stderr
    started = json.loads((tmp_path / "started.json").read_text())
    pid, rid = started["pid"], started["run_id"]
    saved = {p: (digest(p), p.stat().st_mtime_ns) for p in derived.rglob("*.nii.gz") if p.is_file()}
    assert len(saved) == 1
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        allowed_derived_roots=str(derived),
        dicom_memory_mb=1024,
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        for _ in range(2):
            record = wait_registration(client, pid, rid)
            assert record["status"] == "completed" and record["error"] is None, record
            [imported] = [o for o in record["outputs"] if o["kind"] == "import"]
            job = client.get(f"/api/v1/jobs/{imported['detail']}")
            if job.status_code == 404:
                indexed = client.get(f"/api/v1/projects/{pid}/items").json()
                assert indexed["total"] == 1, "Completed registration lost its unfinished index"
            else:
                assert job.status_code == 200, job.text
                wait(client, imported["detail"])
        history = client.get(f"/api/v1/projects/{pid}/imports").json()["items"]
        assert len(history) == 1 and history[0]["import_id"] == imported["ref"]
        assert client.get(f"/api/v1/projects/{pid}/items").json()["total"] == 1
    assert saved == {p: (digest(p), p.stat().st_mtime_ns) for p in saved}
    assert before_source == {p: digest(p) for p in source.rglob("*") if p.is_file()}
