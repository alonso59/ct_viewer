"""API-71: incremental, bounded, redacted reads of the current attempt's output (NFR-17, DCM-24)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.ids import new_ulid, utc_now
from app.main import create_app

SOURCE = "/e/UKBPancreas1"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=SOURCE,
        allowed_derived_roots=str(tmp_path / "derived"),
        _env_file=None,
    )  # type: ignore[call-arg]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, inline_jobs=True)) as c:
        yield c


def operation(settings: Settings, oid: str, *, attempt: int = 1, status: str = "running") -> Path:
    """Write an operation record; returns its attempt dir."""
    root = settings.workspace_root / "plugins/dicom/operations" / oid
    root.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    record = {
        "operation_id": oid,
        "source": SOURCE,
        "project_id": None,
        "purpose": "convert",
        "status": status,
        "attempt": attempt,
        "created_at": now,
        "updated_at": now,
        "request_hash": "x",
    }
    (root / "operation.json").write_text(json.dumps(record))
    job = root / "attempts" / str(attempt)
    job.mkdir(parents=True, exist_ok=True)
    return job


def append(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("a") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)


def read(client: TestClient, kind: str, ref: str, cursor: str | None = None, **q: Any) -> Any:
    params = {**q, **({"cursor": cursor} if cursor else {})}
    response = client.get(f"/api/v1/logs/{kind}/{ref}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_cursor_returns_only_new_lines_and_follows_a_new_attempt(
    client: TestClient, settings: Settings
) -> None:
    oid = new_ulid()
    job = operation(settings, oid)
    append(
        job / "progress.jsonl",
        [
            {"t": "stage", "stage": "reading", "done": 120, "total": 450},
            {"t": "heartbeat"},
            {"t": "log", "level": "warning", "message": "slow disk"},
        ],
    )
    with (job / "progress.jsonl").open("a") as fh:
        fh.write('{"t": "log", "message": "parti')
    first = read(client, "source-operation", oid)
    assert [(x["stream"], x["level"], x["text"]) for x in first["lines"]] == [
        ("stage", "info", "— attempt 1 —"),
        ("stage", "info", "reading 120/450"),
        ("log", "warn", "slow disk"),
    ]
    assert first["done"] is False
    with (job / "progress.jsonl").open("a") as fh:
        fh.write('al"}\n')
    second = read(client, "source-operation", oid, first["next_cursor"])
    assert [x["text"] for x in second["lines"]] == ["partial"]
    assert read(client, "source-operation", oid, second["next_cursor"])["lines"] == []

    job2 = operation(settings, oid, attempt=2, status="failed")
    append(job2 / "progress.jsonl", [{"t": "stage", "stage": "writing", "done": 1, "total": 2}])
    third = read(client, "source-operation", oid, second["next_cursor"])
    assert [x["text"] for x in third["lines"]] == ["— attempt 2 —", "writing 1/2"]
    assert third["done"] is True


def test_inventory_rows_are_sparse_and_responses_are_bounded(
    client: TestClient, settings: Settings
) -> None:
    oid = new_ulid()
    job = operation(settings, oid)
    append(
        job / "progress.jsonl",
        [{"t": "inventory", "files": n, "series": 1} for n in range(5)]
        + [{"t": "log", "message": f"line {n}"} for n in range(10)],
    )
    page = read(client, "source-operation", oid, limit=4)
    assert [x["text"] for x in page["lines"]] == [
        "— attempt 1 —",
        "inventory: files 4, series 1",
        "line 0",
        "line 1",
    ]
    rest = read(client, "source-operation", oid, page["next_cursor"], limit=100)
    assert [x["text"] for x in rest["lines"]] == [f"line {n}" for n in range(2, 10)]
    big = new_ulid()
    append(
        operation(settings, big) / "progress.jsonl",
        [{"t": "log", "message": "x" * 1000} for _ in range(400)],
    )
    page = read(client, "source-operation", big, limit=2000)
    assert 200 < len(page["lines"]) < 300  # 256 KiB of ~1 KiB rows


def test_unknown_or_invalid_references_are_problems(client: TestClient, settings: Settings) -> None:
    assert client.get(f"/api/v1/logs/source-operation/{new_ulid()}").status_code == 404
    assert client.get(f"/api/v1/logs/workspace-run/{new_ulid()}").status_code == 404
    assert client.get("/api/v1/logs/source-operation/not-an-id").status_code == 404
    assert client.get(f"/api/v1/logs/other/{new_ulid()}").status_code == 422
    oid = new_ulid()
    operation(settings, oid)
    bad = client.get(f"/api/v1/logs/source-operation/{oid}", params={"cursor": "%%%"})
    assert bad.status_code in (400, 422)
    assert bad.headers["content-type"].startswith("application/problem+json")


def test_workspace_run_output_is_redacted(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    rid, job_id = new_ulid(), new_ulid()
    run_dir = settings.workspace_root / "plugins/dicom/runs" / rid
    job = run_dir / "attempts" / job_id
    job.mkdir(parents=True)
    derived = settings.derived_roots[0]
    run = {
        "run_id": rid,
        "task": {"id": "dicom.convert", "version": "1", "manifest_hash": "x"},
        "plugin": "dicom",
        "name": "ds",
        "status": "failed",
        "created_at": utc_now(),
        "source": f"{SOURCE}/ANONYM-ABC",
        "dataset_dir": str(derived / "_datasets/ds"),
        "settings": {},
        "settings_hash": "x",
        "job_id": job_id,
    }
    (run_dir / "run.json").write_text(json.dumps(run))
    append(
        job / "progress.jsonl",
        [{"t": "log", "level": "error", "message": f"cannot read {SOURCE}/ANONYM-ABC/IM0001.dcm"}],
    )
    (job / "task.log").write_text(
        "Traceback (most recent call last):\n"
        f'  File "/usr/lib/python3.12/site-packages/pydicom/filereader.py", line 9, in read\n'
        f"OSError: [Errno 5] {SOURCE}/ANONYM-ABC/sub dir/IM0001.dcm: bad\n"
        f"writing {derived}/_datasets/ds/nifti/a.nii.gz and {settings.workspace_root}/x.json\n"
        "tail without newline"
    )
    page = read(client, "workspace-run", rid)
    body = json.dumps(page)
    assert "ANONYM-ABC" not in body and "IM0001" not in body and "sub dir" not in body
    for raw in (SOURCE, str(derived), str(settings.workspace_root), str(tmp_path), "/usr/lib"):
        assert raw not in body
    assert [x["text"] for x in page["lines"]] == [
        "— attempt 1 —",
        "cannot read DATA:",
        "Traceback (most recent call last):",
        '  File "…/filereader.py", line 9, in read',
        "OSError: [Errno 5] DATA:",
        "writing DERIVED:_datasets/ds/nifti/a.nii.gz and WORKSPACE:x.json",
        "tail without newline",
    ]
    assert {x["stream"] for x in page["lines"][2:]} == {"stderr"}
    assert page["done"] is True
