"""API-40 SSE endpoint: message format, Last-Event-ID resume, termination."""

from __future__ import annotations

import asyncio
import json
import signal
import socket
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sse_starlette.sse import AppStatus

from app.api.v1.events import sse_messages
from app.config import Settings
from app.core.errors import NotFound
from app.events.bus import EventBus
from app.main import create_app


def test_generator_formats_resumes_and_ends_on_close() -> None:
    async def body() -> None:
        bus = EventBus()
        first = bus.publish("p", "project.updated", {"fields": ["name"]})
        second = bus.publish("p", "job.finished", {"job_id": "J", "status": "succeeded"})
        gen = sse_messages(bus, "p", first.id)
        msg = await anext(gen)
        assert msg == {
            "id": str(second.id),
            "event": "job.finished",
            "data": json.dumps({"job_id": "J", "status": "succeeded"}),
        }
        nxt = asyncio.ensure_future(anext(gen))
        await asyncio.sleep(0)
        live = bus.publish("p", "index.rebuilt", {"import_id": "I", "n_items": 1})
        assert (await asyncio.wait_for(nxt, 1))["id"] == str(live.id)
        bus.close()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(gen), 1)
        assert bus.subscriber_count("p") == 0

    asyncio.run(asyncio.wait_for(body(), 5))


def test_generator_unsubscribes_when_closed_early() -> None:
    async def body() -> None:
        bus = EventBus()
        bus.publish("p", "project.updated", {})
        gen = sse_messages(bus, "p", 0)
        await anext(gen)
        assert bus.subscriber_count("p") == 1
        await gen.aclose()  # type: ignore[attr-defined]  # client disconnect
        assert bus.subscriber_count("p") == 0

    asyncio.run(asyncio.wait_for(body(), 5))


def test_unknown_project_is_404(client: TestClient) -> None:
    def missing(pid: str) -> Path:
        raise NotFound(f"Project {pid!r} not found")

    client.app.state.ctx.workspace.project_dir = missing  # type: ignore[attr-defined]
    r = client.get("/api/v1/projects/nope/events")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert client.get("/api/v1/projects/x/events?last_event_id=abc").status_code == 422


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_end_to_end_stream_over_uvicorn(settings: Settings, tmp_path: Path) -> None:
    app = create_app(settings, inline_jobs=True)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    box: dict[str, Any] = {}

    async def serve() -> None:
        box["loop"] = asyncio.get_running_loop()
        await server.serve()

    thread = threading.Thread(target=lambda: asyncio.run(serve()), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline and thread.is_alive(), "server did not start"
            time.sleep(0.02)
        ctx = app.state.ctx
        ctx.workspace.project_dir = lambda pid: tmp_path
        loop: asyncio.AbstractEventLoop = box["loop"]

        def publish(event: str, data: dict[str, Any]) -> int:
            fut = asyncio.run_coroutine_threadsafe(_publish(ctx.bus, event, data), loop)
            return fut.result(2)

        old = publish("project.updated", {"fields": ["a"]})
        replayed = publish("project.updated", {"fields": ["b"]})
        url = f"http://127.0.0.1:{port}/api/v1/projects/p/events"
        seen: list[dict[str, str]] = []
        with (
            httpx.Client(timeout=httpx.Timeout(5.0)) as http,
            http.stream("GET", url, headers={"Last-Event-ID": str(old)}) as r,
        ):
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            cur: dict[str, str] = {}
            try:
                for line in r.iter_lines():
                    if not line:
                        if cur:
                            seen.append(cur)
                            cur = {}
                            if len(seen) == 1:
                                live = publish("job.progress", {"job_id": "J", "done": 1})
                            if len(seen) == 2:
                                # SIGINT path: the open stream must end so shutdown can proceed
                                server.handle_exit(signal.SIGINT, None)
                        continue
                    if line.startswith(":"):
                        continue
                    k, _, v = line.partition(":")
                    cur[k] = v.strip()
            except httpx.RemoteProtocolError:
                pass  # sse-starlette drops the connection on shutdown; clients reconnect
        assert seen[0] == {
            "id": str(replayed),
            "event": "project.updated",
            "data": json.dumps({"fields": ["b"]}),
        }
        assert len(seen) == 2
        assert seen[1]["id"] == str(live) and seen[1]["event"] == "job.progress"
    finally:
        server.should_exit = True
        thread.join(15)
        AppStatus.should_exit = False  # process-global in sse-starlette
    assert not thread.is_alive(), "server did not shut down"


async def _publish(bus: EventBus, event: Any, data: dict[str, Any]) -> int:
    return bus.publish("p", event, data).id
