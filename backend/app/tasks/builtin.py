"""Builtin runtime (ADR-0016 §3): the task entry runs in a job worker process (BE-06).

The entry is `run(job_dir) -> int` and follows the same protocol as an external task (TSK-07).
"""

from __future__ import annotations

import importlib
import traceback
from pathlib import Path
from typing import Any

from app.tasks.protocol import LOG


def run_entry(entry: str, job_dir: str) -> dict[str, Any]:
    """Worker unit. Never raises: a crash is an exit code plus `task.log` (§Protocol)."""
    module, _, name = entry.partition(":")
    try:
        fn = getattr(importlib.import_module(module), name)
        code = fn(job_dir)
        return {"exit_code": int(code or 0)}
    except BaseException:
        (Path(job_dir) / LOG).write_text(traceback.format_exc(), encoding="utf-8")
        return {"exit_code": 1}
