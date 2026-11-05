#!/usr/bin/env python3
"""rw-mcp: an MCP server (stdio) that lets an agent drive the workbench through CTFlow.

Standard library only. It is a thin client of the CTFlow API: every action is a CTFlow line the
server validates, fences and records with origin `agent`. It keeps only its CTFlow session.

  python3 scripts/rw-mcp.py [--url URL] [--reviewer NAME] [--project ID]
  claude mcp add rw -- python3 scripts/rw-mcp.py

Tools: ctflow_commands · ctflow_query (plan mode: reads, and previews of anything that acts) ·
ctflow_run (executes; needs a reviewer) · ctflow_logs. URL and reviewer resolve as in ctflow.py.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from typing import Any

import ctflow

PROTOCOL = "2024-11-05"
TEXT_LINES = 40
LOG_PAGES = 20
LINE = {"type": "string", "description": "A CTFlow line, e.g. `runs` or `diagnose <id>`"}
PROJECT = {"type": "string", "description": "Project id; omit to use the session's"}
TOOLS: list[dict[str, Any]] = [
    {
        "name": "ctflow_commands",
        "description": "List the CTFlow commands with usage and a one-line summary.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "ctflow_query",
        "description": "Run a CTFlow line in plan mode: read commands (runs, status, diagnose, "
        "batches, cases) return results; commands that act are only checked, never executed.",
        "inputSchema": {
            "type": "object",
            "properties": {"line": LINE, "project": PROJECT},
            "required": ["line"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "ctflow_run",
        "description": "Run a CTFlow line for real (start, cancel, resume, retry, batch control). "
        "Recorded under the reviewer name and origin `agent`.",
        "inputSchema": {
            "type": "object",
            "properties": {"line": LINE, "project": PROJECT},
            "required": ["line"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "ctflow_logs",
        "description": "The last lines of the redacted log of a run or source operation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Run or operation id"},
                "tail": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
            },
            "required": ["ref"],
        },
        "annotations": {"readOnlyHint": True},
    },
]


def summarize(result: dict[str, Any]) -> str:
    """The parts of an eval result an agent needs, without the raw payloads."""
    out: list[str] = []
    for step in result.get("steps") or []:
        work = step.get("started") or step.get("work")
        tail = f" · {work['kind']} {work['id']} {work['status']}" if work else ""
        out.append(f"{step['command']} → {step.get('value') or ''}{tail}")
    text = result.get("text") or []
    out += text[:TEXT_LINES]
    if len(text) > TEXT_LINES:
        out.append(f"… {len(text) - TEXT_LINES} more lines")
    if result.get("plan_stopped"):
        out.append(f"plan stopped at: {result['plan_stopped']}")
    error = result.get("error")
    if error:
        out += problem_lines(error)
    return "\n".join(out) or "ok"


def problem_lines(body: dict[str, Any]) -> list[str]:
    lines = [f"error: {body.get('title') or 'refused'}: {body.get('detail') or ''}"]
    for err in body.get("errors") or []:
        loc = ".".join(str(p) for p in err.get("loc") or [])
        lines.append(f"  {loc}: {err.get('msg')}" if loc else f"  {err.get('msg')}")
    if body.get("actions"):
        lines.append(f"  next: {', '.join(body['actions'])}")
    return lines


class Server:
    def __init__(self, client: ctflow.Client) -> None:
        self.client = client
        client.origin = "agent"

    def call_tool(self, name: str, args: dict[str, Any]) -> str:
        c = self.client
        if args.get("project"):
            c.project = str(args["project"])
        if name == "ctflow_commands":
            return "\n".join(f"{i['usage']}  — {i['summary']}" for i in c.catalog())
        if name in {"ctflow_query", "ctflow_run"}:
            if name == "ctflow_run" and not c.reviewer:
                raise ctflow.Refused(
                    422,
                    {
                        "title": "reviewer-required",
                        "detail": "Start rw-mcp with --reviewer NAME or set CTFLOW_REVIEWER",
                    },
                )
            return summarize(c.eval(str(args["line"]), plan=name == "ctflow_query"))
        if name == "ctflow_logs":
            work = ctflow.find(c, str(args["ref"]))
            lines: list[str] = []
            cursor = None
            for _ in range(LOG_PAGES):
                page = c.logs(work, cursor)
                lines += [f"{e['level']:5} {e['text']}" for e in page["lines"]]
                cursor = page["next_cursor"]
                if page["done"] or not page["lines"]:
                    break
            return "\n".join(lines[-int(args.get("tail") or 50) :]) or "no log lines"
        raise KeyError(name)

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method, ident = message.get("method"), message.get("id")
        if ident is None:
            return None  # notifications (initialized, cancelled) need no reply
        if method == "initialize":
            result: dict[str, Any] = {
                "protocolVersion": (message.get("params") or {}).get("protocolVersion", PROTOCOL),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "rw-mcp", "version": "1"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = message.get("params") or {}
            result = self.tool_result(str(params.get("name")), params.get("arguments") or {})
        else:
            return {
                "jsonrpc": "2.0",
                "id": ident,
                "error": {"code": -32601, "message": f"Unknown method {method}"},
            }
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    def tool_result(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            with contextlib.redirect_stdout(sys.stderr):  # stdout carries the protocol only
                text, failed = self.call_tool(name, args), False
        except ctflow.Refused as exc:
            text, failed = "\n".join(problem_lines(exc.body or {"detail": str(exc)})), True
        except ConnectionError as exc:
            text, failed = str(exc), True
        except KeyError:
            text, failed = f"Unknown tool {name}", True
        return {"content": [{"type": "text", "text": text}], "isError": failed}


def main(argv: list[str]) -> int:
    options: dict[str, str | None] = {"--url": None, "--reviewer": None, "--project": None}
    for flag, value in zip(argv[::2], argv[1::2], strict=False):
        if flag not in options:
            print(f"rw-mcp: unknown option {flag}", file=sys.stderr)
            return 2
        options[flag] = value
    name = options["--reviewer"] or os.environ.get("CTFLOW_REVIEWER") or ctflow.load_config().get("reviewer")
    server = Server(ctflow.Client(ctflow.server_url(options["--url"]), name, options["--project"]))
    for raw in sys.stdin:
        if not raw.strip():
            continue
        try:
            reply = server.handle(json.loads(raw))
        except ValueError:
            reply = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
