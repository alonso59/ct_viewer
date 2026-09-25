"""AUD-A5-03 (PRJ-17, API-60, TST-18, NFR-17): through a view-only token the API never returns
the real `project_id` or an absolute server path — JSON, JSON lines, CSV, problems, SSE and the
project's jobs; the `Redactor` rules themselves (`app/core/redact.py`)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from app.api.v1.view import _Forward
from app.core.redact import Redactor
from app.main import create_app
from app.tasks.registry import manifest_hash
from tests.test_api_ingest import ctx_of, do_import, wait
from tests.test_format_v2 import derived_settings
from tests.test_tasks import ITEMS, builtin_threshold, run_body
from tools.make_fixtures import DATASET

API = "/api/v1"


def test_redactor_maps_roots_to_aliases_and_elides_other_folders() -> None:
    red = Redactor(
        aliases=[("DATA", "/srv/data/ds"), ("DERIVED", "/srv/derived")],
        folders=["/srv/data", "/srv/ws"],
        ids=[("01PID", "view-T")],
    )
    assert red.text("/srv/data/ds/nifti/a.nii.gz") == "DATA:nifti/a.nii.gz"
    assert red.text("File /srv/data/ds/x is bad") == "File DATA:x is bad"
    assert red.text("/srv/data/ds2/x") == "…/ds2/x"  # path boundary: not the DATA root
    assert red.text("/srv/derived/01PID/seg/run") == "DERIVED:view-T/seg/run"
    assert red.text("DERIVED:01PID/a") == "DERIVED:view-T/a"
    assert red.text("/srv/ws") == "…" and red.text("/srv/wsx") == "/srv/wsx"
    assert red.value({"01PID": ["/srv/ws/p", 3, None]}) == {"view-T": ["…/p", 3, None]}
    sse = b'id: 1\r\nevent: job.finished\r\ndata: {"project_id": "01PID"}\r\n\r\n'
    assert (
        red.sse_bytes(sse)
        == b'id: 1\r\nevent: job.finished\r\ndata: {"project_id": "view-T"}\r\n\r\n'
    )
    assert red.jsonl_bytes(b'{"a": "/srv/ws/x"}\n\n') == b'{"a": "\xe2\x80\xa6/x"}\n\n'


def test_forward_redacts_streams_and_buffered_bodies() -> None:
    """SSE chunks are redacted as they come; a chunked JSON body at once, with its length."""

    def fake(ctype: str, parts: list[bytes]) -> Any:
        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            headers = [(b"content-type", ctype.encode())]
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            for i, p in enumerate(parts):
                await send(
                    {"type": "http.response.body", "body": p, "more_body": i < len(parts) - 1}
                )

        return app

    async def run(ctype: str, parts: list[bytes]) -> list[Message]:
        sent: list[Message] = []

        async def send(m: Message) -> None:
            sent.append(m)

        async def receive() -> Message:
            return {"type": "http.disconnect"}

        red = Redactor(ids=[("01PID", "view-T")])
        scope: dict[str, Any] = {"type": "http", "app": fake(ctype, parts)}
        await _Forward(scope, red)(scope, receive, send)
        return sent

    sse = asyncio.run(run("text/event-stream", [b'data: {"p": "01PID"}\n\n', b": ping\n\n"]))
    assert [m.get("body") for m in sse[1:]] == [b'data: {"p": "view-T"}\n\n', b": ping\n\n"]
    js = asyncio.run(run("application/json", [b'{"p": "01', b'PID"}']))
    assert js[1]["body"] == b'{"p":"view-T"}'
    assert dict(js[0]["headers"])[b"content-length"] == str(len(js[1]["body"])).encode()
    raw = asyncio.run(run("application/octet-stream", [b"01PID"]))
    assert raw[1]["body"] == b"01PID"  # binary passes through


@pytest.fixture
def env(tmp_path: Path, fixtures_copy: Path) -> Iterator[TestClient]:
    derived = tmp_path / "derived"
    derived.mkdir()
    s = derived_settings(tmp_path, fixtures_copy / DATASET, derived)
    with TestClient(create_app(s, inline_jobs=True)) as c:
        reg = ctx_of(c).registry
        reg.tasks.pop("segment.threshold", None)
        m = builtin_threshold()
        reg.add(m, manifest_hash(m.model_dump_json().encode()), "builtin")
        yield c


def test_view_only_never_returns_project_id_or_server_paths(
    env: TestClient, data_root: Path, tmp_path: Path
) -> None:
    """AUD-A5-03: task masks (`DERIVED:{pid}/…`), `advanced` paths, run `output_dir`, QC
    messages, problems, `dataset.jsonl` and `/jobs` — none carries the pid or a server path."""
    pid = str(
        env.post(f"{API}/projects", json={"name": "v", "packs": ["ccrcc"]}).json()["project_id"]
    )
    do_import(env, pid, data_root)
    derived = tmp_path / "derived"
    r = env.put(
        f"{API}/projects/{pid}/roots/DERIVED", json={"path": str(derived), "role": "derived"}
    )
    assert r.status_code == 200, r.text
    started = env.post(
        f"{API}/projects/{pid}/task-runs", json=run_body(), headers={"X-Reviewer": "T"}
    )
    assert started.status_code == 202, started.text
    wait(env, started.json()["job_id"])
    rid = started.json()["run_id"]
    token = env.post(f"{API}/projects/{pid}/view-token").json()["view_token"]
    v = f"{API}/view/{token}"
    # the full link still shows them (they are the project's own data)
    full = env.get(f"{API}/projects/{pid}/items/{ITEMS[0]}").json()
    assert any(m["ref"].startswith(f"DERIVED:{pid}/") for m in full["masks"].values())
    secrets = (pid, str(tmp_path), str(tmp_path.resolve()))
    routes = [
        "", "/cases", "/cases/case_00001", f"/items/{ITEMS[0]}", f"/items/{ITEMS[0]}/dicom-tags",
        "/warnings", "/segmentations", "/variables", "/curation/state", "/task-runs",
        f"/task-runs/{rid}", "/exports/dataset-table?format=jsonl", "/exports/dataset-table",
        "/exports/dataset-table?format=jsonl&include_sensitive=true", "/layers", "/jobs",
    ]  # fmt: skip
    for route in routes:
        res = env.get(v + route)
        assert res.status_code in (200, 404), (route, res.text)
        leaked = [s for s in secrets if s in res.text]
        assert not leaked, (route, res.text[:400])
    item = env.get(f"{v}/items/{ITEMS[0]}").json()
    seg = next(k for k in item["masks"] if k.startswith("threshold-"))
    assert item["masks"][seg]["ref"].startswith(f"DERIVED:view-{token}/segment.threshold/")
    assert item["advanced"]["image_path"].startswith("DATA:")
    run = env.get(f"{v}/task-runs/{rid}").json()
    assert run["output_dir"].startswith(f"DERIVED:view-{token}/")
    jobs = env.get(f"{v}/jobs").json()
    assert jobs and {j["project_id"] for j in jobs} == {f"view-{token}"}
    # include_sensitive stays allowed on view-only (owner 2026-09-26), paths still redacted
    rows = env.get(
        f"{v}/exports/dataset-table", params={"format": "jsonl", "include_sensitive": True}
    )
    assert rows.status_code == 200 and json.loads(rows.text.splitlines()[0])["masks"]
    # binary bodies are untouched
    img = env.get(f"{v}/items/{ITEMS[0]}/image")
    assert img.status_code == 200 and img.content[:2] == b"\x1f\x8b"
