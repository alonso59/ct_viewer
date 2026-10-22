"""J6/S4 (TSK-15): unverified cleanup blocks archive, resume and new launches until confirmed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.tasks import driver
from tests import test_nnunet
from tests.test_api_ingest import ctx_of, wait
from tests.test_segmentation_controls import start

external_env = test_nnunet.external_env


def test_lost_runner_during_pause_is_cleanup_pending_until_confirmed(
    external_env: tuple[TestClient, str, Path, dict[str, str], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, pid, _, _, _ = external_env
    monkeypatch.setattr(driver, "RUNNER_LOST_S", 0.2)
    url, job_id, job = start(client, pid, claimed=True)
    (job / "attempt.json").unlink()  # claimed, but no supervisor attempt was ever recorded
    assert client.post(f"{url}/pause").json()["status"] == "pausing"
    wait(client, job_id)
    detail = client.get(url).json()
    assert detail["status"] == "cleanup_pending" and detail["control"]["acknowledged_at"] is None
    assert client.post(f"{url}/archive").status_code == 409
    assert client.post(f"{url}/resume").status_code == 409
    item = next(i for i in ctx_of(client).index.load(pid).items if i.image and i.modality == "CT")
    again = client.post(
        f"/api/v1/projects/{pid}/task-runs",
        json={"task_id": "segment.nnunet", "selection": {"item_ids": [item.item_id]}},
    )
    assert again.status_code == 409, again.text
    assert client.post(f"{url}/cancel").json()["status"] == "cleanup_pending"
    (job / "exit.json").write_text(json.dumps({"code": -15, "cleanup_verified": True}))
    detail = client.get(url).json()
    assert detail["status"] == "cancelled" and detail["control"]["acknowledged_at"]
    assert client.post(f"{url}/archive").json()["archived"] is True
    assert (job / "job.json").exists()
    assert client.get(f"{url}/outputs").status_code == 200


def test_unsupervised_runs_refuse_pause_and_archive(
    external_env: tuple[TestClient, str, Path, dict[str, str], Path],
) -> None:
    client, pid, _, _, _ = external_env
    ctx = ctx_of(client)
    item = next(i for i in ctx.index.load(pid).items if i.image and i.modality == "CT")
    response = client.post(
        f"/api/v1/projects/{pid}/task-runs",
        json={"task_id": "segment.nnunet", "selection": {"item_ids": [item.item_id]}},
    )
    assert response.status_code == 202, response.text
    url = f"/api/v1/projects/{pid}/task-runs/{response.json()['run_id']}"
    assert client.get(url).json()["supervised"] is False  # the fake-CLI manifest needs no GPU
    assert client.post(f"{url}/pause").status_code == 409
    assert client.post(f"{url}/archive").status_code == 409
    client.post(f"{url}/cancel")
