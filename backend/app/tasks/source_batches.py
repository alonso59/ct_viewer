"""Frozen patient-folder batch plans that drive one source operation per batch, in order."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.core.errors import (
    DerivedRootRequired,
    JobConflict,
    NotFound,
    Problem,
    ServerBusy,
    ValidationProblem,
)
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.core.paths import PathGuard
from app.jobs.manager import JobManager
from app.tasks.dry_run import DICOM_CONVERT
from app.tasks.source_inventory import checked_folders
from app.tasks.source_operations import (
    SourceOperationControl,
    SourceOperationConvert,
    SourceOperations,
    SourceOperationStart,
)
from app.tasks.workspace_runs import (
    DATASET_JSON,
    DATASETS,
    WorkspaceRun,
    dataset_name,
    default_dataset_name,
)

log = logging.getLogger("app.source_batches")

PlanStatus = Literal["pending", "running", "paused", "completed", "cancelled"]
BatchStatus = Literal[
    "pending", "discovering", "ready", "converting", "completed", "attention", "cancelled"
]
Counting = Literal["counting", "done", "cancelled"]
IN_FLIGHT = {"queued", "running", "cancelling", "reconciling", "waiting_for_runner"}


class BatchPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)
    batch_size: int = Field(default=40, ge=1, le=1000)
    settings: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=80)
    auto: bool = False


class BatchPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto: bool


class PlanBatch(BaseModel):
    """Stored batch. Folder names and patient hashes stay inside plan.json."""

    index: int
    name: str
    folders: list[str]
    operation_id: str | None = None
    status: BatchStatus = "pending"
    dataset: str | None = None
    files_total: int | None = None
    approved: bool = False
    error: str | None = None
    patient_hashes: list[str] | None = None
    convert_s: float | None = None


class BatchWarning(BaseModel):
    code: Literal["patient_in_earlier_batch"] = "patient_in_earlier_batch"
    batch_index: int
    earlier_batches: list[int]
    patients: int
    message: str


class PlanRecord(BaseModel):
    version: Literal[1] = 1
    plan_id: str
    source: str
    settings: dict[str, Any]
    batch_size: int
    name: str
    auto: bool
    status: PlanStatus = "pending"
    cursor: int = 0
    counting: Counting = "counting"
    salt: str
    revision: int = 0
    created_at: str
    updated_at: str
    warnings: list[BatchWarning] = Field(default_factory=list)
    batches: list[PlanBatch]


class SourceBatch(BaseModel):
    index: int
    name: str
    folder_count: int
    files_total: int | None
    operation_id: str | None
    status: BatchStatus
    dataset: str | None
    approved: bool
    error: str | None
    patients: int | None


class BatchPlanEta(BaseModel):
    """Time left for the batches that have not completed, from the batches that have."""

    low_s: int | None = None
    high_s: int | None = None
    basis: Literal["unknown", "completed_batches"] = "unknown"


class SourceBatchPlan(BaseModel):
    plan_id: str
    source: str
    name: str
    batch_size: int
    auto: bool
    status: PlanStatus
    cursor: int
    counting: Counting
    revision: int
    created_at: str
    updated_at: str
    warnings: list[BatchWarning]
    eta: BatchPlanEta
    batches: list[SourceBatch]


def plan_eta(plan: PlanRecord) -> BatchPlanEta:
    """Remaining files x the slowest and fastest measured seconds per file, widened by 20% and 25%.

    Batches whose files are not counted yet count as an average completed batch.
    """
    done = [b for b in plan.batches if b.status == "completed" and b.convert_s and b.files_total]
    left = [b for b in plan.batches if b.status != "completed"]
    if not done or not left:
        return BatchPlanEta()
    rates = [b.convert_s / b.files_total for b in done if b.convert_s and b.files_total]
    average = sum(b.files_total or 0 for b in done) / len(done)
    remaining = sum(b.files_total if b.files_total is not None else average for b in left)
    return BatchPlanEta(
        low_s=round(remaining * min(rates) * 0.8),
        high_s=round(remaining * max(rates) * 1.25),
        basis="completed_batches",
    )


def view_of(plan: PlanRecord) -> SourceBatchPlan:
    return SourceBatchPlan(
        **plan.model_dump(exclude={"settings", "salt", "version", "batches"}),
        eta=plan_eta(plan),
        batches=[
            SourceBatch(
                **b.model_dump(exclude={"folders", "patient_hashes", "convert_s"}),
                folder_count=len(b.folders),
                patients=None if b.patient_hashes is None else len(b.patient_hashes),
            )
            for b in plan.batches
        ],
    )


def run_seconds(run: WorkspaceRun) -> float | None:
    """Wall time of the conversion run; time spent paused is included, which only lengthens it."""
    try:
        started, finished = (datetime.fromisoformat(v) for v in (run.started_at, run.finished_at))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    seconds = (finished - started).total_seconds()
    return seconds if seconds > 0 else None


def count_files(source: str, folder: str) -> int:
    """Name-only file count of one patient folder with the discovery traversal rules."""
    from plugins.dicom import files as source_files

    total = 0
    pending = [os.path.join(source, folder)]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    if entry.name.startswith(".") or entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if not source_files.excluded(entry.name):
                            pending.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        total += 1
        except OSError:
            continue
    return total


def top_level_folders(source: Path) -> list[str]:
    from plugins.dicom import files as source_files

    names = []
    with os.scandir(source) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False) and not source_files.excluded(entry.name):
                names.append(entry.name)
    return sorted(names, key=lambda n: (n.lower(), n))


class SourceBatches:
    def __init__(
        self,
        settings: Settings,
        guard: PathGuard,
        jobs: JobManager,
        locks: ProjectLocks,
        operations: SourceOperations,
    ) -> None:
        self.settings, self.guard, self.jobs, self.locks = settings, guard, jobs, locks
        self.operations = operations
        self.root = settings.workspace_root / "plugins" / "dicom" / "batches"
        self._counters: dict[str, asyncio.Task[None]] = {}
        self._reconciler: asyncio.Task[None] | None = None
        self._dirty = False

    # --- storage -------------------------------------------------------------------------

    def _dir(self, plan_id: str) -> Path:
        if not is_ulid(plan_id) or (self.root / plan_id).is_symlink():
            raise NotFound("Batch plan not found")
        return self.root / plan_id

    def get(self, plan_id: str) -> PlanRecord:
        try:
            return PlanRecord.model_validate(read_json(self._dir(plan_id) / "plan.json"))
        except FileNotFoundError:
            raise NotFound("Batch plan not found") from None
        except (OSError, ValueError):
            raise JobConflict(
                "The batch plan record is damaged or unreadable; preserve it and create a new plan"
            ) from None

    def _save(self, plan: PlanRecord) -> None:
        plan.revision += 1
        plan.updated_at = utc_now()
        atomic_write_json(self._dir(plan.plan_id) / "plan.json", plan.model_dump(mode="json"))

    def plans(self) -> list[PlanRecord]:
        if not self.root.exists():
            return []
        plans = []
        for path in sorted(self.root.iterdir(), reverse=True):
            if not is_ulid(path.name) or path.is_symlink():
                continue
            try:
                plans.append(self.get(path.name))
            except Problem:
                log.warning("Batch plan record unavailable; retained", extra={"plan_id": path.name})
        return plans

    def _lock(self, plan_id: str) -> Any:
        return self.locks(f"_source_batch:{plan_id}")

    def _datasets(self) -> Path:
        if not self.settings.derived_roots:
            raise DerivedRootRequired(
                "ALLOWED_DERIVED_ROOTS is empty: the server has no writable folder for datasets",
                actions=["configure:ALLOWED_DERIVED_ROOTS"],
            )
        return self.settings.derived_roots[0] / DATASETS

    # --- plan creation ---------------------------------------------------------------------

    async def create(self, request: BatchPlanCreate) -> PlanRecord:
        if not Path(request.path).is_absolute():
            raise ValidationProblem("Choose an absolute source path")
        source = self.guard.check(Path(request.path))
        if not source.is_dir():
            raise NotFound("Source folder is missing")
        names = await asyncio.to_thread(top_level_folders, source)
        if not names:
            raise ValidationProblem("The source has no patient folders to split into batches")
        names = await asyncio.to_thread(checked_folders, source, names)
        chunks = [
            names[i : i + request.batch_size] for i in range(0, len(names), request.batch_size)
        ]
        stem = dataset_name(request.name or default_dataset_name())
        batches = self._batches(stem, chunks, first=1, width=max(2, len(str(len(chunks)))))
        self._check_names(batches)
        first = {**request.settings, "patient_folders": batches[0].folders}
        self.operations.workspace_tasks.source_estimate_spec(
            DICOM_CONVERT, str(source), first, self.root
        )  # rejects invalid settings before any work starts
        plan = PlanRecord(
            plan_id=new_ulid(),
            source=str(source),
            settings=request.settings,
            batch_size=request.batch_size,
            name=stem,
            auto=request.auto,
            salt=secrets.token_hex(16),
            created_at=utc_now(),
            updated_at=utc_now(),
            batches=batches,
        )
        async with self._lock(plan.plan_id):
            self._save(plan)
        self._count(plan.plan_id)
        return plan

    @staticmethod
    def _batches(stem: str, chunks: list[list[str]], *, first: int, width: int) -> list[PlanBatch]:
        return [
            PlanBatch(index=first + i, name=f"{stem}-b{first + i:0{width}d}", folders=chunk)
            for i, chunk in enumerate(chunks)
        ]

    def _check_names(self, batches: list[PlanBatch]) -> None:
        base = self._datasets()
        for batch in batches:
            if (base / batch.name).exists():
                raise JobConflict(
                    "A dataset with a batch name already exists; choose another plan name",
                    actions=["choose_another_name"],
                )

    # --- name-only file counts ---------------------------------------------------------------

    def _count(self, plan_id: str) -> None:
        running = self._counters.get(plan_id)
        if running is None or running.done():
            self._counters[plan_id] = asyncio.get_running_loop().create_task(
                self._count_plan(plan_id)
            )

    async def _count_plan(self, plan_id: str) -> None:
        try:
            while True:
                plan = self.get(plan_id)
                todo = next((b for b in plan.batches if b.files_total is None), None)
                if todo is None or plan.status == "cancelled":
                    break
                total = 0
                for folder in todo.folders:
                    total += await self.jobs.run_in_worker(count_files, plan.source, folder)
                    if self.get(plan_id).status == "cancelled":
                        return
                async with self._lock(plan_id):
                    plan = self.get(plan_id)
                    for batch in plan.batches:
                        if batch.index == todo.index:
                            batch.files_total = total
                    self._save(plan)
            async with self._lock(plan_id):
                plan = self.get(plan_id)
                if plan.counting == "counting":
                    plan.counting = "cancelled" if plan.status == "cancelled" else "done"
                    self._save(plan)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Batch file counting failed", extra={"plan_id": plan_id})

    # --- controls ----------------------------------------------------------------------------

    async def start(self, plan_id: str) -> PlanRecord:
        async with self._lock(plan_id):
            plan = self.get(plan_id)
            if plan.status == "running":
                return plan
            if plan.status != "pending":
                raise JobConflict("Only a plan that has not started can be started")
            if any(p.status == "running" for p in self.plans() if p.plan_id != plan_id):
                raise JobConflict("Another batch plan is running; wait for it or cancel it")
            plan.status = "running"
            self._save(plan)
        await self._advance(plan_id)
        return self.get(plan_id)

    async def resume_plan(self, plan_id: str) -> PlanRecord:
        """The user's go-ahead: convert the current batch, or continue after a pause."""
        async with self._lock(plan_id):
            plan = self.get(plan_id)
            if plan.status in {"pending", "completed", "cancelled"}:
                raise JobConflict("This plan has nothing to continue")
            if plan.status == "paused":
                if any(p.status == "running" for p in self.plans() if p.plan_id != plan_id):
                    raise JobConflict("Another batch plan is running; wait for it or cancel it")
                plan.status = "running"
            current = plan.batches[plan.cursor]
            current.approved, current.error = True, None
            if current.status == "attention":
                current.status = "discovering"
            self._save(plan)
        await self._advance(plan_id)
        return self.get(plan_id)

    async def update(self, plan_id: str, request: BatchPlanUpdate) -> PlanRecord:
        async with self._lock(plan_id):
            plan = self.get(plan_id)
            if plan.status == "cancelled":
                raise JobConflict("A cancelled plan cannot change")
            if plan.auto != request.auto:
                plan.auto = request.auto
                self._save(plan)
        await self._advance(plan_id)
        return self.get(plan_id)

    async def cancel(self, plan_id: str) -> PlanRecord:
        async with self._lock(plan_id):
            plan = self.get(plan_id)
            if plan.status in {"completed", "cancelled"}:
                return plan
            current = plan.batches[plan.cursor] if plan.cursor < len(plan.batches) else None
            if current is not None and current.operation_id and current.status != "completed":
                record = await self.operations.view(current.operation_id)
                if record.status in IN_FLIGHT or record.status == "cleanup_pending":
                    await self.operations.cancel(
                        current.operation_id,
                        SourceOperationControl(
                            expected_revision=record.revision,
                            expected_attempt=record.attempt,
                            expected_run_attempt=(
                                record.conversion_run.attempts
                                if isinstance(record.conversion_run, WorkspaceRun)
                                else None
                            ),
                        ),
                    )
            plan.status = "cancelled"
            for batch in plan.batches:
                if batch.status != "completed":
                    batch.status = "cancelled"
            self._save(plan)
        task = self._counters.get(plan_id)
        if task is not None:
            task.cancel()
        return self.get(plan_id)

    async def add_new_folders(self, plan_id: str) -> PlanRecord:
        """Folders that appeared after the plan was frozen become one new trailing batch."""
        async with self._lock(plan_id):
            plan = self.get(plan_id)
            if plan.status == "cancelled":
                raise JobConflict("A cancelled plan cannot change")
            source = Path(plan.source)
            current = await asyncio.to_thread(top_level_folders, source)
            known = {name for b in plan.batches for name in b.folders}
            fresh = [n for n in current if n not in known]
            if not fresh:
                raise JobConflict("No new patient folders were found")
            fresh = await asyncio.to_thread(checked_folders, source, fresh)
            width = len(plan.batches[0].name) - len(plan.name) - 2
            batch = self._batches(plan.name, [fresh], first=len(plan.batches) + 1, width=width)
            self._check_names(batch)
            plan.batches.extend(batch)
            plan.counting = "counting"
            if plan.status == "completed":
                plan.status = "paused"
            self._save(plan)
        self._count(plan_id)
        return self.get(plan_id)

    # --- orchestration -------------------------------------------------------------------------

    def nudge(self) -> None:
        """Called when any job ends: re-evaluate running plans, coalescing bursts."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._reconciler is not None and not self._reconciler.done():
            self._dirty = True
            return
        self._reconciler = loop.create_task(self._reconcile_loop())

    async def _reconcile_loop(self) -> None:
        while True:
            self._dirty = False
            await self.reconcile()
            if not self._dirty:
                return

    async def reconcile(self) -> None:
        """Re-enter every running plan and finish interrupted counts; idempotent."""
        for plan in self.plans():
            if plan.counting == "counting" and plan.status != "cancelled":
                self._count(plan.plan_id)
            if plan.status == "running":
                try:
                    await self._advance(plan.plan_id)
                except Exception:
                    log.exception("Batch plan advance failed", extra={"plan_id": plan.plan_id})

    async def _advance(self, plan_id: str) -> None:
        async with self._lock(plan_id):
            while True:
                plan = self.get(plan_id)
                if plan.status != "running":
                    return
                before = self._signature(plan)
                await self._step(plan)
                if self._signature(self.get(plan_id)) == before:
                    return

    @staticmethod
    def _signature(plan: PlanRecord) -> tuple[Any, ...]:
        batch = plan.batches[plan.cursor] if plan.cursor < len(plan.batches) else None
        return (
            plan.status,
            plan.cursor,
            batch and (batch.status, batch.operation_id),
        )

    def _pause(self, plan: PlanRecord, batch: PlanBatch, message: str | None) -> None:
        batch.status, batch.error = "attention", message
        plan.status = "paused"
        self._save(plan)

    async def _step(self, plan: PlanRecord) -> None:
        if plan.cursor >= len(plan.batches):
            plan.status = "completed"
            self._save(plan)
            return
        batch = plan.batches[plan.cursor]
        if batch.operation_id is None:
            if (self._datasets() / batch.name).exists():
                self._pause(plan, batch, "A dataset with this batch name already exists")
                return
            try:
                record = await self.operations.start(
                    SourceOperationStart(
                        path=plan.source,
                        idempotency_key=f"batch-{plan.plan_id}-{batch.index:04d}",
                        purpose="convert",
                        prepare_plan=True,
                        settings=plan.settings,
                        name=batch.name,
                        folders=batch.folders,
                    )
                )
            except Problem as exc:
                self._pause(plan, batch, exc.detail)
                return
            batch.operation_id, batch.status = record.operation_id, "discovering"
            self._save(plan)
            return
        record = await self.operations.view(batch.operation_id)
        if record.conversion_run_id is None:
            await self._step_prepare(plan, batch, record)
        else:
            await self._step_convert(plan, batch, record)

    async def _step_prepare(self, plan: PlanRecord, batch: PlanBatch, record: Any) -> None:
        if record.status in IN_FLIGHT:
            if (batch.status, batch.error) != ("discovering", None):
                batch.status, batch.error = "discovering", None
                self._save(plan)
            return
        if record.status != "completed" or record.stage != "ready":
            self._pause(plan, batch, record.error or "Batch discovery needs attention")
            return
        if batch.patient_hashes is None:
            await self._record_patients(plan, batch, record.operation_id)
        if batch.status != "ready":
            batch.status = "ready"
            self._save(plan)
        if not (batch.approved or (plan.auto and batch.index > 1)):
            return
        if (self._datasets() / batch.name).exists():
            self._pause(plan, batch, "A dataset with this batch name already exists")
            return
        try:
            await self.operations.convert(
                record.operation_id,
                SourceOperationConvert(
                    expected_revision=record.revision,
                    expected_attempt=record.attempt,
                    inventory_generation=str(record.summary.get("generation")),
                    plan_attempt=int(record.plan_attempt or 1),
                    name=batch.name,
                ),
            )
        except ServerBusy as exc:
            # Another conversion holds the single workspace slot; the next finished job
            # re-evaluates this batch.
            log.info("Batch conversion not admitted yet: %s", exc.detail)
            if batch.error != exc.detail:
                batch.error = exc.detail
                self._save(plan)
            return
        except Problem as exc:
            self._pause(plan, batch, exc.detail)
            return
        batch.status, batch.error = "converting", None
        self._save(plan)

    async def _step_convert(self, plan: PlanRecord, batch: PlanBatch, record: Any) -> None:
        run = record.conversion_run
        if record.status in IN_FLIGHT:
            if (batch.status, batch.error) != ("converting", None):
                batch.status, batch.error = "converting", None
                self._save(plan)
            return
        if not isinstance(run, WorkspaceRun):
            self._pause(plan, batch, record.error or "The batch conversion needs attention")
            return
        if record.status == "completed" and (Path(run.dataset_dir) / DATASET_JSON).is_file():
            batch.status, batch.dataset, batch.error = "completed", run.name, None
            batch.convert_s = run_seconds(run)
            plan.cursor += 1
            if plan.cursor >= len(plan.batches):
                plan.status = "completed"
            self._save(plan)
            return
        self._pause(plan, batch, record.error or "The batch conversion needs attention")

    async def _record_patients(self, plan: PlanRecord, batch: PlanBatch, operation: str) -> None:
        ids = await asyncio.to_thread(self.operations.patient_ids, operation)
        hashes = sorted(
            hashlib.sha256(f"{plan.salt}:{pid}".encode()).hexdigest()[:24] for pid in ids
        )
        batch.patient_hashes = hashes
        plan.warnings = [w for w in plan.warnings if w.batch_index != batch.index]
        earlier: dict[int, set[str]] = {
            b.index: set(b.patient_hashes or []) for b in plan.batches if b.index < batch.index
        }
        seen = set(hashes)
        shared = {h for h in seen if any(h in other for other in earlier.values())}
        if shared:
            where = sorted(i for i, other in earlier.items() if seen & other)
            plan.warnings.append(
                BatchWarning(
                    batch_index=batch.index,
                    earlier_batches=where,
                    patients=len(shared),
                    message=(
                        f"{len(shared)} patient(s) in this batch also appear in "
                        f"batch {', '.join(str(i) for i in where)}"
                    ),
                )
            )
        self._save(plan)
