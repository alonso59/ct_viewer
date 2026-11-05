"""CTF-24: `rw-mcp` speaks MCP over stdio and drives a live server through CTFlow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

from tests.test_ctflow_client import API
from tests.test_ctflow_client import live as live
from tests.test_tasks import ITEMS

RW_MCP = Path(__file__).resolve().parents[2] / "scripts" / "rw-mcp.py"


class Mcp:
    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc, self.next_id = proc, 0

    def request(self, method: str, **params: Any) -> dict[str, Any]:
        self.next_id += 1
        assert self.proc.stdin and self.proc.stdout
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        reply = json.loads(self.proc.stdout.readline())
        assert reply["id"] == self.next_id
        return dict(reply)

    def tool(self, name: str, **arguments: Any) -> tuple[str, bool]:
        result = self.request("tools/call", name=name, arguments=arguments)["result"]
        return str(result["content"][0]["text"]), bool(result["isError"])


@contextmanager
def mcp(tmp_path: Path, url: str, *extra: str) -> Iterator[Mcp]:
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "config")}
    env.pop("CTFLOW_REVIEWER", None)
    proc = subprocess.Popen(
        [sys.executable, str(RW_MCP), "--url", url, *extra],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env,
    )  # fmt: skip
    try:
        yield Mcp(proc)
    finally:
        assert proc.stdin
        proc.stdin.close()
        proc.wait(10)


def test_tools_list_and_the_query_tool_plans_while_the_run_tool_acts_as_agent(
    live: tuple[str, str], tmp_path: Path
) -> None:
    url, pid = live
    with mcp(tmp_path, url, "--reviewer", "Agent T", "--project", pid) as server:
        init = server.request("initialize", protocolVersion="2024-11-05")["result"]
        assert init["serverInfo"]["name"] == "rw-mcp"
        tools = server.request("tools/list")["result"]["tools"]
        assert [t["name"] for t in tools] == [
            "ctflow_commands", "ctflow_query", "ctflow_run", "ctflow_logs",
        ]  # fmt: skip
        assert server.request("nope")["error"]["code"] == -32601
        assert "diagnose <run or operation>" in server.tool("ctflow_commands")[0]

        planned, failed = server.tool("ctflow_query", line=f"segment.threshold {ITEMS[0]}")
        assert not failed and "→" in planned
        assert httpx.get(f"{url}{API}/projects/{pid}/task-runs").json() == []  # nothing started

        text, failed = server.tool("ctflow_run", line="segment.threshold all")
        assert not failed and "task-run" in text
        run_id = text.split("task-run ")[1].split()[0]
        runs = httpx.get(f"{url}{API}/projects/{pid}/task-runs").json()
        assert runs[0]["origin"]["client"] == "agent" and runs[0]["reviewer"] == "Agent T"

        deadline = time.monotonic() + 60
        while "completed" not in server.tool("ctflow_query", line=f"status {run_id}")[0]:
            assert time.monotonic() < deadline
            time.sleep(0.2)
        diagnosis, _ = server.tool("ctflow_query", line=f"diagnose {run_id}")
        assert "failed" in diagnosis and "e.g." in diagnosis  # the fixture's corrupt image
        everything, failed = server.tool("ctflow_logs", ref=run_id)
        last, _ = server.tool("ctflow_logs", ref=run_id, tail=1)
        assert not failed and 0 < len(last) < len(everything)


def test_the_run_tool_needs_a_reviewer_and_errors_are_tool_errors(
    live: tuple[str, str], tmp_path: Path
) -> None:
    url, pid = live
    with mcp(tmp_path, url, "--project", pid) as server:
        text, failed = server.tool("ctflow_run", line="runs")
        assert failed and "reviewer" in text
        text, failed = server.tool("ctflow_query", line="status missing-id")
        assert failed and text.startswith("error:")
        assert server.tool("nope")[1] is True
