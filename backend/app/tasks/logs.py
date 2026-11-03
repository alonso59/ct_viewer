"""Readable, redacted output of a source operation, a workspace run or a project run.

The cursor is opaque to clients: it binds the attempt and the byte offsets already read from the
attempt's `progress.jsonl` and `task.log`, so each poll returns only new lines. `log.jsonl` is not
read there: it relays the same `log` rows of `progress.jsonl`.

A project run's job folder is deleted when it ends, so its output is read from the run record's
own files instead: the relayed `log.jsonl` and the failures in `items.jsonl` (a radiomics run:
the failures in `errors.jsonl`). They span every attempt, so the cursor binds the run."""

from __future__ import annotations

import base64
import binascii
import json
import re
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel

from app.config import Settings
from app.core.errors import ValidationProblem
from app.core.redact import Redactor
from app.radiomics.service import ERRORS
from app.tasks import protocol
from app.tasks.models import TERMINAL_TASK_RUN
from app.tasks.records import ITEMS, LOGS
from app.tasks.service import TaskService
from app.tasks.source_operations import SourceOperations

LIMIT: Final = 500
MAX_BYTES: Final = 256 * 1024
TEXT_MAX: Final = 2000
LogKind = Literal["source-operation", "workspace-run", "project-run"]
Level = Literal["info", "warn", "error"]
# Absolute paths outside every known root (library frames of a traceback, for example).
_ABSOLUTE = re.compile(r"(?<![\w.\-~:/])/[^\s\"'`]+")


class LogLine(BaseModel):
    ts: str | None = None
    level: Level = "info"
    stream: Literal["stage", "log", "stderr"]
    text: str


class LogPage(BaseModel):
    lines: list[LogLine]
    next_cursor: str
    done: bool


def _elide(match: re.Match[str]) -> str:
    name = match.group(0).rsplit("/", 1)[-1]
    return f"…/{name}" if name.endswith(".py") else "…"


def _encode(key: str, offsets: list[int]) -> str:
    raw = json.dumps({"a": key, "o": offsets}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cursor: str | None) -> tuple[str | None, list[int]]:
    if not cursor:
        return None, [0, 0]
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        key, offsets = raw["a"], raw["o"]
    except (binascii.Error, ValueError, TypeError, KeyError):
        raise ValidationProblem("Invalid log cursor") from None
    if (
        not isinstance(key, str)
        or not isinstance(offsets, list)
        or len(offsets) != 2
        or not all(type(o) is int and o >= 0 for o in offsets)
    ):
        raise ValidationProblem("Invalid log cursor")
    return key, offsets


def _chunk(path: Path, offset: int, budget: int, *, final: bool) -> list[bytes]:
    """Complete lines from `offset` within `budget` bytes (the trailing partial line too once the
    attempt ended; an over-long line is cut so the reader always advances)."""
    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read(budget)
    except OSError:
        return []
    if len(data) == budget or not final:
        end = data.rfind(b"\n")
        if end >= 0:
            data = data[: end + 1]
        elif len(data) < budget:
            return []
    return data.splitlines(keepends=True)


def _level(raw: object) -> Level:
    value = str(raw or "info").lower()
    if value in ("error", "critical"):
        return "error"
    return "warn" if value.startswith("warn") else "info"


def _counters(row: dict[str, Any]) -> str:
    return ", ".join(f"{k} {v}" for k, v in row.items() if type(v) is int)


def _render(row: dict[str, Any]) -> LogLine | None:
    t = row.get("t")
    if t == "stage":
        stage, done, total = row.get("stage") or "", row.get("done") or 0, row.get("total") or 0
        text = f"{stage} {done}/{total}" if total else str(stage)
        wait = row.get("resource_wait")
        if isinstance(wait, dict) and wait.get("reason"):
            text += f" ({wait['reason']})"
        return LogLine(stream="stage", text=text)
    if t == "inventory":
        name = row.get("stage") or "inventory"
        return LogLine(stream="stage", text=f"{name}: {_counters(row)}")
    if t == "log":
        return LogLine(
            ts=row.get("at") if isinstance(row.get("at"), str) else None,
            level=_level(row.get("level")),
            stream="log",
            text=str(row.get("message", "")),
        )
    if t == "item" and row.get("status") == "failed":
        return LogLine(level="error", stream="log", text=f"failed: {row.get('message') or ''}")
    return None


def _attempt(
    operations: SourceOperations, kind: LogKind, ref: str
) -> tuple[str, int, Path, str, bool]:
    """(attempt key, attempt number, attempt dir, source path, attempt ended)."""
    if kind == "source-operation":
        op = operations.get(ref)
        job = operations.root / op.operation_id / "attempts" / str(op.attempt)
        return str(op.attempt), op.attempt, job, op.source, op.status in TERMINAL_TASK_RUN
    runs = operations.workspace_tasks
    run = runs.get(ref)
    job = (
        runs.settings.workspace_root / "plugins" / run.plugin / "runs" / run.run_id / "attempts"
        if run.task.id == "dicom.convert"
        else runs.settings.workspace_root / ".scratch" / "jobs"
    ) / str(run.job_id)
    return str(run.job_id), run.attempts, job, run.source, run.status in TERMINAL_TASK_RUN


def redactor(
    settings: Settings,
    source: str | None,
    aliases: list[tuple[str, str]] | None = None,
    opaque: list[tuple[str, str]] | None = None,
) -> Redactor:
    """`aliases`/`opaque`: a project's own derived and source roots, named by their aliases."""
    return Redactor(
        aliases=[
            ("WORKSPACE", str(settings.workspace_root)),
            *(("DERIVED", str(d)) for d in settings.derived_roots),
            *(aliases or []),
        ],
        opaque=[
            *(opaque or []),
            *(("DATA", str(r)) for r in settings.allowed_roots),
            *([("DATA", source)] if source else []),
        ],
    )


def _clean(lines: list[LogLine], red: Redactor) -> None:
    for line in lines:
        line.text = _ABSOLUTE.sub(_elide, red.text(line.text))[:TEXT_MAX]


def read_logs(
    operations: SourceOperations,
    kind: LogKind,
    ref: str,
    cursor: str | None,
    limit: int = LIMIT,
) -> LogPage:
    key, offsets = _decode(cursor)
    current, number, job, source, ended = _attempt(operations, kind, ref)
    lines: list[LogLine] = []
    if key != current:
        offsets = [0, 0]
        lines.append(LogLine(stream="stage", text=f"— attempt {number} —"))
    budget = MAX_BYTES
    # Inventory counters arrive several times a second: one line per read is enough to follow.
    inventory: int | None = None
    for raw in _chunk(job / protocol.PROGRESS, offsets[0], budget, final=ended):
        if len(lines) >= limit:
            break
        offsets[0] += len(raw)
        budget -= len(raw)
        try:
            row = json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            continue
        line = _render(row) if isinstance(row, dict) else None
        if line is None:
            continue
        if row.get("t") == "inventory":
            if inventory is not None:
                lines[inventory] = line
                continue
            inventory = len(lines)
        lines.append(line)
    # A crash traceback follows the progress it interrupted.
    if not _pending(job / protocol.PROGRESS, offsets[0]):
        for raw in _chunk(job / protocol.LOG, offsets[1], budget, final=ended):
            if len(lines) >= limit:
                break
            offsets[1] += len(raw)
            text = raw.decode("utf-8", "replace").rstrip("\r\n")
            if text.strip():
                lines.append(LogLine(level="error", stream="stderr", text=text))
    _clean(lines, redactor(operations.settings, source))
    done = ended and not any(
        _pending(job / name, offset)
        for name, offset in zip((protocol.PROGRESS, protocol.LOG), offsets, strict=True)
    )
    return LogPage(lines=lines, next_cursor=_encode(current, offsets), done=done)


def _pending(path: Path, offset: int) -> bool:
    try:
        return path.stat().st_size > offset
    except OSError:
        return False


def _run_log(row: dict[str, Any]) -> LogLine:
    return LogLine(
        ts=row.get("at") if isinstance(row.get("at"), str) else None,
        level=_level(row.get("level")),
        stream="log",
        text=str(row.get("message", "")),
    )


def _item_failure(row: dict[str, Any]) -> LogLine | None:
    if row.get("status") != "failed":
        return None
    return LogLine(
        level="error", stream="log", text=f"{row.get('item_id')} failed: {row.get('message') or ''}"
    )


def _radiomics_failure(row: dict[str, Any]) -> LogLine | None:
    if row.get("kind") != "failed":
        return None
    return LogLine(
        ts=row.get("at") if isinstance(row.get("at"), str) else None,
        level="error",
        stream="log",
        text=f"{row.get('item_id')} label {row.get('label')} failed: {row.get('error') or ''}",
    )


async def read_project_run(
    tasks: TaskService, pid: str, rid: str, cursor: str | None, limit: int = LIMIT
) -> LogPage:
    run = await tasks.get_run(pid, rid)  # settles the status; unknown project or run: not found
    run_dir = tasks.run_dir(pid, rid)
    key, offsets = _decode(cursor)
    if key != rid:
        offsets = [0, 0]
    ended = run.status in TERMINAL_TASK_RUN
    files = (
        [(run_dir / ERRORS, _radiomics_failure)]
        if run.radiomics is not None
        else [(run_dir / LOGS, _run_log), (run_dir / ITEMS, _item_failure)]
    )
    lines: list[LogLine] = []
    budget = MAX_BYTES
    for n, (path, render) in enumerate(files):
        for raw in _chunk(path, offsets[n], budget, final=ended):
            if len(lines) >= limit:
                break
            offsets[n] += len(raw)
            budget -= len(raw)
            try:
                row = json.loads(raw)
            except (UnicodeDecodeError, ValueError):
                continue
            line = render(row) if isinstance(row, dict) else None
            if line is not None:
                lines.append(line)
    roots = tasks.workspace.get(pid).path_roots
    _clean(
        lines,
        redactor(
            tasks.settings,
            None,
            aliases=[(r.alias, r.path) for r in roots if r.role == "derived"],
            opaque=[(r.alias, r.path) for r in roots if r.role != "derived"],
        ),
    )
    done = ended and not any(_pending(path, offsets[n]) for n, (path, _) in enumerate(files))
    return LogPage(lines=lines, next_cursor=_encode(rid, offsets), done=done)
