"""Backend side of the run protocol: write `job.json`, tail `progress.jsonl`, read `result.json`.
The backend writes only `job.json` and `cancel`, plus `pause` and `control.json` for supervised
runs; the supervisor answers with `control-ack.json`."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.fsio import atomic_write_json

PROTOCOL = 1
JOB, PROGRESS, RESULT, CANCEL, CLAIM, LOG, EXIT = (
    "job.json",
    "progress.jsonl",
    "result.json",
    "cancel",
    "claim",
    "task.log",
    "exit.json",  # the runner's record of the exit code (external runtime)
)
LOG_TAIL = 4000


def write_job(job_dir: Path, spec: dict[str, Any]) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(job_dir / JOB, {"protocol": PROTOCOL, **spec})


def request_cancel(job_dir: Path) -> None:
    (job_dir / CANCEL).touch(exist_ok=True)


@dataclass
class Tail:
    """Incremental reader of `progress.jsonl` (complete lines only)."""

    path: Path
    offset: int = 0
    include_offsets: bool = False

    def read(self) -> list[dict[str, Any]]:
        try:
            with self.path.open("rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
        except FileNotFoundError:
            return []
        end = data.rfind(b"\n")
        if end < 0:
            return []
        cursor = self.offset
        self.offset += end + 1
        out: list[dict[str, Any]] = []
        for raw in data[: end + 1].splitlines(keepends=True):
            cursor += len(raw)
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue  # a task bug must not break the relay
            if isinstance(obj, dict):
                if self.include_offsets:
                    obj["_offset"] = cursor
                out.append(obj)
        return out


def read_result(job_dir: Path) -> dict[str, Any] | None:
    return _json(job_dir / RESULT)


def external_finished(job_dir: Path) -> bool:
    attempt = read_attempt(job_dir)
    if attempt is not None:
        outcome = read_exit(job_dir)
        return bool(
            outcome
            and outcome.get("cleanup_verified") is True
            and outcome.get("attempt") == attempt.get("attempt")
        )
    return (job_dir / RESULT).is_file() or (job_dir / EXIT).is_file()


def log_tail(job_dir: Path) -> str:
    p = job_dir / LOG
    try:
        return p.read_text(encoding="utf-8", errors="replace")[-LOG_TAIL:]
    except OSError:
        return ""


def _json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def read_claim(job_dir: Path) -> dict[str, Any] | None:
    """`claim` (runner_id, pid, at); `{}` while the runner is still writing it."""
    p = job_dir / CLAIM
    if not p.exists():
        return None
    return _json(p) or {}


def read_exit(job_dir: Path) -> dict[str, Any] | None:
    return _json(job_dir / EXIT)


def read_attempt(job_dir: Path) -> dict[str, Any] | None:
    """The supervisor's `attempt.json` (attempt generation, state); None before launch."""
    return _json(job_dir / "attempt.json")
