"""SEG-14: API resume rejects drift before creating a replacement queue job."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests import test_nnunet
from tests.test_api_ingest import ctx_of, wait
from tests.test_nnunet_catalog_api import advertise

external_env = test_nnunet.external_env


@pytest.mark.parametrize("drift", ["input", "profile", "manifest", "none"])
def test_resume_requires_the_original_run_identity(
    external_env: tuple[TestClient, str, Path, dict[str, str], Path],
    drift: str,
) -> None:
    client, pid, _, _, _ = external_env
    ctx = ctx_of(client)
    info = ctx.registry.get("segment.nnunet")
    info.manifest.resources.gpu = "required"
    snapshot = advertise(client)
    item = next(i for i in ctx.index.load(pid).items if i.image is not None and i.modality == "CT")
    base = f"/api/v1/projects/{pid}/task-runs"
    started = client.post(
        base,
        json={
            "task_id": "segment.nnunet",
            "settings": {"profile": test_nnunet.PROFILE_ID},
            "selection": {"item_ids": [item.item_id]},
        },
    )
    assert started.status_code == 202, started.text
    rid, job_id = started.json()["run_id"], started.json()["job_id"]
    original = client.get(f"{base}/{rid}").json()
    assert original["identity"]["inputs"][item.item_id].startswith("sha256:")
    client.post(f"{base}/{rid}/cancel")
    wait(client, job_id)
    if drift == "input":
        assert item.image is not None
        path = ctx.workspace.resolver(pid).resolve(item.image.ref)
        path.write_bytes(path.read_bytes() + b"drift")
    elif drift == "profile":
        snapshot["profiles"][0]["profile_sha256"] = "sha256:replacement"
        heartbeat = ctx.settings.workspace_root / "queue/runners/host.json"
        raw: dict[str, Any] = json.loads(heartbeat.read_text())
        raw["model_catalog"] = snapshot
        heartbeat.write_text(json.dumps(raw))
    elif drift == "manifest":
        info.manifest_hash = "sha256:replacement"
    prior = sorted((ctx.settings.workspace_root / "queue").glob("*/job.json"))
    resumed = client.post(f"{base}/{rid}/resume")
    if drift != "none":
        assert resumed.status_code == 409, resumed.text
        assert sorted((ctx.settings.workspace_root / "queue").glob("*/job.json")) == prior
    else:
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["run_id"] == rid and resumed.json()["job_id"] != job_id
        detail = client.get(f"{base}/{rid}").json()
        assert detail["identity"] == original["identity"]
        assert detail["output_dir"] == original["output_dir"]
