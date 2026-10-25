"""Durable source discovery; conversion runs keep their own authority."""

from __future__ import annotations

import asyncio
import builtins
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.core.errors import (
    JobConflict,
    NotFound,
    Problem,
    SourceMissing,
    ValidationProblem,
    problem_body,
)
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.core.paths import PathGuard
from app.jobs.manager import JobManager
from app.jobs.types import JobHandle, JobInfo, JobSpec
from app.projects.service import Workspace
from app.sources import detect as source_detect
from app.sources import formats
from app.sources import open as open_mode
from app.sources.open_service import RETRY as OPEN_ACTIONS
from app.sources.open_service import guarded_source
from app.tasks import dry_run, protocol
from app.tasks.dicom_execution import attempt_cleaned
from app.tasks.dicom_execution import run_dicom_job as run_dicom_worker
from app.tasks.models import (
    TERMINAL_TASK_RUN,
    TaskEstimate,
    TaskRunDetail,
    TaskRunRequest,
    TaskRunStatus,
    TaskSelection,
)
from app.tasks.source_inventory import SourceInventory
from app.tasks.source_plans import SourcePlanPage, read_plan_page, write_plan
from app.tasks.workspace_runs import WorkspaceRun, WorkspaceRunRequest, default_dataset_name

if TYPE_CHECKING:
    from app.tasks.service import TaskService
    from app.tasks.workspace_runs import WorkspaceTasks

ACTIVE = {"queued", "running", "cancelling"}


class SourceOperationStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=8, max_length=128)
    project_id: str | None = None
    purpose: Literal["discover", "open", "convert"] = "convert"
    prepare_plan: bool = False
    settings: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=200)


class SourceOperationControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    expected_attempt: int = Field(ge=1)
    expected_run_attempt: int | None = Field(default=None, ge=0)


class SourceOperationEstimate(SourceOperationControl):
    settings: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=200)


class SourceOperationConvert(SourceOperationControl):
    inventory_generation: str = Field(min_length=1)
    plan_attempt: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=200)


class PendingSourceControl(BaseModel):
    action: Literal["cancel", "resume", "retry_failed"]
    request: SourceOperationControl
    request_id: str
    run_attempt: int


class SourceOperation(BaseModel):
    version: Literal[1] = 1
    operation_id: str
    source: str
    project_id: str | None
    purpose: Literal["discover", "open", "convert"]
    status: TaskRunStatus = "queued"
    stage: str = "discovering"
    revision: int = 0
    attempt: int = 1
    job_id: str | None = None
    created_at: str
    updated_at: str
    request_hash: str
    cleanup_verified: bool = True
    progress: dict[str, int] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    control: dict[str, Any] = Field(default_factory=dict)
    pending_control: PendingSourceControl | None = None
    work_kind: Literal["inventory", "estimate", "convert"] = "inventory"
    settings: dict[str, Any] = Field(default_factory=dict)
    estimate: TaskEstimate | None = None
    plan_attempt: int | None = None
    plan_total: int = 0
    progress_stage: str | None = None
    error: str | None = None
    problem: dict[str, Any] | None = None
    conversion_run_id: str | None = None
    conversion_request: dict[str, Any] = Field(default_factory=dict)
    conversion_run: TaskRunDetail | WorkspaceRun | None = None
    phase_run: TaskRunDetail | WorkspaceRun | None = None
    prepare_plan: bool = False
    dataset_name: str | None = None


class SourceOperations:
    def __init__(
        self,
        settings: Settings,
        guard: PathGuard,
        jobs: JobManager,
        workspace: Workspace,
        locks: ProjectLocks,
        tasks: TaskService,
        workspace_tasks: WorkspaceTasks,
    ) -> None:
        self.settings, self.guard, self.jobs = settings, guard, jobs
        self.workspace, self.locks = workspace, locks
        self.tasks, self.workspace_tasks = tasks, workspace_tasks
        self.root = settings.workspace_root / "plugins" / "dicom" / "operations"
        self._slots = asyncio.Semaphore(min(settings.job_workers, 12))

    def _dir(self, operation: str) -> Path:
        if not is_ulid(operation):
            raise NotFound("Source operation not found")
        return self.root / operation

    def get(self, operation: str) -> SourceOperation:
        try:
            return SourceOperation.model_validate(
                read_json(self._dir(operation) / "operation.json")
            )
        except FileNotFoundError:
            raise NotFound("Source operation not found") from None

    def _write(self, record: SourceOperation) -> SourceOperation:
        record.revision += 1
        record.updated_at = utc_now()
        self._persist(record)
        return record

    def _persist(self, record: SourceOperation) -> None:
        atomic_write_json(
            self._dir(record.operation_id) / "operation.json",
            record.model_dump(mode="json", exclude={"conversion_run", "phase_run"}),
        )

    def _confirm_replay(self, record: SourceOperation) -> None:
        """Reconfirm an uncertain rename before acknowledgment; dispatch only unlaunched work."""
        self._persist(record)
        if record.status != "queued":
            return
        if record.job_id:
            try:
                self.jobs.get(record.job_id)
                return
            except NotFound:
                pass
        retained, cleaned = self._execution_state(record)
        if retained or not cleaned:
            record.status = "interrupted" if cleaned else "cleanup_pending"
            record.cleanup_verified = cleaned
            record.error = (
                "Source work stopped; resume after verified cleanup"
                if cleaned
                else "Source execution evidence needs cleanup verification"
            )
            self._write(record)
            raise JobConflict(record.error)
        self._submit(record)

    def _execution_state(self, record: SourceOperation) -> tuple[bool, bool]:
        attempt = self._attempt_dir(record)
        retained = any(
            (attempt / name).exists() for name in ("launch.json", "process.json", "dispatch")
        )
        cleaned = attempt_cleaned(attempt, record.attempt) if record.job_id or retained else True
        return retained, cleaned

    async def _recover_source(self, record: SourceOperation) -> SourceOperation:
        info = None
        if record.job_id:
            try:
                info = self.jobs.get(record.job_id)
                if info.status not in {"failed", "cancelled", "interrupted"}:
                    return record
                await self.jobs.wait(record.job_id, timeout=0.01)
            except NotFound:
                info = None
            except TimeoutError:
                return record
        current = self.get(record.operation_id)
        if (
            current.attempt != record.attempt
            or current.job_id != record.job_id
            or current.status not in ACTIVE | {"cleanup_pending"}
        ):
            return current
        _, cleaned = self._execution_state(current)
        status: TaskRunStatus
        if not cleaned:
            status = "cleanup_pending"
        elif info and info.status == "cancelled":
            status = "cancelled"
        elif info and info.status == "failed":
            status = "failed"
        else:
            status = "interrupted"
        error = None if status == "cancelled" else current.error
        if status != "cancelled" and (not error or current.status == "cleanup_pending"):
            error = (
                "Source work stopped; verify its source/storage and resume"
                if cleaned
                else "Source cleanup is not yet verified"
            )
        if (current.status, current.cleanup_verified, current.error) != (status, cleaned, error):
            current.status, current.cleanup_verified, current.error = status, cleaned, error
            self._write(current)
        return current

    async def view(self, operation: str, *, include_run: bool = True) -> SourceOperation:
        record = self.get(operation)
        native = await self._conversion_run(record)
        if native is None and record.status in ACTIVE | {"cleanup_pending"}:
            recovered = await self._recover_source(record)
            if recovered is not record:
                record = recovered
                native = await self._conversion_run(record)
        if record.pending_control is not None and native is not None:
            async with self.locks(f"_source_operation:{operation}"):
                record = self.get(operation)
                native = await self._conversion_run(record)
                if native is not None:
                    self._settle_native_control(record, native)
        if native is None:
            return record
        record.conversion_run = native if include_run else None
        if include_run and native.phase_run_id:
            record.phase_run = (
                await self.tasks.get_run(record.project_id, native.phase_run_id)
                if record.project_id
                else self.workspace_tasks.get(native.phase_run_id)
            )
        record.status, record.error = native.status, native.error
        record.stage = "result" if record.status in TERMINAL_TASK_RUN else "converting"
        if (
            isinstance(native, TaskRunDetail)
            and native.status == "completed"
            and (native.execution or {}).get("registration_pending")
            and native.error is None
        ):
            record.stage, record.status = "registering", "reconciling"
        if (
            isinstance(native, TaskRunDetail)
            and native.status == "completed"
            and native.error
            and native.error.startswith("output registration:")
        ):
            record.stage = "registering"
            record.status = "failed"
        if isinstance(native, TaskRunDetail) and (native.execution or {}).get(
            "registration_cancel_requested"
        ):
            record.stage = "registering"
            record.status = (
                "cancelled"
                if (native.execution or {}).get("registration_cancelled")
                else "cancelling"
            )
        record.cleanup_verified = (
            native.cleanup_verified
            if isinstance(native, WorkspaceRun)
            else bool((native.execution or {}).get("cleanup_verified", False))
        )
        return record

    async def _conversion_run(self, record: SourceOperation) -> TaskRunDetail | WorkspaceRun | None:
        if not record.conversion_run_id:
            return None
        try:
            return (
                await self.tasks.get_run(record.project_id, record.conversion_run_id)
                if record.project_id
                else self.workspace_tasks.get(record.conversion_run_id)
            )
        except NotFound:
            return None

    def list(self) -> list[SourceOperation]:
        if not self.root.exists():
            return []
        return [
            self.get(p.name) for p in sorted(self.root.iterdir(), reverse=True) if is_ulid(p.name)
        ]

    def _attempt_dir(self, record: SourceOperation) -> Path:
        return self._dir(record.operation_id) / "attempts" / str(record.attempt)

    def _check_control(
        self, rec: SourceOperation, req: SourceOperationControl, action: str
    ) -> bool:
        pending = rec.pending_control
        if pending is not None:
            if pending.action == action and pending.request == req:
                return True
            raise JobConflict("A durable control is pending; reload and retry that command")
        if rec.control == {"action": action, **req.model_dump()}:
            self._confirm_replay(rec)
            return False
        if rec.revision != req.expected_revision or rec.attempt != req.expected_attempt:
            raise JobConflict(
                "Source operation revision/attempt changed; reload before controlling it"
            )
        return True

    def _check_run_control(
        self, native: TaskRunDetail | WorkspaceRun, request: SourceOperationControl
    ) -> None:
        expected = request.expected_run_attempt
        if (expected is None and native.attempts > 1) or (
            expected is not None and native.attempts != expected
        ):
            raise JobConflict("Conversion run attempt changed; reload before controlling it")

    def _begin_native_control(
        self,
        record: SourceOperation,
        native: TaskRunDetail | WorkspaceRun,
        request: SourceOperationControl,
        action: Literal["cancel", "resume", "retry_failed"],
    ) -> PendingSourceControl:
        self._check_run_control(native, request)
        if record.pending_control is None:
            record.pending_control = PendingSourceControl(
                action=action, request=request, request_id=new_ulid(), run_attempt=native.attempts
            )
            self._write(record)
        return record.pending_control

    def _ack_native_control(self, record: SourceOperation) -> None:
        pending = record.pending_control
        assert pending is not None
        record.control = {"action": pending.action, **pending.request.model_dump()}
        if pending.action in {"resume", "retry_failed"}:
            record.attempt += 1
        record.pending_control = None
        self._write(record)

    def _settle_native_control(
        self, record: SourceOperation, native: TaskRunDetail | WorkspaceRun
    ) -> bool:
        pending = record.pending_control
        if pending is None:
            return False
        resumed = (
            pending.action in {"resume", "retry_failed"}
            and native.attempts == pending.run_attempt + 1
            and native.resume_request_id == pending.request_id
        )
        cancelled = (
            pending.action == "cancel"
            and native.attempts == pending.run_attempt
            and native.status in TERMINAL_TASK_RUN | {"cancelling"}
            and not (
                isinstance(native, TaskRunDetail)
                and native.status == "completed"
                and not (native.execution or {}).get("registration_cancel_requested")
            )
        )
        if resumed or cancelled:
            self._ack_native_control(record)
            return True
        return False

    async def start(self, request: SourceOperationStart) -> SourceOperation:
        if request.purpose == "open" and request.prepare_plan:
            raise ValidationProblem("Open a source first; start conversion as a separate operation")
        if not Path(request.path).is_absolute():
            raise ValidationProblem("Choose an absolute source path")
        source = (
            guarded_source(self.guard, request.path)
            if request.purpose == "open"
            else self.guard.check(Path(request.path))
        )
        if not source.exists():
            raise NotFound("Source is missing")
        if not source.is_dir() and not source.is_file():
            raise ValidationProblem("Choose a regular source file or folder")
        if request.project_id is not None:
            self.workspace.get(request.project_id)  # rejects unknown/archived projects
        payload = request.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        key = hashlib.sha256(request.idempotency_key.encode()).hexdigest()
        receipt = self.root / "requests" / f"{key}.json"
        async with self.locks("_source_operations"):
            reserved_id = new_ulid()
            if receipt.exists():
                old = read_json(receipt)
                if old["request_hash"] != digest:
                    raise JobConflict(
                        "Idempotency key already identifies a different source request"
                    )
                if old.get("status") not in {None, "pending", "committed"}:
                    raise JobConflict("Source creation checkpoint is corrupt")
                reserved_id = old["operation_id"]
                directory = self._dir(reserved_id)
                if (directory / "operation.json").exists():
                    atomic_write_json(receipt, {**old, "status": "pending"})
                    record = self.get(reserved_id)
                    self._confirm_replay(record)
                    atomic_write_json(receipt, {**old, "status": "committed"})
                    return record
                if old.get("status") != "pending" or (
                    directory.exists() and any(p.name != "validation" for p in directory.iterdir())
                ):
                    raise JobConflict(
                        "Source operation record is missing; review retained evidence"
                    )
            record = SourceOperation(
                operation_id=reserved_id,
                source=str(source),
                project_id=request.project_id,
                purpose=request.purpose,
                created_at=utc_now(),
                updated_at=utc_now(),
                request_hash=digest,
                settings=request.settings,
                prepare_plan=request.prepare_plan,
                dataset_name=request.name,
            )
            if request.prepare_plan:
                validation_dir = self._dir(record.operation_id) / "validation"
                spec = (
                    self.tasks.source_estimate_spec(
                        request.project_id,
                        "dicom.convert",
                        str(source),
                        request.settings,
                        validation_dir,
                    )
                    if request.project_id
                    else self.workspace_tasks.source_estimate_spec(
                        "dicom.convert", str(source), request.settings, validation_dir
                    )
                )
                record.settings = spec["settings"]
            intent = {"operation_id": record.operation_id, "request_hash": digest}
            atomic_write_json(receipt, {**intent, "status": "pending"})
            self._write(record)
            self._submit(record)
            atomic_write_json(receipt, {**intent, "status": "committed"})
            return record

    def _submit(self, record: SourceOperation) -> None:
        job_dir = self._attempt_dir(record)
        base: dict[str, Any] = {}
        if record.work_kind == "estimate":
            base = (
                self.tasks.source_estimate_spec(
                    record.project_id, "dicom.convert", record.source, record.settings, job_dir
                )
                if record.project_id
                else self.workspace_tasks.source_estimate_spec(
                    "dicom.convert",
                    record.source,
                    record.settings,
                    job_dir,
                )
            )
            record.settings = base["settings"]
        protocol.write_job(
            job_dir,
            {
                **base,
                "source": base.get("source", record.source),
                "operation": "estimate" if record.work_kind == "estimate" else "inventory",
                "attempt": record.attempt,
                "dicom_process_protocol": 1,
                "inventory": str(self._dir(record.operation_id) / "inventory.sqlite"),
                "purpose": record.purpose,
                "operation_id": record.operation_id,
            },
        )
        record.job_id = new_ulid()
        record.error, record.problem = None, None
        record.progress, record.progress_stage = {}, None
        record.status = "queued"
        record.stage = "planning" if record.work_kind == "estimate" else "discovering"
        self._write(record)

        async def finish(_: JobInfo) -> None:
            current = self.get(record.operation_id)
            if (
                current.attempt == record.attempt
                and current.work_kind == "inventory"
                and current.prepare_plan
                and current.status == "queued"
                and current.stage == "planning"
                and current.cleanup_verified
            ):
                current.work_kind = "estimate"
                current.attempt += 1
                try:
                    self._submit(current)
                except Exception:
                    current.status = "failed"
                    current.error = "Could not prepare the dry run; review its source/settings"
                    self._write(current)
                    raise

        try:
            self.jobs.submit(
                JobSpec(
                    project_id=record.project_id or "_workspace",
                    kind="task",
                    units=[],
                    job_id=record.job_id,
                    key=f"source:{record.operation_id}",
                    driver=lambda handle: self._drive(record.operation_id, record.attempt, handle),
                    on_finish=finish,
                )
            )
        except Exception:
            record.status, record.error = "failed", "Could not admit source discovery"
            self._write(record)
            raise

    async def _drive(self, operation: str, attempt: int, handle: JobHandle) -> None:
        while not handle.stopped:
            try:
                await asyncio.wait_for(self._slots.acquire(), timeout=0.1)
                break
            except TimeoutError:
                continue
        else:
            return
        try:
            await self._drive_claimed(operation, attempt, handle)
        finally:
            self._slots.release()

    async def _drive_claimed(self, operation: str, attempt: int, handle: JobHandle) -> None:
        record = self.get(operation)
        if record.attempt != attempt or record.status not in ACTIVE:
            return
        if record.status == "cancelling":
            record.status = "cancelled"
            self._write(record)
            return
        record.status, record.cleanup_verified = "running", False
        self._write(record)

        def progress(row: dict[str, Any]) -> None:
            if row.get("t") not in {"inventory", "stage", "total"}:
                return
            current = self.get(operation)
            if current.attempt != attempt:
                return
            current.progress.update(
                {
                    k: int(row[k])
                    for k in ("files", "folders", "dicom", "series", "done", "total")
                    if k in row
                }
            )
            if row.get("stage"):
                current.progress_stage = str(row["stage"])
            self._write(current)
            handle.set_done(current.progress.get("files", 0))

        try:
            result = await run_dicom_worker(
                self._attempt_dir(record),
                workspace=self.settings.workspace_root,
                settings=self.settings,
                cancelled=lambda: handle.stopped or self.get(operation).status == "cancelling",
                on_progress=progress,
            )
            current = self.get(operation)
            if current.attempt != attempt:
                return
            current.cleanup_verified = bool(result["cleanup_verified"])
            self._write(current)  # cleanup survives a later plan/registration failure
            if not current.cleanup_verified:
                current.status, current.error = "cleanup_pending", "Worker cleanup is not confirmed"
            elif result["cancelled"] or current.status == "cancelling":
                job = self.jobs.get(str(current.job_id))
                current.status = "interrupted" if job.status == "interrupted" else "cancelled"
            elif result["exit_code"] != 0:
                current.status, current.error = (
                    "failed",
                    "Discovery worker failed; retained diagnostic log",
                )
            else:
                output = protocol.read_result(self._attempt_dir(record)) or {}
                if current.work_kind == "convert":
                    await self._finish_conversion(current, output)
                    return
                elif current.work_kind == "estimate":
                    self._finish_estimate(current, output)
                else:
                    current.summary = output.get("summary", {})
                    current.status = (
                        "completed" if current.summary.get("complete") else "completed_with_errors"
                    )
                    current.stage = "opened" if output.get("open_ready") else "discovered"
                    if current.status == "completed" and current.prepare_plan:
                        current.status, current.stage = "queued", "planning"
                    if current.summary.get("limit_reason") == "inventory_bytes":
                        current.error = (
                            "Inventory storage limit reached; increase DICOM_INVENTORY_MB "
                            "or release old inventory readers, then resume"
                        )
            self._write(current)
            if current.status == "cancelled" and current.job_id:
                self.jobs.cancel(current.job_id)
            elif current.status in {"failed", "cleanup_pending"}:
                raise RuntimeError(current.error or "Discovery did not finish safely")
        except asyncio.CancelledError:
            current = self.get(operation)
            outcome = protocol.read_exit(self._attempt_dir(record)) or {}
            current.cleanup_verified = (
                outcome.get("attempt") == attempt and outcome.get("cleanup_verified") is True
            )
            current.status = "interrupted" if current.cleanup_verified else "cleanup_pending"
            current.error = "Backend interrupted; resume after verified cleanup"
            self._write(current)
            raise
        except Exception as exc:
            current = self.get(operation)
            if not current.cleanup_verified:
                current.status, current.error = (
                    "cleanup_pending",
                    "Source operation failed; verify worker cleanup",
                )
            elif isinstance(exc, Problem):
                current.status, current.error = "failed", exc.detail
                current.problem = problem_body(
                    exc.slug,
                    exc.detail,
                    f"/api/v1/source-operations/{operation}",
                    exc.errors,
                    exc.actions,
                )
            else:
                current.status = "failed"
                current.error = (
                    current.error or "Source operation failed; review its source and settings"
                )
            self._write(current)
            raise RuntimeError(current.error) from None

    def detection(self, operation: str, *, dicom_available: bool) -> source_detect.DetectResult:
        """Bounded adapter hints from the completed inventory, without a rescan."""
        record = self.get(operation)
        if (
            record.purpose != "discover"
            or record.status != "completed"
            or record.stage != "discovered"
            or not record.cleanup_verified
        ):
            raise JobConflict(
                "Finish source discovery before choosing an import adapter", actions=OPEN_ACTIONS
            )
        source = guarded_source(self.guard, record.source)
        database = self._dir(operation) / "inventory.sqlite"
        try:
            if not database.is_file():
                raise JobConflict("Prepared source inventory is missing")
            with SourceInventory(database, source) as inventory:
                summary = inventory.summary()
                if not summary["complete"] or summary["generation"] != record.summary.get(
                    "generation"
                ):
                    raise JobConflict("Prepared source inventory changed")
                inventory.check_reader()
                ignored: Counter[str] = Counter()
                for row in inventory.db.execute("SELECT rel FROM files WHERE kind='ignored'"):
                    name = Path(row[0]).name
                    if name not in formats.SKIP_NAMES:
                        ignored[formats.extension(name)] += 1
                counts = {key: int(summary[key]) for key in ("nifti", "dicom", "npy")}
                counts["ignored"] = sum(ignored.values())
                count = counts["nifti"]
                positions = {
                    index * count // min(count, source_detect.SAMPLE)
                    for index in range(min(count, source_detect.SAMPLE))
                }
                sample = [
                    row[0]
                    for index, row in enumerate(
                        inventory.db.execute(
                            "SELECT rel FROM files WHERE kind='nifti' ORDER BY rel"
                        )
                    )
                    if index in positions
                ]
                has_meta = (
                    not inventory.single_file
                    and inventory.db.execute(
                        "SELECT 1 FROM files WHERE rel='metadata.jsonl' AND error=''"
                    ).fetchone()
                    is not None
                )
                return source_detect.from_facts(
                    source,
                    kind="file" if inventory.single_file else "folder",
                    counts=counts,
                    ignored=dict(ignored),
                    nifti_sample=sample,
                    has_meta=has_meta,
                    truncated=False,
                    dicom_available=dicom_available,
                )
        except (OSError, sqlite3.Error, JobConflict, ValueError) as exc:
            raise JobConflict(
                "Source inventory is unavailable or incompatible; discover it again",
                actions=OPEN_ACTIONS,
            ) from exc

    def open_session(self, operation: str, *, reopen: bool = False) -> open_mode.OpenSession:
        """Restore an explicitly prepared Open result; conversion records stay separate."""
        record = self.get(operation)
        if record.purpose != "open":
            raise NotFound("This operation has no Open session")
        if record.stage != "opened" or record.status != "completed" or not record.cleanup_verified:
            raise JobConflict(
                "Finish or resume source opening before viewing its result", actions=OPEN_ACTIONS
            )
        self.guard.check(Path(record.source))
        directory = self._dir(operation)
        closed = directory / "open-closed.json"
        if closed.exists() and not reopen:
            raise NotFound("This Open session was closed", actions=["choose_another_path", "home"])
        artifact = self._attempt_dir(record) / "open-session.json"
        from app.tasks.source_open import reader_identity

        try:
            raw = artifact.read_bytes()
            if hashlib.sha256(raw).hexdigest() != record.summary.get(
                "open_session_sha256"
            ) or reader_identity() != record.summary.get("open_reader"):
                raise JobConflict(
                    "Open result changed or its reader is incompatible; open the source again",
                    actions=OPEN_ACTIONS,
                )
            session = open_mode.OpenSession.model_validate_json(raw)
            prepared = session
            state = directory / "open-session-state.json"
            if state.exists():
                saved = read_json(state)
                if (
                    saved.get("version") != 2
                    or saved.get("base_sha256") != record.summary["open_session_sha256"]
                ):
                    raise JobConflict(
                        "Saved Open state is incompatible; open the source again",
                        actions=OPEN_ACTIONS,
                    )
                session = open_mode.OpenSession.model_validate(saved["session"])
                if saved.get("label_inputs") != self._open_label_inputs(session):
                    raise JobConflict(
                        "Attached Open mask changed; attach it again", actions=OPEN_ACTIONS
                    )
        except (OSError, ValueError, KeyError):
            raise JobConflict(
                "Open result is unreadable; open the source again", actions=OPEN_ACTIONS
            ) from None
        if session.sid != operation or session.path != record.source:
            raise JobConflict("Open result belongs to a different source", actions=OPEN_ACTIONS)
        from app.tasks.source_open import validate_prepared_open

        database = directory / "inventory.sqlite"
        try:
            if not database.is_file():
                raise JobConflict("Prepared Open inventory is missing")
            with SourceInventory(database, Path(record.source)) as inventory:
                validate_prepared_open(inventory, record.summary["generation"], prepared)
        except (OSError, sqlite3.Error, JobConflict, KeyError, ValueError) as exc:
            raise JobConflict(
                "Prepared Open inputs changed or are unavailable; open the source again",
                actions=OPEN_ACTIONS,
            ) from exc
        if reopen:
            closed.unlink(missing_ok=True)
        return session

    def _open_label_inputs(self, session: open_mode.OpenSession) -> dict[str, builtins.list[int]]:
        from app.tasks.source_open import dependency_stat

        pins = {}
        for item in session.items:
            if item.kind != "label":
                continue
            path = open_mode.source_path(session, item)
            self.guard.check(path)
            try:
                pin = dependency_stat(path.parent, path)
            except (OSError, JobConflict):
                raise JobConflict(
                    "Attached Open mask is unavailable; attach it again", actions=OPEN_ACTIONS
                ) from None
            if pin is None:
                raise JobConflict(
                    "Attached Open mask is missing; attach it again", actions=OPEN_ACTIONS
                )
            pins[item.rel] = pin
        return pins

    def save_open_session(self, session: open_mode.OpenSession) -> None:
        try:
            record = self.get(session.sid)
        except NotFound:
            return  # compatibility Open sessions are intentionally ephemeral
        if record.purpose == "open":
            atomic_write_json(
                self._dir(session.sid) / "open-session-state.json",
                {
                    "version": 2,
                    "label_inputs": self._open_label_inputs(session),
                    "base_sha256": record.summary.get("open_session_sha256"),
                    "session": session.model_dump(mode="json"),
                },
            )

    def close_open_session(self, operation: str) -> None:
        try:
            record = self.get(operation)
        except NotFound:
            return
        if record.purpose == "open":
            atomic_write_json(self._dir(operation) / "open-closed.json", {"closed_at": utc_now()})

    async def convert(self, operation: str, request: SourceOperationConvert) -> SourceOperation:
        async with self.locks(f"_source_operation:{operation}"):
            record = self.get(operation)
            if not self._check_control(record, request, "convert"):
                return await self.view(operation)
            if record.conversion_run_id or record.status != "completed" or record.stage != "ready":
                raise JobConflict("Finish a fresh dry run before starting its conversion")
            if record.estimate is None or record.estimate.n_units == 0:
                raise JobConflict("The dry run selects no series; adjust conversion settings first")
            if (
                record.plan_attempt != request.plan_attempt
                or record.summary.get("generation") != request.inventory_generation
                or not record.summary.get("complete")
            ):
                raise JobConflict("Source plan generation changed; refresh the dry run")
            record.control = {"action": "convert", **request.model_dump()}
            record.conversion_run_id = new_ulid()
            record.conversion_request = {
                **request.model_dump(),
                "name": request.name or record.dataset_name or default_dataset_name(),
            }
            record.work_kind = "convert"
            record.attempt += 1
            self._submit(record)
            return record

    async def _finish_conversion(self, record: SourceOperation, output: dict[str, Any]) -> None:
        async with self.locks(f"_source_operation:{record.operation_id}"):
            current = self.get(record.operation_id)
            if current.attempt != record.attempt:
                return
            if current.status in {"cancelling", "cancelled"}:
                current.status = "cancelled"
                if current.job_id:
                    self.jobs.cancel(current.job_id)
            else:
                await self._allocate_conversion(current, output)
            self._write(current)
            if current.status == "failed":
                raise RuntimeError(current.error)

    async def _allocate_conversion(self, record: SourceOperation, output: dict[str, Any]) -> None:
        summary = output.get("summary", {})
        if not summary.get("complete") or summary.get(
            "generation"
        ) != record.conversion_request.get("inventory_generation"):
            record.status, record.error = (
                "failed",
                "Source changed or discovery is partial; prepare a new dry run",
            )
            record.summary = summary
            return
        assert record.conversion_run_id is not None
        binding = {
            "operation_id": record.operation_id,
            "path": str(self._dir(record.operation_id) / "inventory.sqlite"),
            "generation": summary["generation"],
        }
        if record.project_id:
            await self.tasks.start(
                record.project_id,
                TaskRunRequest(
                    task_id="dicom.convert",
                    settings=record.settings,
                    selection=TaskSelection(source=record.source),
                ),
                None,
                run_id=record.conversion_run_id,
                source_inventory=binding,
            )
        else:
            await self.workspace_tasks.start(
                WorkspaceRunRequest(
                    task_id="dicom.convert",
                    name=record.conversion_request["name"],
                    settings=record.settings,
                    selection=TaskSelection(source=record.source),
                ),
                run_id=record.conversion_run_id,
                source_inventory=binding,
            )
        record.status, record.stage = "completed", "converting"

    def _finish_estimate(self, record: SourceOperation, result: dict[str, Any]) -> None:
        record.summary = result.get("summary", {})
        if record.summary.get("limited"):
            record.status, record.stage = "completed_with_errors", "planning"
            record.error = "Discovery is partial; increase DICOM_INVENTORY_MB and resume Estimate"
            return
        if result.get("status") != "completed":
            raise RuntimeError("Dry run did not finish; inspect discovery diagnostics")
        plan = list(result.get("estimate", {}).get("series_plan", []))
        if not plan and not record.summary.get("dicom"):
            raise dry_run.no_dicom_problem(Path(record.source), int(record.summary.get("nifti", 0)))
        estimate = dry_run.estimate_of(
            result, float(result.get("duration_s", 0)), Path(record.source)
        )
        write_plan(self._dir(record.operation_id) / "plans" / str(record.attempt), plan)
        record.estimate = estimate.model_copy(update={"series": [], "series_truncated": False})
        record.plan_total, record.plan_attempt = len(plan), record.attempt
        record.summary = result["summary"]
        record.status, record.stage = "completed", "ready"

    async def estimate(self, operation: str, request: SourceOperationEstimate) -> SourceOperation:
        async with self.locks(f"_source_operation:{operation}"):
            record = self.get(operation)
            if record.purpose == "open":
                raise JobConflict("Start a separate conversion operation for this Open source")
            if not self._check_control(record, request, "estimate"):
                return record
            if (
                record.status not in {"completed", "completed_with_errors"}
                or not record.cleanup_verified
                or record.conversion_run_id is not None
            ):
                raise JobConflict("Finish source discovery before its dry run")
            record.control = {"action": "estimate", **request.model_dump()}
            record.work_kind, record.settings = "estimate", request.settings
            if request.name is not None:
                record.dataset_name = request.name.strip() or None
            record.estimate, record.plan_attempt, record.plan_total = None, None, 0
            record.attempt += 1
            self._submit(record)
            return record

    def plan_page(
        self,
        operation: str,
        limit: int,
        cursor: str | None,
        action: Literal["convert", "skip"] | None = None,
    ) -> SourcePlanPage:
        record = self.get(operation)
        if record.plan_attempt is None:
            if cursor:
                raise JobConflict("No plan is ready for this generation")
            return SourcePlanPage(items=[], total=0)
        return read_plan_page(
            self._dir(operation) / "plans" / str(record.plan_attempt),
            limit=limit,
            cursor=cursor,
            action=action,
        )

    async def cancel(self, operation: str, request: SourceOperationControl) -> SourceOperation:
        async with self.locks(f"_source_operation:{operation}"):
            record = self.get(operation)
            if not self._check_control(record, request, "cancel"):
                return await self.view(operation)
            native = await self._conversion_run(record)
            if native is not None:
                if self._settle_native_control(record, native):
                    return await self.view(operation)
                self._begin_native_control(record, native, request, "cancel")
                assert record.conversion_run_id is not None
                if record.project_id:
                    await self.tasks.cancel(
                        record.project_id,
                        record.conversion_run_id,
                        expected_attempt=native.attempts,
                    )
                else:
                    await self.workspace_tasks.cancel(
                        record.conversion_run_id, expected_attempt=native.attempts
                    )
                self._ack_native_control(record)
                return await self.view(operation)
            if record.status not in ACTIVE:
                return record
            record.control = {"action": "cancel", **request.model_dump()}
            if record.status == "queued":
                _, cleaned = self._execution_state(record)
                if record.job_id:
                    with suppress(NotFound):
                        self.jobs.cancel(record.job_id)
                record.status = "cancelled" if cleaned else "cleanup_pending"
                record.cleanup_verified = cleaned
                record.error = (
                    None if cleaned else "Source execution evidence needs cleanup verification"
                )
                return self._write(record)
            record.status = "cancelling"
            return self._write(record)

    async def resume(
        self, operation: str, request: SourceOperationControl, *, failed_only: bool = False
    ) -> SourceOperation:
        action: Literal["retry_failed", "resume"] = "retry_failed" if failed_only else "resume"
        async with self.locks(f"_source_operation:{operation}"):
            record = self.get(operation)
            if not self._check_control(record, request, action):
                return await self.view(operation)
            if failed_only and request.expected_run_attempt is None:
                raise JobConflict("Retry failed requires the conversion's current attempt")
            native = await self._conversion_run(record)
            if native is not None:
                if self._settle_native_control(record, native):
                    return await self.view(operation)
                was_pending = record.pending_control is not None
                pending = self._begin_native_control(record, native, request, action)
                assert record.conversion_run_id is not None
                registration_only = (
                    not failed_only
                    and native.status == "completed"
                    and (
                        (native.error and native.error.startswith("output registration:"))
                        or (
                            isinstance(native, TaskRunDetail)
                            and (native.execution or {}).get("registration_cancel_requested")
                        )
                        or was_pending
                    )
                )
                try:
                    if registration_only and record.project_id:
                        await self.tasks.get_run(
                            record.project_id, record.conversion_run_id, retry_registration=True
                        )
                    elif record.project_id:
                        await self.tasks.resume(
                            record.project_id,
                            record.conversion_run_id,
                            expected_attempt=native.attempts,
                            request_id=pending.request_id,
                            failed_only=failed_only,
                        )
                    else:
                        await self.workspace_tasks.resume(
                            record.conversion_run_id,
                            expected_attempt=native.attempts,
                            request_id=pending.request_id,
                            failed_only=failed_only,
                        )
                except JobConflict:
                    latest = await self._conversion_run(record)
                    if latest is not None and latest.attempts == pending.run_attempt:
                        record.pending_control = None
                        self._write(record)
                    raise
                self._ack_native_control(record)
                return await self.view(operation)
            if failed_only:
                raise JobConflict("Retry failed requires a linked conversion run")
            limited = record.status == "completed_with_errors" and record.summary.get("limited")
            if (
                record.status not in {"interrupted", "cancelled", "failed"} and not limited
            ) or not record.cleanup_verified:
                raise JobConflict("Only stopped, cleanup-verified source work may resume")
            self.guard.check(Path(record.source))
            if not Path(record.source).exists():
                raise SourceMissing("The source is unavailable; restore it before resuming")
            record.attempt += 1
            record.error = None
            record.control = {"action": "resume", **request.model_dump()}
            self._submit(record)
            return record

    def series_page(self, operation: str, limit: int, cursor: str | None) -> dict[str, Any]:
        record = self.get(operation)
        database = self._dir(operation) / "inventory.sqlite"
        if not database.exists():
            return {"items": [], "total": 0, "next_cursor": None, "generation": None}
        with SourceInventory(database, Path(record.source)) as inventory:
            return inventory.page(limit=limit, cursor=cursor)

    async def recover_all(self) -> None:
        for record in self.list():
            if record.status not in ACTIVE | {"cleanup_pending"}:
                continue
            attempt = self._attempt_dir(record)
            cleaned = attempt_cleaned(attempt, record.attempt)
            if record.status == "queued" and not (attempt / "launch.json").exists():
                cleaned = True
            record.status = "interrupted" if cleaned else "cleanup_pending"
            record.cleanup_verified = cleaned
            record.error = "Backend interrupted; resume after verified cleanup"
            self._write(record)
