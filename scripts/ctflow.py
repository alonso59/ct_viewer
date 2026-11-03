#!/usr/bin/env python3
"""ctflow: the CTFlow console in a terminal (CTF-18).

Standard library only, nothing to install. It sends each line to a running Radiology Workbench
(API-72) and follows the work it starts through the same records and logs the web app reads; the
server owns every run, so closing the terminal never stops one.

  ctflow                                   interactive console
  ctflow -p PROJECT segment case_00012     one command; follows it to the end (exit code = result)
  ctflow -c "segment case_00012" --detach  start and return at once
  ctflow nightly.ctf [--detach]            run a local script as a durable script run on the server
  ctflow --plan nightly.ctf                plan it without starting anything
  ctflow attach ID · ctflow logs ID [-f] · ctflow status ID · ctflow cancel ID · ctflow runs

Server: --url, else CTFLOW_URL, else http://127.0.0.1:$PORT with PORT from the same `.env` as
`./rw` (RW_ENV, default: the repository's `.env`). Reviewer: --reviewer, else CTFLOW_REVIEWER,
else the name saved in ~/.config/ctflow/config.json (asked once in the console).
Exit codes: 0 completed · 1 failed, completed with errors or interrupted · 2 refused or usage ·
3 cancelled, paused or held for attention · 130 stopped following (the work goes on).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

OK, FAILED, REFUSED, STOPPED, DETACHED = 0, 1, 2, 3, 130
EXIT = {
    "completed": OK,
    "completed_with_errors": FAILED,
    "failed": FAILED,
    "interrupted": FAILED,
    "cancelled": STOPPED,
    "paused": STOPPED,
    "attention": STOPPED,
}
SCRIPT_ACTIVE = {"queued", "running", "waiting", "pausing", "cancelling"}
POLL_S = 1.0
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ctflow"
LOCAL = {"exit", "quit", "attach", "logs", "plan"}
# Absolute paths stay out of the saved history: folder names are often patient names (NFR-17).
_PATH = re.compile(r"(^|\s|\")/[^\s\"]")


class Refused(Exception):
    """An RFC 9457 problem from the server."""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        super().__init__(body.get("detail") or body.get("title") or f"HTTP {status}")
        self.status, self.body = status, body


def server_url(explicit: str | None) -> str:
    if explicit or os.environ.get("CTFLOW_URL"):
        return str(explicit or os.environ["CTFLOW_URL"]).rstrip("/")
    env = Path(os.environ.get("RW_ENV") or Path(__file__).resolve().parents[1] / ".env")
    port = "8000"
    try:
        for raw in env.read_text(encoding="utf-8").splitlines():
            key, _, value = raw.strip().partition("=")
            if key == "PORT" and value.strip():
                port = value.strip().strip("\"'")
    except OSError:
        pass
    return f"http://127.0.0.1:{port}"


def load_config() -> dict[str, Any]:
    try:
        return dict(json.loads((CONFIG / "config.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def save_config(config: dict[str, Any]) -> None:
    CONFIG.mkdir(parents=True, exist_ok=True)
    (CONFIG / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


class Client:
    def __init__(self, url: str, reviewer: str | None, project: str | None, kind: str) -> None:
        self.url, self.reviewer, self.project, self.kind = url, reviewer, project, kind
        self._catalog: list[dict[str, Any]] | None = None
        self.session: str | None = None  # the server keeps variables and procedures (CTF-08)

    def call(self, method: str, path: str, body: Any = None, **query: Any) -> Any:
        params = {k: v for k, v in query.items() if v is not None}
        url = f"{self.url}/api/v1{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.reviewer:
            headers["X-Reviewer"] = self.reviewer
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                problem = json.loads(exc.read() or b"{}")
            except ValueError:
                problem = {}
            raise Refused(exc.code, problem if isinstance(problem, dict) else {}) from None
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Cannot reach {self.url} ({exc.reason}); is the app running?")
        return json.loads(raw) if raw else None

    def eval(self, line: str, *, plan: bool = False) -> dict[str, Any]:
        body = {
            "line": line, "session": self.session, "project_id": self.project,
            "plan": plan, "client": self.kind,
        }  # fmt: skip
        try:
            result = dict(self.call("POST", "/ctflow/eval", body))
        except Refused as exc:
            if self.session is None or "new_session" not in (exc.body.get("actions") or []):
                raise
            print("ctflow: the console session ended; its variables and procedures are gone")
            self.session = None
            return self.eval(line, plan=plan)
        self.session, self.project = result["session"], result.get("project_id")
        return result

    def catalog(self) -> list[dict[str, Any]]:
        if self._catalog is None:
            self._catalog = list(self.call("GET", "/ctflow/commands"))
        return self._catalog

    def status_of(self, work: dict[str, Any]) -> dict[str, Any]:
        kind, ident = work["kind"], work["id"]
        if kind == "task-run":
            return dict(self.call("GET", f"/projects/{work['project_id']}/task-runs/{ident}"))
        if kind == "source-operation":
            return dict(self.call("GET", f"/source-operations/{ident}"))
        if kind == "script-run":
            return dict(self.call("GET", f"/ctflow/script-runs/{ident}"))
        return dict(self.call("GET", f"/task-runs/{ident}"))

    def logs(self, work: dict[str, Any], cursor: str | None) -> dict[str, Any]:
        kind = {"task-run": "project-run"}.get(work["kind"], work["kind"])
        project = work.get("project_id") if kind == "project-run" else None
        return dict(self.call("GET", f"/logs/{kind}/{work['id']}", cursor=cursor, project=project))


def show_problem(exc: Refused) -> None:
    body = exc.body
    print(f"ctflow: {body.get('title') or 'refused'}: {body.get('detail') or exc}", file=sys.stderr)
    for err in body.get("errors") or []:
        loc = ".".join(str(p) for p in err.get("loc") or [])
        print(f"  {loc}: {err.get('msg')}" if loc else f"  {err.get('msg')}", file=sys.stderr)
    if body.get("actions"):
        print(f"  next: {', '.join(body['actions'])}", file=sys.stderr)


def show(result: dict[str, Any]) -> None:
    steps = result.get("steps") or []
    target = steps[0].get("target") if len(steps) == 1 else None
    if target:
        what = {"source": "source"}.get(target["kind"], f"{target['kind']} · {target['n_items']} items")
        extra = f" · seg {target['seg_id']}" if target.get("seg_id") else ""
        print(f"target: {what}{extra}")
    for line in result.get("text") or []:
        print(line)
    for step in steps:
        plan = step.get("plan") or {}
        for issue in plan.get("issues") or []:
            print(f"  {step['command']}: {'.'.join(map(str, issue['loc']))}: {issue['msg']}")
        for reason, n in ((plan.get("preflight") or {}).get("missing") or {}).items():
            print(f"  {step['command']}: skipped {n}: {reason}")
    if result.get("plan_stopped"):
        print(f"plan: {result['plan_stopped']}")
    if result.get("value") and not result.get("text"):
        print(result["value"])
    error = result.get("error")
    if error:
        where = f"line {error['line']}: " if error.get("line") else ""
        show_problem(Refused(422, {**error, "detail": where + error["detail"]}))


def is_over(work: dict[str, Any], record: dict[str, Any]) -> bool:
    status = record.get("status")
    if work["kind"] == "script-run":
        return status not in SCRIPT_ACTIVE
    if work["kind"] == "source-operation" and record.get("stage") == "ready":
        return status == "completed"  # analysis done; `convert` is the next step
    return status in EXIT


def follow(client: Client, work: dict[str, Any], *, logs: bool = True) -> int:
    """Print status changes and new log lines until the work ends; Ctrl+C only stops watching."""
    cursor, last = None, None
    try:
        while True:
            record = client.status_of(work)
            status = str(record.get("status"))
            label = f"{status} · {record['stage']}" if record.get("stage") else status
            if label != last:
                print(f"[{work['id']}] {label}")
                if status == "waiting_for_runner":
                    print("  waiting for the host runner (scripts/rw-runner.py) to start")
                if record.get("waiting"):
                    print(f"  {record['waiting']}")
                last = label
            page: dict[str, Any] = {"done": True}
            if logs:
                page = client.logs(work, cursor)
                cursor = page["next_cursor"]
                for line in page["lines"]:
                    print(f"  {line['level']:5} {line['text']}")
            if is_over(work, record) and page["done"]:
                return EXIT.get(status, OK)
            time.sleep(POLL_S)
    except KeyboardInterrupt:
        print(f"\nstill running on the server; follow again with: ctflow attach {work['id']}")
        return DETACHED


def find(client: Client, ref: str) -> dict[str, Any]:
    steps = client.eval(f"status {ref}").get("steps") or [{}]
    work = steps[-1].get("work")
    if not work:
        raise Refused(404, {"detail": f"No run or operation {ref}"})
    return dict(work)


def run_line(client: Client, line: str, *, detach: bool, plan: bool, as_json: bool) -> int:
    words = line.split()
    if words and words[0] in {"attach", "logs"}:
        if len(words) < 2:
            raise Refused(422, {"detail": f"Name the run or operation: {words[0]} <id>"})
        work = find(client, words[1])
        if words[0] == "attach" or "-f" in words:
            return follow(client, work, logs=True)
        page = client.logs(work, None)
        for entry in page["lines"]:
            print(f"{entry['level']:5} {entry['text']}")
        return OK
    result = client.eval(line, plan=plan)
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        show(result)
    if result.get("error"):
        return REFUSED
    if plan:
        plans = [s["plan"] for s in result["steps"] if s.get("plan")]
        return OK if all(p["ok"] for p in plans) else REFUSED
    started = [s["started"] for s in result["steps"] if s.get("started")]
    if len(started) == 1 and not detach:
        return follow(client, started[0])
    for work in started:
        print(f"follow with: ctflow attach {work['id']}")
    return OK


def run_script(client: Client, script: str, name: str, *, detach: bool) -> int:
    """A durable script run (CTF-10): it goes on when this terminal closes."""
    body = {"script": script, "name": name, "project_id": client.project, "client": client.kind}
    run = client.call("POST", "/ctflow/script-runs", body)
    work = {"kind": "script-run", "id": run["run_id"], "project_id": run.get("project_id")}
    print(f"script run {run['run_id']} {run['status']}")
    if detach:
        print(f"follow with: ctflow attach {run['run_id']}")
        return OK
    return follow(client, work)


def complete_factory(client: Client) -> Any:
    def complete(text: str, state: int) -> str | None:
        import readline

        buffer = readline.get_line_buffer()
        words = buffer.split()
        try:
            catalog = client.catalog()
        except (ConnectionError, Refused):
            return None
        if len(words) <= 1 and not buffer.endswith(" "):
            names = sorted({c["name"] for c in catalog} | LOCAL)
            options = [n for n in names if n.startswith(text)]
        else:
            command = next((c for c in catalog if c["name"] == words[0]), None)
            names = [f"-{o['name']}" for o in (command or {}).get("options", [])]
            options = [n for n in names if n.startswith(text)] if text.startswith("-") else []
        return options[state] if state < len(options) else None

    return complete


def console(client: Client, config: dict[str, Any]) -> int:
    try:
        import readline
    except ImportError:  # no line editing on this platform
        readline = None  # type: ignore[assignment]
    history = CONFIG / "history"
    if readline is not None:
        readline.set_auto_history(False)
        readline.set_completer(complete_factory(client))
        readline.set_completer_delims(" \t")
        readline.parse_and_bind("tab: complete")
        try:
            readline.read_history_file(history)
        except OSError:
            pass
    if not client.reviewer:
        name = input("Your name or initials (stamped on what you start): ").strip()
        if name:
            client.reviewer = config["reviewer"] = name
            save_config(config)
    print(f"ctflow · {client.url} · reviewer: {client.reviewer or '-'} · `help` lists commands")
    status = OK
    while True:
        try:
            line = input(f"ctflow[{client.project or '-'}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if readline is not None and not _PATH.search(line):
            readline.add_history(line)
        words = line.split()
        if words[0] in {"exit", "quit"}:
            break
        try:
            plan = words[0] == "plan"
            if plan:
                line = line.split(None, 1)[1] if len(words) > 1 else ""
            # In the console, starting work returns at once; `attach` follows it.
            status = run_line(client, line, detach=True, plan=plan, as_json=False)
        except Refused as exc:
            show_problem(exc)
            status = REFUSED
        except ConnectionError as exc:
            print(f"ctflow: {exc}", file=sys.stderr)
            status = REFUSED
    if readline is not None:
        try:
            CONFIG.mkdir(parents=True, exist_ok=True)
            readline.write_history_file(history)
        except OSError:
            pass
    return status


def main(argv: list[str]) -> int:
    url = reviewer = project = command = None
    detach = plan = as_json = False
    i = 0
    while i < len(argv) and argv[i].startswith("-"):
        flag = argv[i]
        if flag in {"-h", "--help"}:
            print(__doc__)
            return OK
        if flag in {"--detach", "--plan", "--json"}:
            detach |= flag == "--detach"
            plan |= flag == "--plan"
            as_json |= flag == "--json"
            i += 1
            continue
        if flag not in {"--url", "--reviewer", "-p", "--project", "-c"} or i + 1 >= len(argv):
            print(f"ctflow: unknown or incomplete option {flag}; see ctflow --help", file=sys.stderr)
            return REFUSED
        value = argv[i + 1]
        if flag == "--url":
            url = value
        elif flag == "--reviewer":
            reviewer = value
        elif flag in {"-p", "--project"}:
            project = value
        else:
            command = value
        i += 2
    rest = argv[i:]
    script_file = None
    if command is None and len(rest) == 1 and rest[0].endswith(".ctf"):
        try:
            command = script_file = Path(rest[0]).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"ctflow: cannot read {rest[0]}: {exc.strerror}", file=sys.stderr)
            return REFUSED
    if command is None and rest:
        # the server groups words with "…" (not shell quotes)
        command = " ".join(f'"{w}"' if any(c.isspace() for c in w) else w for w in rest)
    config = load_config()
    name = reviewer or os.environ.get("CTFLOW_REVIEWER") or config.get("reviewer")
    client = Client(server_url(url), name, project, "terminal")
    if command is None:
        return console(client, config)
    try:
        if script_file is not None and not plan:
            return run_script(client, script_file, Path(rest[0]).stem, detach=detach)
        return run_line(client, command, detach=detach, plan=plan, as_json=as_json)
    except Refused as exc:
        show_problem(exc)
        return REFUSED
    except ConnectionError as exc:
        print(f"ctflow: {exc}", file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
