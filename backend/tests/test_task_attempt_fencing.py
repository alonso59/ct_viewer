"""TSK-14/15: obsolete task callbacks and unpublished attempts cannot reach the runner."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.errors import JobConflict
from app.core.fsio import atomic_write_json
from app.core.ids import new_ulid
from app.tasks import protocol
from app.tasks.models import TERMINAL_TASK_RUN
from app.tasks.records import Live
from app.tasks.registry import manifest_hash, parse_manifest
from tests.test_api_ingest import ctx_of, wait
from tests.test_tasks import THRESHOLD, finish, run_body, with_derived
from tests.test_tasks import env as env
from tests.test_tasks import plugins_root as plugins_root
from tests.test_tasks import proj as proj


@pytest.mark.parametrize("callback", ["status", "progress", "finish"])
def test_old_task_callbacks_cannot_modify_the_current_attempt(
    env: TestClient, proj: str, tmp_path: Path, callback: str
) -> None:
    with_derived(env, proj, tmp_path)
    started = env.post(f"/api/v1/projects/{proj}/task-runs", json=run_body()).json()
    finish(env, proj, started)
    ctx = ctx_of(env)
    service = ctx.source_operations.tasks
    run_dir = service.runs.run_dir(proj, started["run_id"])
    manifest = service.get("segment.threshold").manifest
    old = Live(
        proj,
        started["run_id"],
        run_dir,
        service.job_dir(manifest, started["job_id"]),
        manifest,
        None,
    )

    def replacement(record: Any) -> None:
        record.job_id = new_ulid()
        record.status = "running"
        record.attempts += 1

    env.portal.call(service.runs.update, proj, run_dir, replacement)
    before = (run_dir / "run.json").read_bytes()
    logs = (run_dir / "log.jsonl").read_bytes() if (run_dir / "log.jsonl").exists() else b""
    if callback == "status":
        env.portal.call(service._set_status, old, "waiting_for_runner")
    elif callback == "progress":
        env.portal.call(
            service._on_lines, old, [{"t": "log", "message": "obsolete", "_offset": 42}]
        )
    else:
        info = ctx.jobs.get(started["job_id"]).model_copy(deep=True)
        env.portal.call(service._finish, old, info)
    assert (run_dir / "run.json").read_bytes() == before
    assert (
        (run_dir / "log.jsonl").read_bytes() if (run_dir / "log.jsonl").exists() else b""
    ) == logs


def test_external_job_is_published_only_after_its_run_owns_the_attempt(
    env: TestClient, proj: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_derived(env, proj, tmp_path)
    ctx = ctx_of(env)
    service = ctx.source_operations.tasks
    manifest, _ = parse_manifest(THRESHOLD)
    manifest = manifest.model_copy(
        update={"resources": manifest.resources.model_copy(update={"gpu": "required"})}
    )
    ctx.registry.tasks.pop(manifest.id)
    ctx.registry.add(
        manifest, manifest_hash(manifest.model_dump_json().encode()), "plugins_root", THRESHOLD
    )
    assert service.get(manifest.id).manifest.runtime.type == "external"
    observed = []
    original = protocol.write_job

    def publish(job: Path, payload: dict[str, Any]) -> None:
        record = service.runs.read(service.runs.run_dir(proj, payload["run_id"]))
        observed.append(record.job_id == job.name and record.status not in TERMINAL_TASK_RUN)
        original(job, payload)

    monkeypatch.setattr(protocol, "write_job", publish)
    response = env.post(f"/api/v1/projects/{proj}/task-runs", json=run_body())
    assert response.status_code == 202, response.text
    started = response.json()
    from tests.test_runner import poll

    poll(lambda: bool(observed))
    assert observed == [True]
    job = ctx.settings.workspace_root / "queue" / started["job_id"]
    assert (job / "job.json").is_file()
    assert not (job / "claim").exists()
    atomic_write_json(job / "attempt.json", {"attempt": "synthetic", "state": "failed"})
    atomic_write_json(job / "result.json", {"status": "failed", "error": "Synthetic failure"})
    atomic_write_json(
        job / "exit.json", {"attempt": "synthetic", "code": 1, "cleanup_verified": True}
    )
    wait(env, started["job_id"])
    original_submit = service._submit

    async def concurrent_resumes() -> None:
        arrived = 0
        release = asyncio.Event()

        async def submit(*args: Any, **kwargs: Any) -> Any:
            nonlocal arrived
            arrived += 1
            if arrived == 2:
                release.set()
            await release.wait()
            return await original_submit(*args, **kwargs)

        monkeypatch.setattr(service, "_submit", submit)
        results = await asyncio.wait_for(
            asyncio.gather(
                service.resume(proj, started["run_id"], expected_attempt=1),
                service.resume(proj, started["run_id"], expected_attempt=1),
                return_exceptions=True,
            ),
            timeout=10,
        )
        accepted = [result for result in results if not isinstance(result, BaseException)]
        assert (
            len(accepted) == 1 and sum(isinstance(result, JobConflict) for result in results) == 1
        )
        current = service.runs.read(service.runs.run_dir(proj, started["run_id"]))
        assert current.job_id == accepted[0].job_id and current.attempts == 2

    env.portal.call(concurrent_resumes)
    poll(lambda: len(observed) == 2)
    assert all(observed)
