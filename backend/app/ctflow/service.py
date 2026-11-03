"""One console line → the same service calls the GUI makes (CTF-02).

Task commands come from the loaded task manifests (CTF-03); targets go through the shared
resolver (CTF-04..06). Nothing here writes run files, submits jobs or picks output paths."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.core.errors import NotFound, ValidationProblem
from app.core.ids import new_ulid
from app.core.reviewer import Origin
from app.ctflow.models import (
    CommandInfo,
    EvalPlan,
    EvalRequest,
    EvalResult,
    OptionInfo,
    ResolvedTarget,
    WorkRef,
)
from app.ctflow.parse import FLAG, Line, parse
from app.tasks.dry_run import DICOM_CONVERT
from app.tasks.models import PreflightRequest, TaskInfo, TaskManifest, TaskRunRequest
from app.tasks.source_operations import (
    SourceOperationControl,
    SourceOperationConvert,
    SourceOperations,
    SourceOperationStart,
)
from app.tasks.targets import TargetOptions, resolve

ITEMS_SHOWN = 50
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
    "help": ("help [command]", "List the commands, or one command's options"),
    "cases": ("cases [-phase P]", "List the active cases of the project"),
    "runs": ("runs", "List the project's task runs"),
    "status": ("status <run or operation>", "Show one run or source operation"),
    "cancel": ("cancel <run or operation>", "Cancel a run or source operation"),
    "convert": ("convert <operation>", "Convert a DICOM source whose analysis is ready"),
}
_SCALARS = {"string", "integer", "number", "boolean"}


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
    def __init__(self, operations: SourceOperations) -> None:
        self.operations = operations
        self.tasks = operations.tasks

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

    async def eval(self, req: EvalRequest, reviewer: str | None) -> EvalResult:
        line = parse(req.line)
        if line.name in CORE:
            return await self._core(line, req, reviewer)
        info = self._by_name().get(line.name)
        if info is None:
            raise NotFound(f"Unknown command {line.name!r}; `help` lists them")
        return await self._task(info.manifest, line, req, reviewer)

    async def _task(
        self, m: TaskManifest, line: Line, req: EvalRequest, reviewer: str | None
    ) -> EvalResult:
        if len(line.args) > 1:
            raise ValidationProblem(f"{line.name} takes one target; quote a path with spaces")
        settings = self._settings(m, line.options)
        opts = TargetOptions(
            seg=line.options.get("seg"),
            labels=[w for w in line.options.get("labels", "").split(",") if w],
            scope=line.options.get("scope"),
            phase=[w for w in line.options.get("phase", "").split(",") if w],
        )
        pid = req.project_id
        target = resolve(self.tasks, pid, m, line.args[0] if line.args else None, opts)
        shown = ResolvedTarget(
            kind=target.kind,
            project_id=pid,
            n_items=len(target.item_ids) if target.kind != "source" else 0,
            item_ids=target.item_ids[:ITEMS_SHOWN],
            seg_id=target.selection.seg_id,
            labels=target.selection.labels,
        )
        result = EvalResult(command=line.name, task_id=m.id, target=shown)
        name = line.options.get("name")
        if req.plan:
            check = self.tasks.validate(m.id, settings, target.selection.labels or None)
            plan = EvalPlan(ok=check.ok, issues=check.issues, settings=check.settings)
            if pid is not None and check.ok:
                plan.preflight = await self.tasks.preflight(
                    pid, m.id, PreflightRequest(selection=target.selection, settings=settings)
                )
            result.plan = plan
            return result
        origin = Origin(client=req.client)
        if m.id == DICOM_CONVERT:
            # As the converter window: a durable analysis first, then `convert` (API-69).
            op = await self.operations.start(
                SourceOperationStart(
                    path=str(target.selection.source),
                    idempotency_key=f"ctflow-{new_ulid()}",
                    project_id=pid,
                    purpose="convert",
                    prepare_plan=True,
                    settings=settings,
                    name=name,
                ),
                reviewer,
                origin,
            )
            result.started = WorkRef(
                kind="source-operation", id=op.operation_id, job_id=op.job_id,
                status=op.status, project_id=pid,
            )  # fmt: skip
            result.text = [
                f"analysis {op.operation_id} {op.status}; then: convert {op.operation_id}"
            ]
            return result
        if pid is None:
            raise ValidationProblem(f"{m.id} needs a project", actions=["choose_project"])
        started = await self.tasks.start(
            pid,
            TaskRunRequest(task_id=m.id, settings=settings, selection=target.selection, name=name),
            reviewer,
            origin,
        )
        result.started = WorkRef(
            kind="task-run", id=started.run_id, job_id=started.job_id,
            status=started.status, project_id=pid,
        )  # fmt: skip
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

    async def _core(self, line: Line, req: EvalRequest, reviewer: str | None) -> EvalResult:
        result = EvalResult(command=line.name)
        arg = line.args[0] if line.args else None
        if line.name == "help":
            commands = self.commands()
            if arg is not None:
                commands = [c for c in commands if arg in (c.name, c.task_id)]
                if not commands:
                    raise NotFound(f"Unknown command {arg!r}")
            result.data = [c.model_dump(mode="json") for c in commands]
            result.text = [f"{c.usage}  — {c.summary}" for c in commands]
            if arg is not None:
                result.text += [f"  -{o.name} ({o.type})  {o.help}" for o in commands[0].options]
            return result
        if line.name in {"status", "cancel"}:
            if arg is None:
                raise ValidationProblem(f"Name the run or operation: {line.name} <id>")
            find = self._status if line.name == "status" else self._cancel
            return await find(result, arg, req.project_id)
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
                reviewer,
            )
            result.started = WorkRef(
                kind="source-operation", id=arg, job_id=converted.job_id,
                status=converted.status, project_id=converted.project_id,
            )  # fmt: skip
            result.text = [f"conversion of {arg} {converted.status}"]
            return result
        pid = req.project_id
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
            return result
        runs = await self.tasks.list_runs(pid)
        result.data = [
            r.model_dump(mode="json", include={"run_id", "task", "status", "name"}) for r in runs
        ]
        result.text = [f"{r.run_id}  {r.task.id}  {r.status}" for r in runs]
        return result

    async def _find(self, ref: str, pid: str | None) -> tuple[WorkRef, Any]:
        """A project run (with a project), else a source operation, else a workspace run."""
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

    async def _status(self, result: EvalResult, ref: str, pid: str | None) -> EvalResult:
        work, record = await self._find(ref, pid)
        result.work, result.data = work, record.model_dump(mode="json")
        stage = f"  {record.stage}" if work.kind == "source-operation" else ""
        result.text = [f"{work.id}  {work.kind}{stage}  {work.status}"]
        return result

    async def _cancel(self, result: EvalResult, ref: str, pid: str | None) -> EvalResult:
        work, record = await self._find(ref, pid)
        status: str
        if work.kind == "task-run":
            assert pid is not None
            status = (await self.tasks.cancel(pid, ref)).status
        elif work.kind == "workspace-run":
            status = (await self.operations.workspace_tasks.cancel(ref)).status
        else:
            control = SourceOperationControl(
                expected_revision=record.revision,
                expected_attempt=record.attempt,
                expected_run_attempt=(
                    record.conversion_run.attempts if record.conversion_run else None
                ),
            )
            status = (await self.operations.cancel(ref, control)).status
        work.status = status
        result.work, result.text = work, [f"{work.id}  {work.status}"]
        return result
