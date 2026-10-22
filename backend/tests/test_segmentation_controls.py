"""TSK-15: controls are durable requests; terminal acknowledgement needs verified cleanup."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests import test_nnunet
from tests.test_api_ingest import ctx_of, wait
from tests.test_nnunet_catalog_api import advertise

external_env = test_nnunet.external_env


def start(client: TestClient, pid: str, *, claimed: bool) -> tuple[str, str, Path]:
    ctx = ctx_of(client)
    ctx.registry.get("segment.nnunet").manifest.resources.gpu = "required"
    advertise(client)
    item = next(i for i in ctx.index.load(pid).items if i.image and i.modality == "CT")
    base = f"/api/v1/projects/{pid}/task-runs"
    response = client.post(
        base, json={"task_id": "segment.nnunet", "selection": {"item_ids": [item.item_id]}}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    job = ctx.settings.workspace_root / "queue" / job_id
    if claimed:
        (job / "claim").write_text(json.dumps({"runner_id": "synthetic-owner"}))
        (job / "attempt.json").write_text(
            json.dumps(
                {"attempt_version": 1, "attempt": "synthetic-generation", "state": "running"}
            )
        )
    return f"{base}/{response.json()['run_id']}", job_id, job


def test_queued_pause_and_archive_are_idempotent_and_retain_audit(
    external_env: tuple[TestClient, str, Path, dict[str, str], Path],
) -> None:
    client, pid, _, _, _ = external_env
    url, job_id, job = start(client, pid, claimed=False)
    paused = client.post(f"{url}/pause")
    assert paused.status_code == 200, paused.text
    wait(client, job_id)
    first = client.get(url).json()
    assert first["status"] == "paused" and first["control"]["acknowledged_at"]
    assert not (job / "claim").exists()
    assert client.post(f"{url}/pause").json()["control"]["id"] == first["control"]["id"]
    assert client.post(f"{url}/archive").status_code == 200
    assert client.post(f"{url}/archive").json()["archived"] is True
    assert (job / "job.json").exists()
    assert not client.get(f"/api/v1/projects/{pid}/task-runs").json()
    assert (
        client.get(f"/api/v1/projects/{pid}/task-runs?archived=true").json()[0]["run_id"]
        == first["run_id"]
    )
    assert client.post(f"{url}/resume").status_code == 409


def test_claimed_pause_waits_for_generation_fenced_cleanup(
    external_env: tuple[TestClient, str, Path, dict[str, str], Path],
) -> None:
    client, pid, _, _, _ = external_env
    url, job_id, job = start(client, pid, claimed=True)
    assert client.post(f"{url}/archive").status_code == 409
    response = client.post(f"{url}/pause")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pausing"
    assert not (job / "cancel").exists(), "pause immediately discarded its in-flight grace period"
    (job / "result.json").write_text(json.dumps({"status": "paused"}))
    (job / "exit.json").write_text(json.dumps({"attempt": "old", "cleanup_verified": True}))
    assert client.get(url).json()["status"] == "pausing"
    assert client.get(url).json()["control"]["acknowledged_at"] is None
    assert client.post(f"{url}/resume").status_code == 409
    (job / "control-ack.json").write_text(
        json.dumps({"id": response.json()["control"]["id"], "attempt": "synthetic-generation"})
    )
    (job / "exit.json").write_text(
        json.dumps({"attempt": "synthetic-generation", "cleanup_verified": True, "code": 0})
    )
    wait(client, job_id)
    detail = client.get(url).json()
    assert detail["status"] == "paused" and detail["control"]["acknowledged_at"]
    ack = json.loads((job / "control-ack.json").read_text())
    assert ack["id"] == detail["control"]["id"] and ack["attempt"] == "synthetic-generation"
    assert client.post(f"{url}/archive").status_code == 200


def test_cancel_supersedes_pause_and_old_control_cannot_acknowledge_it(
    external_env: tuple[TestClient, str, Path, dict[str, str], Path],
) -> None:
    client, pid, _, _, _ = external_env
    url, job_id, job = start(client, pid, claimed=True)
    pause = client.post(f"{url}/pause")
    assert pause.status_code == 200, pause.text
    previous = pause.json()["control"]["id"]
    cancelled = client.post(f"{url}/cancel").json()
    assert cancelled["status"] == "cancelling" and cancelled["control"]["id"] != previous
    (job / "control-ack.json").write_text(
        json.dumps({"id": previous, "attempt": "synthetic-generation"})
    )
    assert client.get(url).json()["control"]["acknowledged_at"] is None
    assert client.post(f"{url}/pause").status_code == 409
    (job / "exit.json").write_text(
        json.dumps({"attempt": "synthetic-generation", "cleanup_verified": True, "code": -15})
    )
    wait(client, job_id)
    detail = client.get(url).json()
    assert detail["status"] == "cancelled" and detail["control"]["action"] == "cancel"
    assert client.post(f"{url}/cancel").json()["control"]["id"] == detail["control"]["id"]
