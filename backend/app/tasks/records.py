"""Task run records, constants and the service base (TSK-06..10, AUD-A6-06).

Run records live in `tasks/runs/{run_id}/` (`run.json` through the shared `jobs.runs.RunStore`,
`items.jsonl`, `log.jsonl`); the service is split along its sections, each a base class of the
next: records → selection → jobspec → estimate → registration → driver → service.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from app.config import Settings
from app.core.errors import ValidationProblem, issue_errors
from app.core.fsio import iter_jsonl
from app.core.locks import ProjectLocks
from app.events.bus import EventBus
from app.ingest.store import IndexStore
from app.jobs.manager import JobManager
from app.jobs.runs import RunStore
from app.projects.service import Workspace
from app.tasks.models import (
    RESUMABLE_TASK_RUN,
    TERMINAL_TASK_RUN,
    TaskManifest,
    TaskRunOutput,
    TaskRunRecord,
)
from app.tasks.radiomics_task import RadiomicsTask
from app.tasks.registry import Registry
from app.tasks.schema import normalize, settings_hash

TASKS: Final = "tasks"
RUNS: Final = "runs"
ITEMS: Final = "items.jsonl"  # per-item outcomes of every attempt (last line per item wins)
LOGS: Final = "log.jsonl"
LEDGER: Final = Path("derived") / "runs.jsonl"
ANNOTATIONS: Final = "annotations.jsonl"
CANCEL_GRACE_S: Final = 30.0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def item_outcomes(run_dir: Path) -> dict[str, dict[str, Any]]:
    """item_id → last outcome line over all attempts."""
    out: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(run_dir / ITEMS):
        out[str(row["item_id"])] = row
    return out


def default_seg_id(task_id: str, run_id: str) -> str:
    """`{task-short}-{run_id[:8]}` (TASKS.md §Outputs), lower-cased to the seg_id slug."""
    short = task_id.rsplit(".", 1)[-1].lower()
    return f"{short}-{run_id[:8].lower()}"


@dataclass
class Live:
    """Per-attempt driver state."""

    pid: str
    rid: str
    run_dir: Path
    job_dir: Path
    manifest: TaskManifest
    seg_id: str | None
    done: int = 0
    registered: bool = False
    outputs: list[TaskRunOutput] = field(default_factory=list)
    cancel_sent: bool = False
    dataset_dir: Path | None = None
    set_total: Callable[[int], None] | None = None


class TaskBase:
    """Dependencies, run records (`jobs.runs.RunStore`) and job folders of the task service."""

    def __init__(
        self,
        settings: Settings,
        registry: Registry,
        workspace: Workspace,
        store: IndexStore,
        jobs: JobManager,
        bus: EventBus,
        locks: ProjectLocks,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.workspace = workspace
        self.store = store
        self.jobs = jobs
        self.bus = bus
        self.locks = locks
        self.runs = RunStore(
            TaskRunRecord,
            self._runs_dir,
            jobs,
            locks,
            terminal=TERMINAL_TASK_RUN,
            resumable=RESUMABLE_TASK_RUN,
            noun="Task run",
        )

    @property
    def queue_dir(self) -> Path:
        return self.settings.workspace_root / "queue"

    def _runs_dir(self, pid: str) -> Path:
        return self.workspace.project_dir(pid) / TASKS / RUNS

    def job_dir(self, m: TaskManifest, job_id: str) -> Path:
        root = self.settings.workspace_root
        if m.runtime.type == "external":
            return root / "queue" / job_id
        return root / ".scratch" / "jobs" / job_id

    def _settings(self, m: TaskManifest, raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Authoritative validation (TSK-02): 422 with field issues, else normalized settings."""
        norm, issues = normalize(m.settings_schema, m.defaults, raw)
        errors = issue_errors(issues, ["body", "settings"])
        if errors:
            raise ValidationProblem(f"Invalid settings for {m.id}", errors=errors)
        return norm, settings_hash(m.id, m.version, norm)

    def _radiomics(self) -> RadiomicsTask:
        return RadiomicsTask(self.workspace, self.store, self.jobs, self.bus, self.locks)
