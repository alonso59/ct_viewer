"""DCM-22..24, API-70: frozen patient-folder batch plans drive one operation per batch."""

from __future__ import annotations

import json
import os
import signal
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.errors import JobConflict
from app.main import create_app
from app.tasks import source_operations
from app.tasks.source_inventory import SourceInventory
from tests.test_source_operations_api import API, wait_operation
from tools.dicom_fixtures import write_series

PLANS = "/api/v1/source-batches"
SHAPE: dict[str, Any] = {}


def make_settings(tmp_path: Path) -> Settings:
    (tmp_path / "derived").mkdir(exist_ok=True)
    return Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(tmp_path / "source"),
        allowed_derived_roots=str(tmp_path / "derived"),
        dicom_memory_mb=1024,
        _env_file=None,
    )  # type: ignore[call-arg]


def patients(source: Path, names: list[str]) -> None:
    for name in names:
        write_series(source / name, patient_id=f"ID-{name}", **SHAPE)


@contextmanager
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(tmp_path), inline_jobs=True)) as client:
        yield client


def create_plan(client: TestClient, source: Path, **body: Any) -> dict[str, Any]:
    response = client.post(PLANS, json={"path": str(source), **body})
    assert response.status_code == 201, response.text
    return dict(response.json())


def wait_plan(
    client: TestClient, plan_id: str, done: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    deadline = time.monotonic() + 40
    plan: dict[str, Any] = {}
    while time.monotonic() < deadline:
        plan = client.get(f"{PLANS}/{plan_id}").json()
        if done(plan):
            return plan
        time.sleep(0.05)
    raise AssertionError(plan)


def batch_status(index: int, *wanted: str) -> Callable[[dict[str, Any]], bool]:
    return lambda plan: plan["batches"][index]["status"] in wanted


def test_plan_freezes_sorted_folders_and_never_names_them_in_the_api(tmp_path: Path) -> None:
    source = tmp_path / "source"
    patients(source, ["delta", "Alpha", "charlie", "Bravo", "echo"])
    (source / "notes.txt").write_text("not a patient")
    with app_client(tmp_path) as client:
        plan = create_plan(client, source, batch_size=2, name="Study X")
        assert [b["name"] for b in plan["batches"]] == ["Study-X-b01", "Study-X-b02", "Study-X-b03"]
        assert [b["folder_count"] for b in plan["batches"]] == [2, 2, 1]
        assert plan["status"] == "pending" and plan["auto"] is False
        counted = wait_plan(client, plan["plan_id"], lambda p: p["counting"] == "done")
        assert [b["files_total"] for b in counted["batches"]] == [28, 28, 14]
        text = json.dumps(counted)
        assert not any(name in text for name in ("Alpha", "Bravo", "delta", "ID-"))
        stored = json.loads(
            (
                tmp_path / "workspace/plugins/dicom/batches" / plan["plan_id"] / "plan.json"
            ).read_text()
        )
        assert [b["folders"] for b in stored["batches"]] == [
            ["Alpha", "Bravo"],
            ["charlie", "delta"],
            ["echo"],
        ]
        patients(source, ["aaa-late"])
        assert client.get(f"{PLANS}/{plan['plan_id']}").json()["batches"][0]["folder_count"] == 2
        grown = client.post(f"{PLANS}/{plan['plan_id']}/add-new-folders")
        assert grown.status_code == 202, grown.text
        assert [b["name"] for b in grown.json()["batches"]][-1] == "Study-X-b04"
        assert grown.json()["batches"][-1]["folder_count"] == 1
        assert client.post(f"{PLANS}/{plan['plan_id']}/add-new-folders").status_code == 409
        listed = client.get(PLANS).json()
        assert listed["total"] == 1 and listed["items"][0]["plan_id"] == plan["plan_id"]


def test_plan_refuses_a_root_with_dicom_and_bad_settings_or_names(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_series(source, **SHAPE)
    patients(source, ["a"])
    with app_client(tmp_path) as client:
        refused = client.post(PLANS, json={"path": str(source)})
        assert refused.status_code == 422 and "directly" in refused.json()["detail"]
        assert client.post(PLANS, json={"path": str(source / "x")}).status_code == 404
    for item in source.glob("*.dcm"):
        item.unlink()
    with app_client(tmp_path) as client:
        bad = client.post(PLANS, json={"path": str(source), "settings": {"nope": 1}})
        assert bad.status_code == 422
        (tmp_path / "derived" / "_datasets" / "taken-b01").mkdir(parents=True)
        taken = client.post(PLANS, json={"path": str(source), "name": "taken"})
        assert taken.status_code == 409
        assert client.post(PLANS, json={"path": str(source), "batch_size": 0}).status_code == 422


@pytest.mark.parametrize("name", ["..", "a/b", "a\\b", ".hidden", "missing", "", "link", "file"])
def test_operation_folder_scope_is_validated(tmp_path: Path, name: str) -> None:
    source = tmp_path / "source"
    patients(source, ["a"])
    (source / "file").write_text("x")
    try:
        (source / "link").symlink_to(source / "a", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with app_client(tmp_path) as client:
        response = client.post(
            API,
            json={"path": str(source), "idempotency_key": "scope-validation", "folders": [name]},
        )
        assert response.status_code == 422, response.text


def test_scoped_inventory_reads_only_its_folders_and_is_not_mixed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    patients(source, ["a", "b", "c"])
    (source / "stray.bin").write_bytes(b"x")
    database = tmp_path / "workspace" / "inventory.sqlite"
    database.parent.mkdir(parents=True)
    with SourceInventory(database, source, ["b", "a"]) as inventory:
        assert inventory.precount() == (28, 3)  # two series of 14 slices; root and 2 folders
        summary = inventory.scan()
        assert summary["dicom"] == 28 and summary["complete"] and summary["series"] == 2
        assert summary["scope_hash"]
        assert inventory.patient_ids() == {"ID-a", "ID-b"}
    with SourceInventory(database, source) as inherited:
        assert inherited.scope == {"a", "b"}
    for other in (["a"], ["a", "b", "c"]):
        with pytest.raises(JobConflict):
            SourceInventory(database, source, other)
    whole = tmp_path / "workspace" / "whole.sqlite"
    with SourceInventory(whole, source) as inventory:
        assert inventory.scan()["dicom"] == 42
    with pytest.raises(JobConflict):
        SourceInventory(whole, source, ["a"])


def test_operation_with_folders_discovers_and_converts_only_that_scope(tmp_path: Path) -> None:
    source = tmp_path / "source"
    patients(source, ["a", "b", "c"])
    body = {"path": str(source), "prepare_plan": True, "name": "scoped"}
    with app_client(tmp_path) as client:
        first = client.post(
            API, json={**body, "idempotency_key": "scope-one", "folders": ["c", "a"]}
        )
        assert first.status_code == 202, first.text
        ready = wait_operation(client, first.json()["operation_id"])
        assert ready["stage"] == "ready" and ready["summary"]["dicom"] == 28
        assert ready["estimate"]["n_units"] == 2
        assert ready["settings"]["patient_folders"] == ["a", "c"]
        replay = client.post(
            API, json={**body, "idempotency_key": "scope-one", "folders": ["c", "a"]}
        )
        assert replay.json()["operation_id"] == first.json()["operation_id"]
        changed = client.post(API, json={**body, "idempotency_key": "scope-one", "folders": ["a"]})
        assert changed.status_code == 409
        clash = client.post(
            API,
            json={
                **body,
                "idempotency_key": "scope-two",
                "folders": ["a"],
                "settings": {"patient_folders": ["b"]},
            },
        )
        assert clash.status_code == 422
        whole = client.post(API, json={**body, "idempotency_key": "scope-whole"})
        assert wait_operation(client, whole.json()["operation_id"])["summary"]["dicom"] == 42


def converted(tmp_path: Path, plan: dict[str, Any], index: int) -> list[str]:
    dataset = tmp_path / "derived" / "_datasets" / plan["batches"][index]["name"]
    assert (dataset / "dataset.json").is_file()
    return sorted(p.name for p in (dataset / "nifti").glob("*.nii.gz"))


def test_sequential_chaining_waits_for_the_first_convert_then_runs_automatically(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    patients(source, ["a", "b", "c", "d", "e"])
    with app_client(tmp_path) as client:
        plan = create_plan(client, source, batch_size=2, name="seq", auto=True)
        pid = plan["plan_id"]
        assert client.post(f"{PLANS}/{pid}/continue").status_code == 409  # not started
        started = client.post(f"{PLANS}/{pid}/start")
        assert started.status_code == 202, started.text
        ready = wait_plan(client, pid, batch_status(0, "ready"))
        time.sleep(0.3)
        held = client.get(f"{PLANS}/{pid}").json()
        assert (
            held["batches"][0]["status"] == "ready" and held["batches"][1]["operation_id"] is None
        )
        assert ready["status"] == "running" and ready["batches"][0]["patients"] == 2
        assert client.post(f"{PLANS}/{pid}/start").status_code == 202  # idempotent
        assert client.post(f"{PLANS}/{pid}/continue").status_code == 202
        done = wait_plan(client, pid, lambda p: p["status"] == "completed")
        assert [b["status"] for b in done["batches"]] == ["completed"] * 3
        assert [b["dataset"] for b in done["batches"]] == ["seq-b01", "seq-b02", "seq-b03"]
        assert done["cursor"] == 3 and not done["warnings"]
        assert [len(converted(tmp_path, done, i)) for i in range(3)] == [2, 2, 1]
        operations = client.get(API).json()["items"]
        assert (
            len(
                [o for o in operations if o["dataset_name"] and o["dataset_name"].startswith("seq")]
            )
            == 3
        )


def test_manual_plan_stops_at_each_batch_until_continue(tmp_path: Path) -> None:
    source = tmp_path / "source"
    patients(source, ["a", "b"])
    with app_client(tmp_path) as client:
        plan = create_plan(client, source, batch_size=1, name="manual")
        pid = plan["plan_id"]
        client.post(f"{PLANS}/{pid}/start")
        wait_plan(client, pid, batch_status(0, "ready"))
        assert client.post(f"{PLANS}/{pid}/continue").status_code == 202
        wait_plan(client, pid, batch_status(1, "ready"))
        time.sleep(0.3)
        assert client.get(f"{PLANS}/{pid}").json()["batches"][1]["status"] == "ready"
        assert client.patch(f"{PLANS}/{pid}", json={"auto": True}).json()["auto"] is True
        done = wait_plan(client, pid, lambda p: p["status"] == "completed")
        assert converted(tmp_path, done, 1)


def crash_batch(monkeypatch: pytest.MonkeyPatch, folder: str) -> dict[str, bool]:
    original = source_operations.run_dicom_worker
    state = {"armed": True}

    async def crash(job: Path, **kwargs: Any) -> dict[str, Any]:
        spec = json.loads((job / "job.json").read_text())
        if state["armed"] and folder in (spec.get("folders") or []):
            state["armed"] = False
            kwargs["on_started"] = lambda pid: os.kill(pid, signal.SIGKILL)
        return await original(job, **kwargs)

    monkeypatch.setattr(source_operations, "run_dicom_worker", crash)
    return state


def test_failure_pauses_the_plan_and_continue_resumes_after_the_operation_is_resumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_source_operations_api import control

    source = tmp_path / "source"
    patients(source, ["a", "b"])
    crash_batch(monkeypatch, "b")
    with app_client(tmp_path) as client:
        plan = create_plan(client, source, batch_size=1, name="pause", auto=True)
        pid = plan["plan_id"]
        client.post(f"{PLANS}/{pid}/start")
        wait_plan(client, pid, batch_status(0, "ready"))
        client.post(f"{PLANS}/{pid}/continue")
        paused = wait_plan(client, pid, lambda p: p["status"] == "paused")
        assert paused["cursor"] == 1 and paused["batches"][0]["status"] == "completed"
        assert paused["batches"][1]["status"] == "attention" and paused["batches"][1]["error"]
        operation = paused["batches"][1]["operation_id"]
        time.sleep(0.3)
        assert client.get(f"{PLANS}/{pid}").json()["status"] == "paused"
        assert client.post(f"{PLANS}/{pid}/start").status_code == 409
        assert control(client, operation, "resume").status_code == 202
        wait_operation(client, operation)
        assert client.post(f"{PLANS}/{pid}/continue").status_code == 202
        done = wait_plan(client, pid, lambda p: p["status"] == "completed")
        assert [b["status"] for b in done["batches"]] == ["completed", "completed"]
        assert len(converted(tmp_path, done, 1)) == 1
        assert client.get(API).json()["total"] == 2


def test_restart_recovers_a_running_plan_without_double_submitting(tmp_path: Path) -> None:
    source = tmp_path / "source"
    patients(source, ["a", "b"])
    with app_client(tmp_path) as client:
        pid = create_plan(client, source, batch_size=1, name="restart")["plan_id"]
        client.post(f"{PLANS}/{pid}/start")
        first = wait_plan(client, pid, batch_status(0, "ready"))
        operation = first["batches"][0]["operation_id"]
    with app_client(tmp_path) as client:
        again = wait_plan(client, pid, lambda p: p["status"] == "running")
        assert again["batches"][0]["operation_id"] == operation
        assert (
            again["batches"][0]["status"] == "ready" and again["batches"][1]["operation_id"] is None
        )
        assert client.post(f"{PLANS}/{pid}/continue").status_code == 202
        client.app.state.ctx.source_batches.nudge()  # type: ignore[attr-defined]
        wait_plan(client, pid, batch_status(1, "ready"))
        assert client.get(API).json()["total"] == 2
    with app_client(tmp_path) as client:
        client.app.state.ctx.source_batches.nudge()  # type: ignore[attr-defined]
        time.sleep(0.5)
        final = client.get(f"{PLANS}/{pid}").json()
        assert (
            final["batches"][1]["status"] == "ready"
            and final["batches"][0]["status"] == "completed"
        )
        assert client.get(API).json()["total"] == 2


def test_restart_during_conversion_pauses_until_the_operation_is_resumed(tmp_path: Path) -> None:
    from tests.test_source_operations_api import control

    source = tmp_path / "source"
    patients(source, ["a"])
    with app_client(tmp_path) as client:
        pid = create_plan(client, source, batch_size=1, name="mid")["plan_id"]
        client.post(f"{PLANS}/{pid}/start")
        first = wait_plan(client, pid, batch_status(0, "ready"))
        operation = first["batches"][0]["operation_id"]
        client.post(f"{PLANS}/{pid}/continue")
    with app_client(tmp_path) as client:
        state = wait_plan(client, pid, lambda p: p["status"] in {"paused", "completed"})
        if state["status"] == "paused":
            assert state["batches"][0]["status"] == "attention"
            assert control(client, operation, "resume").status_code == 202
            wait_operation(client, operation)
            assert client.post(f"{PLANS}/{pid}/continue").status_code == 202
        done = wait_plan(client, pid, lambda p: p["status"] == "completed")
        assert done["batches"][0]["dataset"] == "mid-b01"
        assert client.get(API).json()["total"] == 1


def test_duplicate_patient_across_batches_warns_without_blocking(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_series(source / "a", patient_id="SAME", seed="one", **SHAPE)
    write_series(source / "b", patient_id="SAME", seed="two", **SHAPE)
    write_series(source / "c", patient_id="OTHER", **SHAPE)
    with app_client(tmp_path) as client:
        pid = create_plan(client, source, batch_size=1, name="dupes", auto=True)["plan_id"]
        client.post(f"{PLANS}/{pid}/start")
        wait_plan(client, pid, batch_status(0, "ready"))
        client.post(f"{PLANS}/{pid}/continue")
        done = wait_plan(client, pid, lambda p: p["status"] == "completed")
        assert [w["batch_index"] for w in done["warnings"]] == [2]
        warning = done["warnings"][0]
        assert warning["earlier_batches"] == [1] and warning["patients"] == 1
        assert "SAME" not in json.dumps(done)
        stored = (tmp_path / "workspace/plugins/dicom/batches" / pid / "plan.json").read_text()
        assert "SAME" not in stored and "OTHER" not in stored


def test_cancel_stops_the_plan_and_unstarted_batches(tmp_path: Path) -> None:
    source = tmp_path / "source"
    patients(source, ["a", "b"])
    with app_client(tmp_path) as client:
        pid = create_plan(client, source, batch_size=1, name="cancel")["plan_id"]
        client.post(f"{PLANS}/{pid}/start")
        wait_plan(client, pid, batch_status(0, "ready"))
        cancelled = client.post(f"{PLANS}/{pid}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert {b["status"] for b in cancelled.json()["batches"]} == {"cancelled"}
        assert client.post(f"{PLANS}/{pid}/continue").status_code == 409
        assert client.post(f"{PLANS}/{pid}/cancel").json()["status"] == "cancelled"


def test_unknown_plan_ids_are_not_found(tmp_path: Path) -> None:
    with app_client(tmp_path) as client:
        assert client.get(f"{PLANS}/01JABCDEFGHJKMNPQRSTVWXYZ0").status_code == 404
        assert client.get(f"{PLANS}/not-an-id").status_code == 404
