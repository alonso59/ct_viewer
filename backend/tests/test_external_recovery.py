"""TSK-14, BE-14: reconnect the same supervised attempt after API restart."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_api_ingest import ctx_of, do_import, wait
from tests.test_runner import API, ITEMS, REPO, poll
from tools.make_fixtures import DATASET


@pytest.mark.parametrize("claimed", [False, True])
def test_api_restart_does_not_cancel_or_duplicate_external_work(
    tmp_path: Path,
    fixtures_copy: Path,
    claimed: bool,
) -> None:
    plugins = tmp_path / "plugins"
    shutil.copytree(REPO / "plugins/threshold", plugins / "threshold")
    manifest_path = plugins / "threshold/task.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["resources"]["gpu"] = "required"
    manifest_path.write_text(json.dumps(manifest))
    derived = tmp_path / "derived"
    derived.mkdir()
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(fixtures_copy / DATASET),
        allowed_derived_roots=str(derived),
        plugins_root=plugins,
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        project = client.post(f"{API}/projects", json={"name": "Recovery"}).json()["project_id"]
        # Register the test-owned manifest without a product plugin contribution.
        ctx = ctx_of(client)
        from app.tasks.registry import parse_manifest

        parsed, digest = parse_manifest(manifest_path)
        ctx.registry.add(parsed, digest, "plugins_root", manifest_path)
        do_import(client, project, fixtures_copy / DATASET)
        assert (
            client.put(
                f"{API}/projects/{project}/roots/DERIVED",
                json={"path": str(derived), "role": "derived"},
            ).status_code
            == 200
        )
        started = client.post(
            f"{API}/projects/{project}/task-runs",
            json={"task_id": "segment.threshold", "selection": {"item_ids": ITEMS[:1]}},
        ).json()
        job = settings.workspace_root / "queue" / started["job_id"]
        poll(lambda: (job / "job.json").exists())
        spec = json.loads((job / "job.json").read_text())
        if claimed:
            (job / "claim").write_text(json.dumps({"runner_id": "synthetic-owner"}))
            (job / "attempt.json").write_text(
                json.dumps({"attempt": "synthetic-attempt", "state": "running"})
            )
        output = Path(spec["output_dir"]) / "one.nii.gz"
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(spec["items"][0]["image"]["path"], output)
        progress = (
            json.dumps({"t": "log", "message": "synthetic durable stage"})
            + "\n"
            + json.dumps(
                {
                    "t": "item",
                    "item_id": ITEMS[0],
                    "status": "ok",
                    "outputs": [
                        {"kind": "mask", "path": str(output), "labels": {"1": "foreground"}}
                    ],
                }
            )
            + "\n"
        )
        if claimed:
            (job / "progress.jsonl").write_text(progress)
        masks = (
            ctx.workspace.project_dir(project) / "tasks/runs" / started["run_id"] / "masks.jsonl"
        )
        ledger = ctx.workspace.project_dir(project) / "derived/runs.jsonl"
        if claimed:
            poll(lambda: masks.exists())
            run_dir = masks.parent
            poll(
                lambda: any(
                    o.get("kind") == "mask"
                    for o in json.loads((run_dir / "run.json").read_text())["outputs"]
                )
            )
            persisted = json.loads((run_dir / "run.json").read_text())
            assert persisted["progress_cursor"] > 0
            assert persisted["progress_done"] == 1
            assert len(ledger.read_text().splitlines()) == 1
    assert not (job / "cancel").exists(), "API shutdown cancelled supervised work"
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        # Recovery is a startup responsibility, before a browser happens to request the run.
        assert ctx_of(client).jobs.get(started["job_id"]).job_id == started["job_id"]
        ctx_of(client).registry.add(parsed, digest, "plugins_root", manifest_path)
        resumed = client.get(f"{API}/projects/{project}/task-runs/{started['run_id']}")
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["job_id"] == started["job_id"]
        expected = {"running"} if claimed else {"queued", "waiting_for_runner"}
        assert resumed.json()["status"] in expected
        assert len(list((settings.workspace_root / "queue").glob("*/job.json"))) == 1
        if not claimed:
            (job / "claim").write_text(json.dumps({"runner_id": "synthetic-owner"}))
            (job / "attempt.json").write_text(
                json.dumps({"attempt": "synthetic-attempt", "state": "running"})
            )
            (job / "progress.jsonl").write_text(progress)
        (job / "result.json").write_text(
            json.dumps({"status": "completed", "counts": {"items": 1, "skipped": 1}})
        )
        (job / "exit.json").write_text(
            json.dumps({"attempt": "synthetic-attempt", "code": 0, "cleanup_verified": True})
        )
        wait(client, started["job_id"])
        assert (
            client.get(f"{API}/projects/{project}/task-runs/{started['run_id']}").json()["status"]
            == "completed"
        )
        assert len(masks.read_text().splitlines()) == 1, "recovery registered the same mask twice"
        assert len((masks.parent / "items.jsonl").read_text().splitlines()) == 1
        assert len((masks.parent / "log.jsonl").read_text().splitlines()) == 1
        assert len(ledger.read_text().splitlines()) == 1, (
            "recovery appended the same output to the ledger twice"
        )
