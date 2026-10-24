"""D20/D23/D35: recover generated-import finalization without a second import or pixels."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.ingest import service as ingest_module
from app.jobs.runs import RunStore
from app.main import create_app
from tests.test_api_ingest import ctx_of, wait
from tools.dicom_fixtures import write_series

API = "/api/v1"


def wait_registration(client: TestClient, pid: str, rid: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(API + f"/projects/{pid}/task-runs/{rid}")
        assert response.status_code == 200, response.text
        record = response.json()
        if record.get("error") or not (record.get("execution") or {}).get("registration_pending"):
            return dict(record)
        time.sleep(0.02)
    raise AssertionError("Metadata registration did not settle")


@pytest.mark.parametrize(
    "barrier",
    ["before_import", "after_import", "after_index", "changed_output", "changed_metadata"],
)
def test_finalization_after_restart_is_idempotent_at_registration_barriers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, barrier: str
) -> None:
    source, output = tmp_path / "source", tmp_path / "derived"
    write_series(source)
    output.mkdir()
    before_source = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        allowed_derived_roots=str(output),
        dicom_memory_mb=1024,
        _env_file=None,
    )  # type: ignore[call-arg]
    original_append, original_write = ingest_module.append_jsonl, RunStore.write
    interrupted = False

    def interrupt_append(path: Path, rows: Any) -> None:
        nonlocal interrupted
        if not interrupted and path.name == "imports.jsonl":
            interrupted = True
            if barrier == "after_import":
                original_append(path, rows)
            raise OSError("synthetic interruption at import append")
        original_append(path, rows)

    def interrupt_run(store: Any, path: Path, record: Any) -> None:
        nonlocal interrupted
        if not interrupted and any(o.kind == "import" for o in record.outputs):
            interrupted = True
            raise OSError("synthetic interruption after index submission")
        original_write(store, path, record)

    if barrier == "after_index":
        monkeypatch.setattr(RunStore, "write", interrupt_run)
    else:
        monkeypatch.setattr(ingest_module, "append_jsonl", interrupt_append)
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        pid = client.post(API + "/projects", json={"name": "Registration", "packs": []}).json()[
            "project_id"
        ]
        assert (
            client.put(
                API + f"/projects/{pid}/roots/DERIVED",
                json={"path": str(output), "role": "derived"},
            ).status_code
            == 200
        )
        started = client.post(
            API + f"/projects/{pid}/task-runs",
            json={"task_id": "dicom.convert", "selection": {"source": str(source)}},
        )
        assert started.status_code == 202, started.text
        rid = started.json()["run_id"]
        wait(client, started.json()["job_id"])
        assert interrupted
        pdir = ctx_of(client).workspace.project_dir(pid)
        # Simulate loss before the frontend reads/repairs the completed run.
        completed = next(output.rglob("*.nii.gz"))
        before = hashlib.sha256(completed.read_bytes()).hexdigest(), completed.stat().st_mtime_ns
    monkeypatch.setattr(ingest_module, "append_jsonl", original_append)
    monkeypatch.setattr(RunStore, "write", original_write)
    if barrier in {"changed_output", "changed_metadata"}:
        changed = (
            completed
            if barrier == "changed_output"
            else next(output.glob("**/runs/*/metadata.jsonl"))
        )
        changed.write_bytes(changed.read_bytes() + b" ")
        preserved = changed.read_bytes()
        with TestClient(create_app(settings, inline_jobs=True)) as client:
            run = wait_registration(client, pid, rid)
            assert "changed" in run["error"] and not [
                o for o in run["outputs"] if o["kind"] == "import"
            ]
            assert client.get(API + f"/projects/{pid}/imports").json()["items"] == []
        assert changed.read_bytes() == preserved
        assert before_source == {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()
        }
        return
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        for _ in range(2):
            run = wait_registration(client, pid, rid)
            assert run["status"] == "completed", run
            assert run["error"] is None, run
            imports = [o for o in run["outputs"] if o["kind"] == "import"]
            assert len(imports) == 1, run
            wait(client, imports[0]["detail"])
        history = client.get(API + f"/projects/{pid}/imports").json()["items"]
        assert len(history) == 1
        assert history[0]["import_id"] == imports[0]["ref"]
        assert len((pdir / "sources" / "imports.jsonl").read_text().splitlines()) == 1
    assert (
        hashlib.sha256(completed.read_bytes()).hexdigest(),
        completed.stat().st_mtime_ns,
    ) == before
    assert before_source == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()
    }
