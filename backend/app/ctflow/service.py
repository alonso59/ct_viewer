"""A console line or script → the same service calls the GUI makes (CTF-02).

The script language (`lang`) evaluates the text; every CTFlow command it reaches comes here. Task
commands come from the loaded task manifests (CTF-03); targets go through the shared resolver
(CTF-04..06). Nothing here writes run files, submits jobs or picks output paths."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import NotFound, Problem, ValidationProblem
from app.core.ids import new_ulid
from app.core.reviewer import Origin
from app.ctflow.lang import LIMITS, Interp, Proc, ScriptError, format_list
from app.ctflow.library import Library
from app.ctflow.models import (
    CommandInfo,
    CommandResult,
    EvalError,
    EvalPlan,
    EvalRequest,
    EvalResult,
    OptionInfo,
    ResolvedTarget,
    WorkRef,
)
from app.ctflow.parse import FLAG, Line, options_of
from app.ctflow.runs import ACTIVE, ScriptRuns
from app.ctflow.sessions import Session
from app.tasks.dry_run import DICOM_CONVERT
from app.tasks.logs import redactor
from app.tasks.models import (
    TERMINAL_TASK_RUN,
    PreflightRequest,
    TaskInfo,
    TaskManifest,
    TaskRunRequest,
)
from app.tasks.source_batches import BatchReassign, SourceBatches, view_of
from app.tasks.source_operations import (
    SourceOperationControl,
    SourceOperationConvert,
    SourceOperations,
    SourceOperationStart,
)
from app.tasks.targets import TargetOptions, resolve

ITEMS_SHOWN = 50
STEPS_SHOWN = 500
# Plan mode: what a command that would act returns; a later command that uses it cannot be planned.
PLANNED = "planned:"
TARGET_OPTIONS = [
    OptionInfo(
        name="seg", type="string", help="Segmentation set to read; `default` = the project's"
    ),
    OptionInfo(name="labels", type="list", help="Labels to extract, by name or value (radiomics)"),
    OptionInfo(name="scope", type="string", enum=["complete", "voi"], help="Only these items"),
    OptionInfo(name="phase", type="list", help="Only items of these phases"),
    OptionInfo(name="name", type="string", help="Name of the run or dataset"),
]
_TARGET_KEYS = {o.name for o in TARGET_OPTIONS}
CORE = {
    "project": ("project [id]", "Show or choose the session's current project"),
    "help": ("help [command]", "List the commands, or one command's options"),
    "cases": ("cases [-phase P]", "List the active cases of the project"),
    "runs": ("runs", "List the project's task runs"),
    "status": ("status <run or operation>", "Show one run or source operation"),
    "cancel": ("cancel <run or operation>", "Cancel a run, source operation or script run"),
    "pause": ("pause <script run>", "Pause a script run (and its supervised child)"),
    "resume": (
        "resume <run or operation> [-failed]",
        "Resume a run or source operation (a script run replays its journal)",
    ),
    "retry": ("retry <run or operation>", "Run only the failed items again (resume -failed)"),
    "diagnose": ("diagnose <run or operation>", "Counts and the most frequent failure messages"),
    "batches": ("batches", "List the batch plans"),
    "batch": (
        "batch <plan> [start | continue | cancel | reassign <index> <operation>]",
        "Show a batch plan, or start, continue, cancel it or replace a batch's operation",
    ),
    "wait": ("wait <run or operation>", "In a script run: wait until the run ends"),
    "scripts": ("scripts", "List the library scripts (project, workspace, shipped)"),
    "save": ("save <proc> [-project]", "Save a session procedure as <proc>.ctf in the library"),
    "convert": ("convert <operation>", "Convert a DICOM source whose analysis is ready"),
}
_SCALARS = {"string", "integer", "number", "boolean"}


@dataclass
class Call:
    """One request: its context and what its commands did, in order."""

    project: str | None
    plan: bool
    origin: Origin
    reviewer: str | None
    procs: dict[str, Proc] = field(default_factory=dict)  # the session's, for `save`
    starts: int = 0
    steps: list[CommandResult] = field(default_factory=list)
    text: list[str] = field(default_factory=list)


class _PlanStop(Exception):
    def __init__(self, name: str) -> None:
        self.name = name


def error_of(exc: ScriptError | Problem) -> EvalError:
    if isinstance(exc, ScriptError):
        return EvalError(title="script error", detail=exc.message, line=exc.line)
    return EvalError(
        title=exc.slug, detail=str(exc), errors=exc.errors or [], actions=exc.actions or []
    )


def _control_of(record: Any) -> SourceOperationControl:
    """The fences of a source operation as just read."""
    return SourceOperationControl(
        expected_revision=record.revision,
        expected_attempt=record.attempt,
        expected_run_attempt=record.conversion_run.attempts if record.conversion_run else None,
    )


def _command_name(m: TaskManifest) -> str:
    return m.command.name if m.command else m.id


def _settings_options(m: TaskManifest) -> list[OptionInfo]:
    spelled = {key: alias for alias, key in (m.command.options if m.command else {}).items()}
    out = []
    for key, prop in (m.settings_schema.get("properties") or {}).items():
        kind = prop.get("type")
        if kind == "array" and (prop.get("items") or {}).get("type") in _SCALARS:
            kind = "list"
        if kind not in _SCALARS | {"list"}:
            continue  # nested objects stay with the settings form
        out.append(
            OptionInfo(
                name=spelled.get(key, key.replace("_", "-")),
                type=kind,
                help=prop.get("x-help") or prop.get("description") or prop.get("title") or "",
                enum=prop.get("enum") or (prop.get("items") or {}).get("enum"),
                default=m.defaults.get(key, prop.get("default")),
                setting=key,
            )
        )
    return out


def _number(raw: str) -> int | float:
    """`100` stays an integer, as the GUI's JSON sends it, so the settings hash the same."""
    try:
        return int(raw)
    except ValueError:
        return float(raw)


def _coerce(option: OptionInfo, raw: str, schema: dict[str, Any]) -> Any:
    try:
        if option.type == "boolean":
            low = raw.lower()
            if low not in {"true", "false", "1", "0", "yes", "no"}:
                raise ValueError
            return low in {"true", "1", "yes"}
        if option.type == "integer":
            return int(raw)
        if option.type == "number":
            return _number(raw)
        if option.type == "list":
            item = (schema.get("items") or {}).get("type")
            parts = [p for p in raw.split(",") if p]
            return [
                int(p) if item == "integer" else _number(p) if item == "number" else p
                for p in parts
            ]
    except ValueError:
        raise ValidationProblem(
            f"-{option.name} expects a {option.type}",
            errors=[{"loc": ["option", option.name], "msg": f"not a {option.type}: {raw}"}],
        ) from None
    return raw


class Console:
    def __init__(
        self, operations: SourceOperations, runs: ScriptRuns, batches: SourceBatches
    ) -> None:
        self.operations, self.runs, self.batches = operations, runs, batches
        self.tasks = operations.tasks
        self.library = Library(self.tasks.settings, self.tasks.workspace)
        runs.console = self

    # --- catalog -------------------------------------------------------------------------------

    def _by_name(self) -> dict[str, TaskInfo]:
        """Every task by its command name and by its id; core names win (they are reserved)."""
        out: dict[str, TaskInfo] = {}
        for info in self.tasks.registry.tasks.values():
            out[info.manifest.id] = info
            if info.manifest.command and info.manifest.command.name not in CORE:
                out[info.manifest.command.name] = info
        return out

    def commands(self) -> list[CommandInfo]:
        core = [CommandInfo(name=n, usage=u, summary=s) for n, (u, s) in CORE.items()]
        listed = []
        for raw in self.tasks.registry.tasks.values():
            m = raw.manifest
            if m.test_only:
                continue  # callable by id, not listed (as in the Tasks view)
            info = self.tasks.get(m.id)
            target = "<source>" if m.input == "source" else "[case | item | path | all]"
            listed.append(
                CommandInfo(
                    name=_command_name(m),
                    task_id=m.id,
                    summary=m.title,
                    usage=f"{_command_name(m)} {target} [-option value …]",
                    options=[
                        *(o for o in TARGET_OPTIONS if m.input != "source" or o.name == "name"),
                        *_settings_options(m),
                    ],
                    available=info.available,
                    reason=info.unavailable_reason,
                )
            )
        return core + sorted(listed, key=lambda c: c.name)

    # --- evaluation ----------------------------------------------------------------------------

    async def eval(self, req: EvalRequest, reviewer: str | None, session: Session) -> EvalResult:
        call = Call(
            project=req.project_id or session.project,
            plan=req.plan,
            origin=Origin(client=req.client),
            reviewer=reviewer,
            procs=session.procs,
        )
        by_name = self._by_name()

        async def run_command(words: list[str]) -> str:
            line = options_of(words)
            if call.plan and any(PLANNED in w for w in words):
                raise _PlanStop(line.name)
            if line.name == "wait":
                raise ValidationProblem(
                    "wait works inside a script run; in the console, follow with ctflow attach"
                )
            step = await self.dispatch(line, call, by_name)
            if step.started is not None:
                call.starts += 1
            call.steps.append(step)
            call.text.extend(step.text)
            if call.starts > LIMITS.starts:
                raise ScriptError(f"a line may start at most {LIMITS.starts} runs")
            return step.value

        result = EvalResult(session=session.id)
        async with session.lock:
            interp = Interp(
                session.vars,
                session.procs,
                run_command,
                self.is_command,
                self.source(call),
                call.text,
            )
            try:
                result.value = await interp.run(req.line)
            except _PlanStop as stop:
                result.plan_stopped = (
                    f"{stop.name} uses the result of a command that plan mode does not run;"
                    " the plan stops there"
                )
            except (ScriptError, Problem) as exc:
                if not call.steps and not call.text:
                    if isinstance(exc, Problem):
                        raise
                    where = f"line {exc.line}: " if exc.line else ""
                    raise ValidationProblem(f"{where}{exc.message}") from None
                result.error = error_of(exc)
            session.project = call.project
        result.project_id, result.text = call.project, call.text
        result.steps = call.steps[:STEPS_SHOWN]
        return result

    def is_command(self, name: str) -> bool:
        return name in CORE or name in self._by_name()

    async def dispatch(self, line: Line, call: Call, by_name: dict[str, TaskInfo]) -> CommandResult:
        if line.name in CORE:
            return await self._core(line, call)
        info = by_name.get(line.name)
        if info is None:
            raise NotFound(f"Unknown command {line.name!r}; `help` lists them")
        return await self._task(info.manifest, line, call)

    def source(self, call: Call) -> Callable[[str], str]:
        """`source`: a library script (project, workspace, shipped), never an arbitrary file."""

        def read(name: str) -> str:
            try:
                return self.library.read(name, call.project).text
            except Problem as exc:
                raise ScriptError(str(exc)) from None

        return read

    async def _task(self, m: TaskManifest, line: Line, call: Call) -> CommandResult:
        if len(line.args) > 1:
            raise ValidationProblem(f"{line.name} takes one target; quote a path with spaces")
        settings = self._settings(m, line.options)
        opts = TargetOptions(
            seg=line.options.get("seg"),
            labels=[w for w in line.options.get("labels", "").split(",") if w],
            scope=line.options.get("scope"),
            phase=[w for w in line.options.get("phase", "").split(",") if w],
        )
        pid = call.project
        target = resolve(self.tasks, pid, m, line.args[0] if line.args else None, opts)
        shown = ResolvedTarget(
            kind=target.kind,
            project_id=pid,
            n_items=len(target.item_ids),
            item_ids=target.item_ids[:ITEMS_SHOWN],
            seg_id=target.selection.seg_id,
            labels=target.selection.labels,
        )
        result = CommandResult(command=line.name, task_id=m.id, target=shown)
        name = line.options.get("name")
        if call.plan:
            check = self.tasks.validate(m.id, settings, target.selection.labels or None)
            plan = EvalPlan(ok=check.ok, issues=check.issues, settings=check.settings)
            ready = ""
            if pid is not None and check.ok:
                plan.preflight = await self.tasks.preflight(
                    pid, m.id, PreflightRequest(selection=target.selection, settings=settings)
                )
                ready = f", ready {plan.preflight.n_ready} of {plan.preflight.n_selected}"
            result.plan, result.value = plan, f"{PLANNED}{m.id}"
            verdict = "ok" if plan.ok else "settings need changes"
            result.text = [f"plan {line.name}: {verdict}{ready}"]
            return result
        if m.id == DICOM_CONVERT:
            # As the converter window: a durable analysis first, then `convert` (API-69).
            script = call.origin.script_run_id
            # in a script run the key is the journaled call, so a replay finds the same operation
            key = f"ctflow-{script}-{call.origin.step}" if script else f"ctflow-{new_ulid()}"
            op = await self.operations.start(
                SourceOperationStart(
                    path=str(target.selection.source),
                    idempotency_key=key,
                    project_id=pid,
                    purpose="convert",
                    prepare_plan=True,
                    settings=settings,
                    name=name,
                ),
                call.reviewer,
                call.origin,
            )
            result.started = WorkRef(
                kind="source-operation", id=op.operation_id, job_id=op.job_id,
                status=op.status, project_id=pid,
            )  # fmt: skip
            result.value = op.operation_id
            result.text = [
                f"analysis {op.operation_id} {op.status}; then: convert {op.operation_id}"
            ]
            return result
        if pid is None:
            raise ValidationProblem(f"{m.id} needs a project", actions=["choose_project"])
        started = await self.tasks.start(
            pid,
            TaskRunRequest(task_id=m.id, settings=settings, selection=target.selection, name=name),
            call.reviewer,
            call.origin,
        )
        result.started = WorkRef(
            kind="task-run", id=started.run_id, job_id=started.job_id,
            status=started.status, project_id=pid,
        )  # fmt: skip
        result.value = started.run_id
        result.text = [f"{m.id} run {started.run_id} {started.status} ({shown.n_items} items)"]
        return result

    def _settings(self, m: TaskManifest, options: dict[str, str]) -> dict[str, Any]:
        known = {o.name: o for o in _settings_options(m)}
        props = m.settings_schema.get("properties") or {}
        out: dict[str, Any] = {}
        for key, raw in options.items():
            if key in _TARGET_KEYS:
                if raw == FLAG:
                    raise ValidationProblem(f"-{key} needs a value")
                continue
            option = known.get(key) or known.get(key.replace("_", "-"))
            if option is None or option.setting is None:
                raise ValidationProblem(
                    f"{_command_name(m)} has no option -{key}",
                    errors=[{"loc": ["option", key], "msg": "unknown option"}],
                )
            out[option.setting] = _coerce(option, raw, props[option.setting])
        return out

    # --- core commands -------------------------------------------------------------------------

    async def _core(self, line: Line, call: Call) -> CommandResult:
        result = CommandResult(command=line.name)
        arg = line.args[0] if line.args else None
        if line.name == "project":
            if arg is not None:
                project = self.tasks.workspace.get(arg)  # unknown or archived: a problem
                call.project = project.project_id
            result.value = call.project or ""
            result.text = [f"project: {call.project or 'none'}"]
            return result
        if line.name == "scripts":
            scripts = self.library.list(call.project)
            result.data = [s.model_dump(mode="json") for s in scripts]
            result.value = format_list([s.name for s in scripts])
            result.text = [f"{s.name}  {s.scope}  {s.summary}" for s in scripts]
            return result
        if line.name == "save":
            return self._save(result, line, call)
        acting_batch = line.name == "batch" and len(line.args) > 1
        if call.plan and (line.name in {"convert", "cancel", "resume", "retry"} or acting_batch):
            result.value = f"{PLANNED}{line.name}"
            result.text = [f"plan {line.name}: would {line.name} {arg or '?'}"]
            return result
        if line.name == "help":
            commands = self.commands()
            if arg is not None:
                commands = [c for c in commands if arg in (c.name, c.task_id)]
                if not commands:
                    raise NotFound(f"Unknown command {arg!r}")
            result.data = [c.model_dump(mode="json") for c in commands]
            result.text = [f"{c.usage}  — {c.summary}" for c in commands]
            result.value = format_list([c.name for c in commands])
            if arg is not None:
                result.text += [f"  -{o.name} ({o.type})  {o.help}" for o in commands[0].options]
            return result
        if line.name == "batches":
            plans = self.batches.plans()
            result.data = [view_of(p).model_dump(mode="json") for p in plans]
            result.value = format_list([p.plan_id for p in plans])
            result.text = [f"{p.plan_id}  {p.status}  {p.name}" for p in plans]
            return result
        if line.name == "batch":
            return await self._batch(result, line)
        if line.name in {"status", "cancel", "pause", "resume", "retry", "diagnose"}:
            if arg is None:
                raise ValidationProblem(f"Name the run or operation: {line.name} <id>")
            if line.name == "status":
                return await self._status(result, arg, call.project)
            if line.name == "cancel":
                return await self._cancel(result, arg, call.project)
            if line.name == "diagnose":
                return await self._diagnose(result, arg, call.project)
            if line.name in {"resume", "retry"}:
                failed = line.name == "retry" or "failed" in line.options
                return await self._resume(result, arg, call.project, failed)
            run = await (
                self.runs.resume(arg) if line.name == "resume" else self.runs.control(arg, "pause")
            )
            result.work = WorkRef(kind="script-run", id=arg, job_id=run.job_id, status=run.status)
            result.value, result.text = run.status, [f"{arg}  {run.status}"]
            return result
        if line.name == "convert":
            if arg is None:
                raise ValidationProblem("Name the operation: convert <operation>")
            op = await self.operations.view(arg)
            converted = await self.operations.convert(
                arg,
                SourceOperationConvert(
                    expected_revision=op.revision,
                    expected_attempt=op.attempt,
                    inventory_generation=str(op.summary.get("generation")),
                    plan_attempt=int(op.plan_attempt or 1),
                ),
                call.reviewer,
            )
            result.value = arg
            result.started = WorkRef(
                kind="source-operation", id=arg, job_id=converted.job_id,
                status=converted.status, project_id=converted.project_id,
            )  # fmt: skip
            result.text = [f"conversion of {arg} {converted.status}"]
            return result
        pid = call.project
        if pid is None:
            raise ValidationProblem(f"{line.name} needs a project", actions=["choose_project"])
        if line.name == "cases":
            phases = [w for w in line.options.get("phase", "").split(",") if w]
            items = [
                i
                for i in self.tasks.store.load(pid).items
                if i.status == "active" and (not phases or i.phase.canonical in phases)
            ]
            counts = Counter(i.case_id for i in items)
            result.data = [{"case_id": c, "n_items": n} for c, n in sorted(counts.items())]
            result.text = [f"{c}  {n} items" for c, n in sorted(counts.items())]
            result.value = format_list(sorted(counts))
            return result
        runs = await self.tasks.list_runs(pid)
        result.data = [
            r.model_dump(mode="json", include={"run_id", "task", "status", "name"}) for r in runs
        ]
        result.text = [f"{r.run_id}  {r.task.id}  {r.status}" for r in runs]
        result.value = format_list([r.run_id for r in runs])
        return result

    def _save(self, result: CommandResult, line: Line, call: Call) -> CommandResult:
        name = line.args[0] if line.args else ""
        proc = call.procs.get(name)
        if proc is None:
            raise ValidationProblem(f"No procedure {name!r} in this session; define it with proc")
        project = call.project if "project" in line.options else None
        if "project" in line.options and project is None:
            raise ValidationProblem("save -project needs a project", actions=["choose_project"])
        text = (
            f"# {name}: saved from the console\n"
            f"proc {name} {{{format_list(proc.params)}}} {{{proc.body}}}\n"
        )
        if call.plan:
            result.value, result.text = f"{PLANNED}save", [f"plan save: would save {name}.ctf"]
            return result
        saved = self.library.save(f"{name}.ctf", text, project)
        result.value, result.text = saved.name, [f"saved {saved.name} ({saved.scope})"]
        return result

    async def find_work(self, ref: str, pid: str | None) -> tuple[WorkRef, Any]:
        """A script run, else a project run (with a project), a source operation or a workspace
        run."""
        try:
            script = self.runs.get(ref)
        except NotFound:
            pass
        else:
            return WorkRef(
                kind="script-run", id=ref, job_id=script.job_id, status=script.status,
                project_id=script.project_id,
            ), script  # fmt: skip
        if pid is not None:
            try:
                run = await self.tasks.get_run(pid, ref)
            except NotFound:
                pass
            else:
                return WorkRef(
                    kind="task-run", id=ref, job_id=run.job_id, status=run.status, project_id=pid
                ), run
        try:
            op = await self.operations.view(ref)
        except NotFound:
            ws = self.operations.workspace_tasks.get(ref)  # raises not-found itself
            return WorkRef(kind="workspace-run", id=ref, job_id=ws.job_id, status=ws.status), ws
        return WorkRef(
            kind="source-operation", id=ref, job_id=op.job_id, status=op.status,
            project_id=op.project_id,
        ), op  # fmt: skip

    async def _status(self, result: CommandResult, ref: str, pid: str | None) -> CommandResult:
        work, record = await self.find_work(ref, pid)
        result.work, result.data = work, record.model_dump(mode="json")
        stage = f"  {record.stage}" if work.kind == "source-operation" else ""
        result.text = [f"{work.id}  {work.kind}{stage}  {work.status}"]
        result.value = work.status
        return result

    async def _cancel(self, result: CommandResult, ref: str, pid: str | None) -> CommandResult:
        work, _ = await self.find_work(ref, pid)
        work.status = await self.cancel_work(work)
        result.work, result.text = work, [f"{work.id}  {work.status}"]
        result.value = work.status
        return result

    async def _resume(
        self, result: CommandResult, ref: str, pid: str | None, failed: bool
    ) -> CommandResult:
        work, record = await self.find_work(ref, pid)
        if work.kind == "script-run":
            if failed:
                raise ValidationProblem("A script run replays its journal; it has no failed items")
            run = await self.runs.resume(ref)
            work.status = run.status
        elif work.kind == "source-operation":
            control = _control_of(record)
            work.status = (await self.operations.resume(ref, control, failed_only=failed)).status
        else:
            if work.kind == "task-run":
                assert pid is not None
                started = await self.tasks.resume(
                    pid, ref, expected_attempt=record.attempts, failed_only=failed
                )
            else:
                started = await self.operations.workspace_tasks.resume(
                    ref, expected_attempt=record.attempts, failed_only=failed
                )
            work.status = started.status
        result.work, result.text = work, [f"{work.id}  {work.status}"]
        result.value = work.status
        return result

    async def _diagnose(self, result: CommandResult, ref: str, pid: str | None) -> CommandResult:
        work, record = await self.find_work(ref, pid)
        if work.kind == "script-run":
            raise ValidationProblem("diagnose takes a run or a source operation")
        error, counts, errors = record.error, record.counts, []
        if work.kind == "source-operation":
            run = record.conversion_run
            counts = run.counts if run else {}
            if run and record.project_id:
                errors = self.tasks.errors(record.project_id, run.run_id)
        elif work.kind == "task-run":
            assert pid is not None
            errors = self.tasks.errors(pid, ref)
        counts = counts if isinstance(counts, dict) else counts.model_dump()
        red = redactor(self.tasks.settings, None)
        by_message: dict[str, list[str]] = {}
        for e in errors:
            by_message.setdefault(red.text(e.message or e.status), []).append(e.item_id)
        top = sorted(by_message.items(), key=lambda kv: -len(kv[1]))[:3]
        result.work = work
        result.data = {
            "status": work.status,
            "counts": counts,
            "error": red.text(error) if error else None,
            "failures": [{"message": m, "n": len(ids), "example": ids[0]} for m, ids in top],
        }
        result.value = work.status
        result.text = [
            f"{work.id}  {work.kind}  {work.status}",
            "  ".join(f"{k} {v}" for k, v in counts.items()),
            *([f"error: {red.text(error)}"] if error else []),
            *(f"{len(ids)}x {m}  (e.g. {ids[0]})" for m, ids in top),
        ]
        return result

    async def _batch(self, result: CommandResult, line: Line) -> CommandResult:
        if not line.args:
            raise ValidationProblem("Name the plan: batch <plan> [start | continue | cancel | …]")
        plan_id, action = line.args[0], (line.args[1] if len(line.args) > 1 else None)
        if action is None:
            plan = self.batches.get(plan_id)
        elif action == "start":
            plan = await self.batches.start(plan_id)
        elif action == "continue":
            plan = await self.batches.resume_plan(plan_id)
        elif action == "cancel":
            plan = await self.batches.cancel(plan_id)
        elif action == "reassign":
            if len(line.args) != 4 or not line.args[2].isdigit():
                raise ValidationProblem("Usage: batch <plan> reassign <index> <operation>")
            current = self.batches.get(plan_id)
            plan = await self.batches.reassign(
                plan_id,
                int(line.args[2]),
                BatchReassign(operation_id=line.args[3], expected_revision=current.revision),
            )
        else:
            raise ValidationProblem(f"batch {plan_id}: unknown action {action!r}")
        view = view_of(plan)
        result.data, result.value = view.model_dump(mode="json"), plan.status
        result.text = [f"{plan.plan_id}  {plan.status}  {plan.name}"] + [
            f"  {b.index}  {b.status}  {b.name}  {b.operation_id or '-'}" for b in view.batches
        ]
        return result

    async def cancel_work(self, work: WorkRef) -> str:
        """Cancel through the work's own controls; returns its status."""
        pid, ref = work.project_id, work.id
        if work.kind == "script-run":
            return (await self.runs.control(ref, "cancel")).status
        if work.kind == "task-run":
            assert pid is not None
            return (await self.tasks.cancel(pid, ref)).status
        if work.kind == "workspace-run":
            return (await self.operations.workspace_tasks.cancel(ref)).status
        record = await self.operations.view(ref)
        return (await self.operations.cancel(ref, _control_of(record))).status

    @staticmethod
    def is_over(work: WorkRef) -> bool:
        if work.kind == "script-run":
            return work.status not in ACTIVE
        return work.status in TERMINAL_TASK_RUN

    async def find_started(self, pid: str | None, rid: str, step: int) -> CommandResult | None:
        """The run a script run's journaled call started before the server stopped, if any."""
        if pid is None:
            return None
        for run in await self.tasks.list_runs(pid):
            origin = run.origin
            if origin and origin.script_run_id == rid and origin.step == step:
                return CommandResult(
                    command=run.task.id, task_id=run.task.id, value=run.run_id,
                    started=WorkRef(
                        kind="task-run", id=run.run_id, job_id=run.job_id,
                        status=run.status, project_id=pid,
                    ),
                    text=[f"{run.task.id} run {run.run_id} {run.status} (found after a restart)"],
                )  # fmt: skip
        return None
