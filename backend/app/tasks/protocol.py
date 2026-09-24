"""Backend side of the run protocol (TASKS.md §Protocol): write `job.json`, tail `progress.jsonl`,
read `result.json`. The backend writes only `job.json` and `cancel` (TSK-11)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.fsio import atomic_write_json

PROTOCOL = 1
JOB, PROGRESS, RESULT, CANCEL, CLAIM, LOG = (
    "job.json",
    "progress.jsonl",
    "result.json",
    "cancel",
    "claim",
    "task.log",
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
        self.offset += end + 1
        out: list[dict[str, Any]] = []
        for raw in data[: end + 1].splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue  # a task bug must not break the relay
            if isinstance(obj, dict):
                out.append(obj)
        return out


def read_result(job_dir: Path) -> dict[str, Any] | None:
    p = job_dir / RESULT
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def log_tail(job_dir: Path) -> str:
    p = job_dir / LOG
    try:
        return p.read_text(encoding="utf-8", errors="replace")[-LOG_TAIL:]
    except OSError:
        return ""
