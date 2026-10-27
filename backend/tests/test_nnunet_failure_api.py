"""TSK-06/07: native failures remain visible in the job and logical run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests import test_nnunet
from tests.test_api_ingest import ctx_of, wait

external_env = test_nnunet.external_env


@pytest.mark.parametrize("status", ["failed", "completed_with_errors"])
def test_native_failure_detail_is_visible_in_run_and_job(
    external_env: tuple[TestClient, str, Path, dict[str, str], Path], status: str
) -> None:
    client, pid, _, _, _ = external_env
    ctx = ctx_of(client)
    items = [i.item_id for i in ctx.index.load(pid).items if i.image and i.modality == "CT"][:3]
    base = f"/api/v1/projects/{pid}/task-runs"
    response = client.post(
        base, json={"task_id": "segment.nnunet", "selection": {"item_ids": items}}
    )
    assert response.status_code == 202, response.text
    started = response.json()
    job = ctx.settings.workspace_root / "queue" / started["job_id"]
    error = "CUDA out of memory. Choose GPUs with more free memory, then resume."
    (job / "progress.jsonl").write_text(
        json.dumps({"t": "item", "item_id": items[0], "status": "failed", "message": error}) + "\n"
    )
    (job / "result.json").write_text(json.dumps({"status": status, "error": error}))
    wait(client, started["job_id"])
    finished = client.get(f"/api/v1/jobs/{started['job_id']}").json()
    assert finished["status"] == ("failed" if status == "failed" else "succeeded")
    if status == "failed":
        assert "CUDA out of memory" in finished["error"]
    detail = client.get(f"{base}/{started['run_id']}").json()
    assert detail["status"] == status
    assert detail["error"] == error
    assert detail["counts"]["pending"] == len(items) - 1
