"""Durable script runs (CTF-10..14): a script that runs on the server, not in a client.

`WORKSPACE_ROOT/plugins/ctflow/runs/{run_id}/`: `run.json` (the record), `journal.jsonl` (every
CTFlow command the script called, in order, with what it returned and the run it started) and
`output.jsonl` (what the script printed). The journal plus the children's own run records are
the execution record; children stay ordinary runs and operations.

A run is a job driven here. After a server restart it is `interrupted`; resume runs the script
again from the beginning and answers every journaled call from the journal, so nothing it already
did happens twice. A start refused because the task is busy (TSK-12) waits a bounded time, then
the run moves to `attention` until it is resumed. Nothing is retried on its own.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, Field

from app.config import Settings
from app.core.errors import JobConflict, NotFound, Problem, ServerBusy, ValidationProblem
from app.core.fsio import append_jsonl, atomic_write_json, iter_jsonl, read_json
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.core.reviewer import Origin
from app.ctflow.lang import Interp, Limits, ScriptError
from app.ctflow.models import CommandResult, EvalError, WorkRef
from app.jobs.manager import JobManager
from app.jobs.types import JobHandle, JobInfo, JobSpec
from app.tasks.logs import LogPage, read_files, redactor, run_log
from app.tasks.workspace_runs import WORKSPACE_JOBS

if TYPE_CHECKING:
    from app.ctflow.service import Console

ScriptRunStatus = Literal[
    "queued", "running", "waiting", "attention", "pausing", "paused",
    "cancelling", "cancelled", "completed", "failed", "interrupted",
]  # fmt: skip
ACTIVE: Final = {"queued", "running", "waiting", "pausing", "cancelling"}
RESUMABLE: Final = {"paused", "attention", "interrupted", "failed"}
LIMITS = Limits(steps=500_000, starts=2_000)
BUSY_WAIT_S = 3600.0  # a busy task (TSK-12) is waited for this long, then `attention`
POLL_S = 1.0
SCRIPT_MAX = 100_000


class ScriptRunStart(BaseModel):
    script: str = Field(min_length=1, max_length=SCRIPT_MAX)
    name: str | None = Field(default=None, max_length=120)
    project_id: str | None = None
    client: Literal["console", "terminal"] = "console"


class JournalEntry(BaseModel):
    seq: int
    words: list[str]
    state: Literal["pending", "done", "failed"]
    value: str = ""
    child: WorkRef | None = None
    error: EvalError | None = None
    at: str


class ScriptRun(BaseModel):
    run_id: str
    name: str
    status: ScriptRunStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    reviewer: str | None = None
    origin: Origin | None = None
    project_id: str | None = None  # the project the script starts in
    script: str
    script_sha256: str
    attempts: int = 0
    job_id: str | None = None
    control: Literal["pause", "cancel"] | None = None
    waiting: str | None = None  # why a `waiting` or `attention` run is held
    error: EvalError | None = None
    value: str = ""
    calls: int = 0  # journaled CTFlow commands
    starts: int = 0  # runs and operations it started


class ScriptRunDetail(ScriptRun):
    journal: list[JournalEntry] = Field(default_factory=list)  # the last JOURNAL_SHOWN


JOURNAL_SHOWN = 200


class ReplayedProblem(Problem):
    """A refusal recorded in the journal, raised again on replay with the same words."""

    def __init__(self, error: EvalError) -> None:
        super().__init__(error.detail, errors=error.errors, actions=error.actions)
        self.slug = error.title


class _Stop(Exception):
    def __init__(self, status: ScriptRunStatus, reason: str | None = None) -> None:
        self.status, self.reason = status, reason


class _Output:
    """`puts` and command lines go to `output.jsonl`, except while the journal is replayed."""

    def __init__(self, path: Path) -> None:
        self.path, self.replaying = path, False

    def append(self, text: str) -> None:
        if not self.replaying:
            append_jsonl(self.path, [{"at": utc_now(), "level": "info", "message": text}])

    def extend(self, lines: list[str]) -> None:
        for line in lines:
            self.append(line)


class ScriptRuns:
    def __init__(self, settings: Settings, jobs: JobManager, locks: ProjectLocks) -> None:
        self.settings, self.jobs, self.locks = settings, jobs, locks
        self.root = settings.workspace_root / "plugins" / "ctflow" / "runs"
        self.console: Console | None = None  # set once the console exists (it needs us too)
        self._finished = asyncio.Event()
        jobs.on_finished.append(lambda _info: self._finished.set())

    # --- records -------------------------------------------------------------------------------

    def _dir(self, rid: str) -> Path:
        if not is_ulid(rid):
            raise NotFound(f"Script run {rid!r} not found")
        return self.root / rid

    def get(self, rid: str) -> ScriptRun:
        path = self._dir(rid) / "run.json"
        if not path.is_file():
            raise NotFound(f"Script run {rid!r} not found")
        return ScriptRun.model_validate(read_json(path))

    def detail(self, rid: str) -> ScriptRunDetail:
        journal = self.journal(rid)
        return ScriptRunDetail(**self.get(rid).model_dump(), journal=journal[-JOURNAL_SHOWN:])

    def journal(self, rid: str) -> list[JournalEntry]:
        """The last entry per sequence number wins (a pending call, then its outcome)."""
        entries: dict[int, JournalEntry] = {}
        for row in iter_jsonl(self._dir(rid) / "journal.jsonl"):
            entry = JournalEntry.model_validate(row)
            entries[entry.seq] = entry
        return [entries[k] for k in sorted(entries)]

    def all(self) -> list[ScriptRun]:
        if not self.root.is_dir():
            return []
        out = [self.get(p.name) for p in self.root.iterdir() if (p / "run.json").is_file()]
        return sorted(out, key=lambda r: r.run_id, reverse=True)

    def _write(self, run: ScriptRun) -> None:
        atomic_write_json(self._dir(run.run_id) / "run.json", run.model_dump(mode="json"))

    # --- lifecycle -----------------------------------------------------------------------------

    async def start(self, req: ScriptRunStart, reviewer: str | None) -> ScriptRun:
        from app.core import reviewer as reviewer_stamp

        if req.project_id is not None:
            self._console().tasks.workspace.get(req.project_id)  # unknown: not found
        rid = new_ulid()
        run = ScriptRun(
            run_id=rid,
            name=(req.name or "").strip() or f"script {utc_now()}",
            status="queued",
            created_at=utc_now(),
            reviewer=reviewer_stamp.optional(reviewer),
            origin=Origin(client=req.client),
            project_id=req.project_id,
            script=req.script,
            script_sha256="sha256:" + hashlib.sha256(req.script.encode()).hexdigest(),
        )
        self._dir(rid).mkdir(parents=True)
        self._write(run)
        return self._submit(run)

    def _submit(self, run: ScriptRun) -> ScriptRun:
        run.attempts += 1
        run.job_id, run.status, run.control, run.error, run.waiting = (
            new_ulid(), "queued", None, None, None,
        )  # fmt: skip
        self._write(run)

        async def driver(handle: JobHandle) -> None:
            await self._drive(run.run_id, handle)

        async def on_finish(_: JobInfo) -> str | None:
            return run.run_id

        self.jobs.submit(
            JobSpec(
                project_id=run.project_id or WORKSPACE_JOBS, kind="script", units=[],
                driver=driver, on_finish=on_finish, ref=run.run_id, job_id=run.job_id,
                key=run.run_id,
            )
        )  # fmt: skip
        return run

    async def control(self, rid: str, action: Literal["pause", "cancel"]) -> ScriptRun:
        async with self.locks(f"_ctflow:{rid}"):
            run = self.get(rid)
            if run.status in ACTIVE:
                if action == "pause" and run.control == "cancel":
                    raise JobConflict("This script run is already being cancelled")
                run.control = action
                run.status = "cancelling" if action == "cancel" else "pausing"
            elif action == "cancel" and run.status in RESUMABLE:
                run.status, run.finished_at = "cancelled", utc_now()
            elif run.status != ("cancelled" if action == "cancel" else "paused"):
                raise JobConflict(f"A {run.status} script run cannot be {action}d")
            self._write(run)
        await self._forward(run, action)
        return run

    async def resume(self, rid: str) -> ScriptRun:
        async with self.locks(f"_ctflow:{rid}"):
            run = self.get(rid)
            if run.status not in RESUMABLE:
                raise JobConflict(f"A {run.status} script run cannot be resumed")
            return self._submit(run)

    async def recover_all(self) -> None:
        """Startup: no script run survives a restart; resume replays it (CTF-12)."""
        for run in self.all():
            if run.status in ACTIVE:
                run.status = "cancelled" if run.status == "cancelling" else "interrupted"
                run.finished_at = utc_now()
                self._write(run)

    async def _forward(self, run: ScriptRun, action: Literal["pause", "cancel"]) -> None:
        """Pass the control to the child the script is waiting on, through its own controls."""
        child = next((e.child for e in reversed(self.journal(run.run_id)) if e.child), None)
        console = self._console()
        if child is None or child.kind == "script-run":
            return
        try:
            if action == "cancel":
                await console.cancel_work(child)
            elif child.kind == "task-run" and child.project_id:
                await console.tasks.pause(child.project_id, child.id)
        except Problem:
            pass  # finished already, or a run without supervised pause: dispatch still stops

    def _console(self) -> Console:
        assert self.console is not None
        return self.console

    # --- execution -----------------------------------------------------------------------------

    async def _set(self, rid: str, **changes: Any) -> ScriptRun:
        async with self.locks(f"_ctflow:{rid}"):
            run = self.get(rid)
            for key, value in changes.items():
                setattr(run, key, value)
            self._write(run)
            return run

    def _check(self, rid: str, handle: JobHandle) -> None:
        run = self.get(rid)
        if run.control == "cancel":
            raise _Stop("cancelled")
        if run.control == "pause":
            raise _Stop("paused")
        if handle.stopped:
            raise _Stop("interrupted", "the server stopped")

    async def _drive(self, rid: str, handle: JobHandle) -> None:
        from app.ctflow.service import Call, error_of

        console = self._console()
        run = await self._set(rid, status="running", started_at=utc_now())
        journal = {e.seq: e for e in self.journal(rid)}
        output = _Output(self._dir(rid) / "output.jsonl")
        output.append(f"— attempt {run.attempts} —")
        call = Call(
            project=run.project_id, plan=False, origin=Origin(client="script"),
            reviewer=run.reviewer,
        )  # fmt: skip
        by_name = console._by_name()
        seq = 0

        async def run_command(words: list[str]) -> str:
            nonlocal seq
            seq += 1
            past = journal.get(seq)
            if past is not None and past.state != "pending":
                if past.words != words:
                    raise ScriptError(
                        f"the script took another path than its journal at call {seq};"
                        " start a new run"
                    )
                output.replaying = True
                if past.state == "failed" and past.error is not None:
                    raise ReplayedProblem(past.error)
                return past.value
            output.replaying = False
            self._check(rid, handle)
            call.origin = Origin(client="script", script_run_id=rid, step=seq)
            pending = JournalEntry(seq=seq, words=words, state="pending", at=utc_now())
            append_jsonl(self._dir(rid) / "journal.jsonl", [pending.model_dump(mode="json")])
            try:
                step = await self._dispatch(console, words, call, by_name, rid, handle, past)
            except Problem as exc:
                failed = pending.model_copy(update={"state": "failed", "error": error_of(exc)})
                append_jsonl(self._dir(rid) / "journal.jsonl", [failed.model_dump(mode="json")])
                raise
            child = step.started
            done = pending.model_copy(update={"state": "done", "value": step.value, "child": child})
            append_jsonl(self._dir(rid) / "journal.jsonl", [done.model_dump(mode="json")])
            output.extend(step.text)
            await self._set(
                rid, calls=seq, starts=self.get(rid).starts + (1 if child else 0), waiting=None,
                status="running" if self.get(rid).control is None else self.get(rid).status,
            )  # fmt: skip
            if child is not None and self.get(rid).starts > LIMITS.starts:
                raise ScriptError(f"a script run may start at most {LIMITS.starts} runs")
            return step.value

        interp = Interp({}, {}, run_command, console.is_command, console.source, output, LIMITS)
        try:
            value = await interp.run(run.script)
        except _Stop as stop:
            await self._set(
                rid, status=stop.status, waiting=stop.reason, finished_at=utc_now(),
                control=None if stop.status == "attention" else self.get(rid).control,
            )  # fmt: skip
            return
        except (ScriptError, Problem) as exc:
            error = error_of(exc)
            output.replaying = False
            where = f"line {error.line}: " if error.line else ""
            output.append(f"error: {where}{error.detail}")
            await self._set(rid, status="failed", error=error, finished_at=utc_now())
            return
        await self._set(rid, status="completed", value=value, finished_at=utc_now())

    async def _dispatch(
        self,
        console: Console,
        words: list[str],
        call: Any,
        by_name: dict[str, Any],
        rid: str,
        handle: JobHandle,
        pending: JournalEntry | None,
    ) -> CommandResult:
        """One journaled call; a busy task start waits (CTF-13); `wait` follows a child."""
        from app.ctflow.parse import options_of

        line = options_of(words)
        if pending is not None and line.name in by_name:
            # The server stopped between this start and its journal line: the child, if it was
            # started, carries this run and step in its origin.
            found = await console.find_started(call.project, rid, pending.seq)
            if found is not None:
                return found
        if line.name == "wait":
            return await self._wait(console, line, call, rid, handle)
        deadline = time.monotonic() + BUSY_WAIT_S
        while True:
            try:
                return await console.dispatch(line, call, by_name)
            except (JobConflict, ServerBusy) as exc:
                if line.name not in by_name and line.name != "convert":
                    raise
                if time.monotonic() >= deadline:
                    raise _Stop(
                        "attention", f"{line.name} still busy after {int(BUSY_WAIT_S)} s; resume"
                    ) from None
                await self._set(rid, status="waiting", waiting=f"{line.name}: {exc.detail}")
                await self._idle(rid, handle, deadline)

    async def _idle(self, rid: str, handle: JobHandle, deadline: float) -> None:
        self._finished.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                self._finished.wait(), max(0.0, min(POLL_S * 5, deadline - time.monotonic()))
            )
        self._check(rid, handle)

    async def _wait(
        self, console: Console, line: Any, call: Any, rid: str, handle: JobHandle
    ) -> CommandResult:
        if not line.args:
            raise ValidationProblem("Name the run or operation: wait <id>")
        while True:
            work, record = await console.find_work(line.args[0], call.project)
            if console.is_over(work, record):
                break
            await self._set(rid, waiting=f"wait {work.id} ({work.status})")
            self._finished.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._finished.wait(), POLL_S)
            self._check(rid, handle)
        return CommandResult(
            command="wait", value=work.status, work=work, text=[f"{work.id}  {work.status}"]
        )

    # --- output --------------------------------------------------------------------------------

    def logs(self, rid: str, cursor: str | None, limit: int) -> LogPage:
        run = self.get(rid)

        red = redactor(self.settings, None)
        ended = run.status not in ACTIVE
        return read_files(
            [(self._dir(rid) / "output.jsonl", run_log)], rid, cursor, ended, red, limit
        )
