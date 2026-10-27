"""Task service: list, validate, preflight, estimate, runs, outputs.

Stateless: routers build one per request from the app context. The API process writes the run
record (`tasks/runs/{run_id}/`), the segmentation-set registration and the derived ledger under
the project lock; the task writes only its job dir and its `output_dir`.
`radiomics.pyradiomics` is served by the radiomics service behind the same endpoints.
Modules: `records` → `selection` → `jobspec` → `estimate` → `registration` → `driver` → here.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.core import reviewer as reviewer_stamp
from app.core.errors import JobConflict, Problem, ValidationProblem
from app.core.fsio import append_jsonl, read_json
from app.core.ids import is_ulid, new_ulid, utc_now
from app.jobs.types import TERMINAL, JobHandle, JobSpec
from app.projects.models import SEG_ID_RE
from app.tasks import control, dry_run, protocol, registry
from app.tasks.dicom_execution import attempt_cleaned
from app.tasks.dicom_resources import require_pixel_budget
from app.tasks.driver import DriverBase
from app.tasks.dry_run import DICOM_CONVERT
from app.tasks.identity import committed_outputs, create_identity, verify_resume
from app.tasks.jobspec import bind_inventory
from app.tasks.models import (
    TERMINAL_TASK_RUN,
    TaskInfo,
    TaskItemError,
    TaskList,
    TaskRef,
    TaskResourceWait,
    TaskRunCounts,
    TaskRunDetail,
    TaskRunInput,
    TaskRunListItem,
    TaskRunOutput,
    TaskRunProgress,
    TaskRunRecord,
    TaskRunRequest,
    TaskRunStarted,
    TaskValidateResult,
)
from app.tasks.records import CANCEL_GRACE_S, ITEMS, Live, dicom_history, item_outcomes
from app.tasks.registry import RADIOMICS_TASK
from app.tasks.schema import normalize, settings_hash

_SEG_RE = re.compile(SEG_ID_RE)
log = logging.getLogger("app.tasks")


class TaskService(DriverBase):
    async def recover_all(self) -> None:
        for project in self.workspace.list():
            try:
                for run_dir in self.runs.run_dirs(project.project_id):
                    await self._recover_dicom(project.project_id, run_dir)
                    await self._recover_external(project.project_id, run_dir)
            except (Problem, OSError, ValueError):
                log.warning(
                    "External recovery needs review", extra={"project_id": project.project_id}
                )

    async def _recover_dicom(
        self, pid: str, run_dir: Path, *, retry_registration: bool = False
    ) -> None:
        rec = self.runs.read(run_dir)
        if (rec.execution or {}).get("phase_step"):
            self.phase_runs.recover(pid, rec.run_id)
            return
        native_job_id = rec.job_id
        if rec.task.id != DICOM_CONVERT or not native_job_id:
            return
        if rec.status == "completed":
            await self._recover_registration(
                pid, run_dir, rec, native_job_id, retry_registration=retry_registration
            )
            return
        if rec.status in TERMINAL_TASK_RUN or (
            self.runs.job(rec.job_id) is not None and rec.status != "cleanup_pending"
        ):
            return
        job = run_dir / "attempts" / native_job_id
        cleaned = attempt_cleaned(job, rec.attempts)
        outcomes, total = await asyncio.to_thread(dicom_history, run_dir, rec.attempts)
        n = Counter(event["status"] for event in outcomes.values())

        def recover(current: TaskRunRecord) -> None:
            if (
                current.attempts != rec.attempts
                or current.job_id != rec.job_id
                or current.status in TERMINAL_TASK_RUN
            ):
                return
            current.counts = TaskRunCounts(
                items=total + n["skipped"],
                ok=n["ok"],
                failed=n["failed"],
                skipped=n["skipped"],
                pending=max(0, total - n["ok"] - n["failed"]),
            )
            current.execution = {
                **(current.execution or {}),
                "attempt": current.attempts,
                "cleanup_verified": cleaned,
            }
            current.status = "interrupted" if cleaned else "cleanup_pending"
            current.error = "Backend interrupted; resume after verified cleanup"

        await self.runs.update(pid, run_dir, recover)

    async def _recover_registration(
        self,
        pid: str,
        run_dir: Path,
        rec: TaskRunRecord,
        native_job_id: str,
        *,
        retry_registration: bool,
    ) -> None:
        key = f"dicom.registration:{rec.run_id}"
        lock = self.locks(f"_dicom_registration:{pid}:{rec.run_id}")
        if (rec.execution or {}).get("registration_cancel_requested"):
            if retry_registration:
                if not (rec.execution or {}).get("registration_cancelled"):
                    raise JobConflict("Wait for metadata registration to stop before resuming")
                async with self.locks(pid):
                    rec = self.runs.read(run_dir)
                    for field in ("registration_cancel_requested", "registration_cancelled"):
                        if rec.execution is not None:
                            rec.execution.pop(field, None)
                    self.runs.write(run_dir, rec)
            elif (rec.execution or {}).get("registration_cancelled"):
                return
        if lock.locked() or self.jobs.active(pid, "task", key) is not None:
            return
        if (
            rec.error
            and rec.error.startswith("output registration:")
            and not retry_registration
            and (
                self.runs.job(rec.job_id) is not None
                or self.runs.job((rec.execution or {}).get("registration_job_id")) is not None
            )
        ):
            return
        job = run_dir / "attempts" / native_job_id
        result = protocol.read_result(job)
        if result is None or not attempt_cleaned(job, rec.attempts):
            return
        manifest = rec.manifest_snapshot or self.registry.get(rec.task.id).manifest
        live = Live(pid, rec.run_id, run_dir, job, manifest, rec.selection.seg_id)
        try:
            checkpoint = read_json(run_dir / "registration.json")
        except (OSError, ValueError):
            checkpoint = None
        if (
            isinstance(checkpoint, dict)
            and checkpoint.get("status") == "completed"
            and checkpoint.get("index_verified") is True
        ):
            try:
                await self._finalize_dicom(live, result)
            except Exception as exc:
                await self._record_registration_error(pid, run_dir, exc)
            return

        async def recover_registration(_handle: JobHandle) -> None:
            try:
                await self._finalize_dicom(live, result)
            except Exception as exc:
                await self._record_registration_error(pid, run_dir, exc)
                raise

        async with lock:
            if self.jobs.active(pid, "task", key) is not None:
                return
            registration_job = new_ulid()
            async with self.locks(pid):
                current = self.runs.read(run_dir)
                current.execution = {
                    **(current.execution or {}),
                    "registration_pending": True,
                    "registration_job_id": registration_job,
                }
                if current.error and current.error.startswith("output registration:"):
                    current.error = None
                self.runs.write(run_dir, current)
            self.jobs.submit(
                JobSpec(
                    project_id=pid,
                    job_id=registration_job,
                    kind="task",
                    units=[],
                    key=key,
                    ref=rec.run_id,
                    driver=recover_registration,
                )
            )
        return

    def list_tasks(self) -> TaskList:
        return TaskList(
            tasks=[self._info(t) for t in self.registry.tasks.values()],
            invalid=list(self.registry.invalid),
            runners=registry.runners(self.queue_dir),
        )

    def get(self, task_id: str) -> TaskInfo:
        return self._info(self.registry.get(task_id))

    def validate(
        self,
        task_id: str,
        raw: dict[str, Any],
        labels: list[int] | None = None,
        n_items: int | None = None,
    ) -> TaskValidateResult:
        info = self.get(task_id)
        if task_id == RADIOMICS_TASK:
            return self._radiomics().validate_task(raw, labels, n_items)
        m = info.manifest
        norm, issues = normalize(m.settings_schema, m.defaults, raw)
        ok = not any(i.severity == "error" for i in issues)
        return TaskValidateResult(
            ok=ok,
            issues=issues,
            settings=norm if ok else None,
            settings_hash=settings_hash(m.id, m.version, norm) if ok else None,
        )

    async def start(
        self,
        pid: str,
        req: TaskRunRequest,
        reviewer: str | None,
        *,
        run_id: str | None = None,
        source_inventory: dict[str, Any] | None = None,
    ) -> TaskRunStarted:
        if req.task_id == RADIOMICS_TASK:
            return await self._radiomics().start_task(pid, req, reviewer)
        info = self.get(req.task_id)
        if run_id is not None:
            if req.task_id != DICOM_CONVERT or not is_ulid(run_id):
                raise JobConflict(
                    "Reserved run identities are only supported for DICOM source operations"
                )
            reserved = self._runs_dir(pid) / run_id
            if (reserved / "run.json").exists():
                prior = self.runs.read(reserved)
                _, requested_hash = self._settings(info.manifest, req.settings)
                if (
                    prior.task.id != req.task_id
                    or prior.settings_hash != requested_hash
                    or prior.selection.source != req.selection.source
                ):
                    raise JobConflict("Reserved conversion request changed")
                bind_inventory(reserved, self.settings.workspace_root, source_inventory)
                if prior.job_id:
                    await self._recover_dicom(pid, reserved)
                    prior = self.runs.read(reserved)
                    assert prior.job_id is not None
                    return TaskRunStarted(run_id=run_id, job_id=prior.job_id, status=prior.status)
                return await self._submit(pid, reserved, info.manifest, [], None, skip=[])
            if reserved.exists() and any(reserved.iterdir()):
                raise JobConflict(
                    "Reserved conversion record is missing; review retained attempt evidence"
                )
        for previous in self.runs.run_dirs(pid):
            if self.runs.read(previous).task.id == req.task_id:
                await self._recover_dicom(pid, previous)
                await self._recover_external(pid, previous)
                await control.settle(self, pid, previous)
                if self.runs.read(previous).status in control.STOPPING:
                    raise JobConflict(
                        f"Run {previous.name} is still stopping; wait for its verified cleanup"
                    )
        m = info.manifest
        if not info.available:
            raise ValidationProblem(f"Task {m.id} is unavailable: {info.unavailable_reason}")
        who = reviewer_stamp.optional(reviewer)
        settings, shash = self._settings(m, req.settings)
        cfg = self.workspace.get(pid)
        source = self._source(req.selection) if m.input == "source" else None
        if source is not None and source_inventory is None:
            await dry_run.require_dicom(m.id, Path(source))
        items = [] if source is not None else await self.select(pid, req.selection)
        seg_id = self._seg_id(cfg, m, req.selection)
        ready = [i for i in items if self._not_ready(cfg, m, i, seg_id) is None]
        if not ready and source is None:
            raise ValidationProblem(
                "No selected item is ready for this task",
                errors=[{"loc": ["body", "selection"], "msg": "Nothing to run"}],
            )
        target = settings.get("seg_id") if "masks" in m.outputs else None
        if target is not None and (not isinstance(target, str) or not _SEG_RE.match(target)):
            raise ValidationProblem(
                "seg_id must be a lower-case slug",
                errors=[{"loc": ["body", "settings", "seg_id"], "msg": SEG_ID_RE}],
            )
        if target is not None and cfg.segmentation(target) is not None:
            raise ValidationProblem(
                f"Segmentation set {target!r} already exists; choose another seg_id",
                errors=[{"loc": ["body", "settings", "seg_id"], "msg": "exists"}],
            )
        self._check_conflict(pid, m.id)
        identity = await asyncio.to_thread(
            create_identity, info, settings, self._job_items(pid, ready, seg_id)
        )
        rid = run_id or new_ulid()
        out_dir = self._output_dir(pid, m, rid)
        if m.id == DICOM_CONVERT:
            require_pixel_budget(self.settings)
        now = utc_now()
        selected_seg = cfg.segmentation(seg_id) if seg_id else None
        rec = TaskRunRecord(
            run_id=rid,
            task=TaskRef(id=m.id, version=m.version, manifest_hash=info.manifest_hash),
            name=(req.name or "").strip() or f"{m.title} {now}",
            status="queued",
            created_at=now,
            reviewer=who,
            runtime=m.runtime.type,
            settings=settings,
            settings_hash=shash,
            identity=identity,
            supervised=m.runtime.type == "external" and m.resources.gpu in {"required", "optional"},
            manifest_snapshot=m.model_copy(deep=True),
            selection=req.selection.model_copy(update={"seg_id": seg_id, "source": source}),
            item_ids=[i.item_id for i in ready],
            inputs=[
                TaskRunInput(
                    item_id=i.item_id,
                    image_fp=i.image.fp if i.image else None,
                    seg_id=seg_id,
                    mask_fp=(i.masks[seg_id].fp if seg_id and seg_id in i.masks else None),
                    removed_labels=(selected_seg.removed_labels if selected_seg else []),
                )
                for i in ready
            ],
            output_dir=str(out_dir) if out_dir else None,
            counts=TaskRunCounts(items=len(ready), skipped=len(items) - len(ready)),
        )
        run_dir = self._runs_dir(pid) / rid
        async with self.locks(pid):
            current_seg = self.workspace.get(pid).segmentation(seg_id) if seg_id else None
            if seg_id and (
                current_seg is None
                or current_seg.removed_labels
                != (selected_seg.removed_labels if selected_seg else [])
            ):
                raise JobConflict("Segmentation label selection changed; start a new run")
            run_dir.mkdir(parents=True, exist_ok=True)
            skipped = [
                {
                    "item_id": i.item_id,
                    "status": "skipped",
                    "message": self._not_ready(cfg, m, i, seg_id),
                }
                for i in items
                if i not in ready
            ]
            if skipped:
                append_jsonl(run_dir / ITEMS, skipped)
            self.runs.write(run_dir, rec)
            bind_inventory(run_dir, self.settings.workspace_root, source_inventory)
        return await self._submit(pid, run_dir, m, ready, seg_id, skip=[])

    async def get_run(
        self, pid: str, rid: str, *, retry_registration: bool = False
    ) -> TaskRunDetail:
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            return await rad.task_detail(pid, rid)
        run_dir = self.runs.run_dir(pid, rid)
        await self._recover_dicom(pid, run_dir, retry_registration=retry_registration)
        await self._recover_external(pid, run_dir)
        await control.settle(self, pid, run_dir)
        rec = self.runs.read(run_dir)
        if not (rec.execution or {}).get("phase_step"):
            rec = await self.runs.reconcile(pid, run_dir)
        job = self.runs.job(rec.job_id)
        progress = None
        execution = rec.execution or {}
        resource_wait = None
        phase_step = execution.get("phase_step") is True
        if (rec.task.id == DICOM_CONVERT or phase_step) and execution.get("progress"):
            progress = TaskRunProgress.model_validate(execution["progress"])
        if rec.task.id == DICOM_CONVERT and execution.get("resource_wait"):
            resource_wait = TaskResourceWait.model_validate(execution["resource_wait"])
        if job is not None and job.status not in TERMINAL:
            if not (phase_step and execution.get("shared_conversion_job")) and (
                rec.task.id != DICOM_CONVERT or progress is None
            ):
                progress = TaskRunProgress(
                    done=job.done,
                    total=job.total,
                    eta_s=None if rec.task.id == DICOM_CONVERT or phase_step else job.eta_s,
                    stage="analyzing" if phase_step else None,
                    stage_done=job.done if phase_step else 0,
                    stage_total=job.total if phase_step else 0,
                )
            if job.status == "waiting_for_runner" and rec.status == "queued":
                rec.status = "waiting_for_runner"
        return TaskRunDetail(
            **rec.model_dump(),
            progress=progress,
            resource_wait=resource_wait,
            conversion_time=execution.get("conversion_time"),
        )

    async def list_runs(
        self, pid: str, task_id: str | None = None, *, archived: bool = False
    ) -> list[TaskRunListItem]:
        """Archived runs are listed only on request; their records stay on disk."""
        out: list[TaskRunListItem] = []
        for run_dir in self.runs.run_dirs(pid):
            await self._recover_dicom(pid, run_dir)
            await self._recover_external(pid, run_dir)
            await control.settle(self, pid, run_dir)
            rec = self.runs.read(run_dir)
            if not (rec.execution or {}).get("phase_step"):
                rec = await self.runs.reconcile(pid, run_dir)
            if rec.archived == archived:
                out.append(TaskRunListItem.model_validate(rec.model_dump()))
        if not archived:
            out += await self._radiomics().task_summaries(pid)
        if task_id is not None:
            out = [r for r in out if r.task.id == task_id]
        return sorted(out, key=lambda r: r.run_id, reverse=True)

    async def cancel(
        self, pid: str, rid: str, *, expected_attempt: int | None = None
    ) -> TaskRunDetail:
        if not self._radiomics().has_run(pid, rid):
            rec = self.runs.read(self.runs.run_dir(pid, rid))
            if (rec.execution or {}).get("phase_step"):
                await self.phase_runs.cancel(pid, rid, expected_attempt)
                return await self.get_run(pid, rid)
            if rec.task.id == DICOM_CONVERT:
                async with self.locks(f"_dicom_control:{pid}:{rid}"):
                    return await self._cancel(pid, rid, expected_attempt=expected_attempt)
        return await self._cancel(pid, rid, expected_attempt=expected_attempt)

    async def _cancel(
        self, pid: str, rid: str, *, expected_attempt: int | None = None
    ) -> TaskRunDetail:
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            await rad.cancel(pid, rid)
            return await rad.task_detail(pid, rid)
        run_dir = self.runs.run_dir(pid, rid)
        rec = self.runs.read(run_dir)
        if rec.supervised:
            return await control.request_control(self, pid, rid, "cancel")
        if expected_attempt is not None and rec.attempts != expected_attempt:
            raise JobConflict("Conversion run attempt changed; reload before controlling it")
        if rec.task.id == DICOM_CONVERT and rec.status == "completed":
            await self._cancel_registration(pid, rid, run_dir)
            return await self.get_run(pid, rid)
        if rec.task.id == DICOM_CONVERT and rec.status not in TERMINAL_TASK_RUN:
            if rec.job_id and self.runs.job(rec.job_id) is not None:
                protocol.request_cancel(run_dir / "attempts" / rec.job_id)

                def cancelling(current: TaskRunRecord) -> bool:
                    if current.attempts != rec.attempts:
                        raise JobConflict(
                            "Conversion run attempt changed; reload before cancelling"
                        )
                    if current.status in TERMINAL_TASK_RUN:
                        return False
                    current.status = "cancelling"
                    return True

                await self.runs.update(pid, run_dir, cancelling)
                self.jobs.cancel(rec.job_id)
            return await self.get_run(pid, rid)
        await self.runs.cancel(pid, run_dir, CANCEL_GRACE_S + 5)
        return await self.get_run(pid, rid)

    async def pause(self, pid: str, rid: str) -> TaskRunDetail:
        """Stop dispatch, keep committed cases; `paused` once cleanup is verified."""
        if self._radiomics().has_run(pid, rid):
            raise JobConflict("This run does not support supervised controls")
        return await control.request_control(self, pid, rid, "pause")

    async def archive(self, pid: str, rid: str) -> TaskRunDetail:
        """Hide an inactive supervised run; records, masks and sources are kept."""
        if self._radiomics().has_run(pid, rid):
            raise JobConflict("Only inactive supervised runs can be archived")
        return await control.archive(self, pid, rid)

    async def resume(
        self,
        pid: str,
        rid: str,
        *,
        expected_attempt: int | None = None,
        request_id: str | None = None,
        failed_only: bool = False,
    ) -> TaskRunStarted:
        """A new attempt that skips the items already `ok`."""
        if not self._radiomics().has_run(pid, rid):
            rec = self.runs.read(self.runs.run_dir(pid, rid))
            if failed_only and (rec.task.id != DICOM_CONVERT or expected_attempt is None):
                raise JobConflict("Retry failed requires a conversion run and its current attempt")
            if (rec.execution or {}).get("phase_step"):
                return await self.phase_runs.resume(pid, rid, expected_attempt)
            if rec.task.id == DICOM_CONVERT:
                async with self.locks(f"_dicom_control:{pid}:{rid}"):
                    return await self._resume(
                        pid,
                        rid,
                        expected_attempt=expected_attempt,
                        request_id=request_id,
                        failed_only=failed_only,
                    )
        return await self._resume(
            pid,
            rid,
            expected_attempt=expected_attempt,
            request_id=request_id,
            failed_only=failed_only,
        )

    async def _resume(
        self,
        pid: str,
        rid: str,
        *,
        expected_attempt: int | None = None,
        request_id: str | None = None,
        failed_only: bool = False,
    ) -> TaskRunStarted:
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            if failed_only:
                raise JobConflict("Retry failed is supported only for DICOM conversion")
            d = await rad.resume(pid, rid)
            return TaskRunStarted(run_id=rid, job_id=d.job_id, status="queued")
        run_dir = self.runs.run_dir(pid, rid)
        await self._recover_dicom(pid, run_dir)
        await self._recover_external(pid, run_dir)
        await control.settle(self, pid, run_dir)
        previous = self.runs.read(run_dir)
        if failed_only:
            request_id = request_id or f"retry-failed:{rid}:{expected_attempt}"
            if (
                previous.attempts == (expected_attempt or 0) + 1
                and previous.resume_request_id == request_id
            ):
                return TaskRunStarted(run_id=rid, job_id=previous.job_id, status=previous.status)
        if previous.archived:
            raise JobConflict("Archived runs are read-only")
        if previous.runtime == "external" and previous.job_id:
            job = self.queue_dir / previous.job_id
            if (job / "attempt.json").exists() and not protocol.external_finished(job):
                raise JobConflict("Prior external attempt cleanup is pending; resume is blocked")
        rec = await self.runs.resumable(pid, run_dir)
        if expected_attempt is not None and rec.attempts != expected_attempt:
            raise JobConflict("Conversion run attempt changed; reload before controlling it")
        if rec.task.id == DICOM_CONVERT:
            require_pixel_budget(self.settings)
        if (
            rec.task.id == DICOM_CONVERT
            and rec.job_id
            and not attempt_cleaned(run_dir / "attempts" / rec.job_id, rec.attempts)
        ):
            raise JobConflict("Prior DICOM execution cleanup is unconfirmed; resume is blocked")
        info = self.get(rec.task.id)
        m = info.manifest
        if m.version != rec.task.version:
            raise JobConflict(
                f"Run used {m.id} {rec.task.version}; installed is {m.version}. Start a new run."
            )
        self._check_conflict(pid, m.id)
        segmentation = (
            self.workspace.get(pid).segmentation(rec.selection.seg_id)
            if rec.selection.seg_id
            else None
        )
        if rec.selection.seg_id and (
            segmentation is None
            or any(pinned.removed_labels != segmentation.removed_labels for pinned in rec.inputs)
        ):
            raise JobConflict("Segmentation label selection changed; start a new run")
        idx = self.store.load(pid)
        items = [idx.by_id[i] for i in rec.item_ids if i in idx.by_id]
        if m.id == "segment.nnunet" and m.resources.gpu == "required":
            try:
                outputs = committed_outputs(rec.outputs, self.workspace.resolver(pid).resolve)
                await asyncio.to_thread(
                    verify_resume,
                    rec.identity,
                    info,
                    rec.settings,
                    self._job_items(pid, items, rec.selection.seg_id),
                    outputs,
                )
            except (OSError, ValueError, Problem) as exc:
                raise JobConflict(
                    "Cannot resume: pinned model, inputs or committed outputs changed or are "
                    "unavailable. Start a new run."
                ) from exc
        ok = [k for k, v in item_outcomes(run_dir).items() if v["status"] == "ok"]
        retry_item_ids = None
        if failed_only:
            outcomes, _ = await asyncio.to_thread(dicom_history, run_dir, rec.attempts)
            retry_item_ids = [
                iid for iid, outcome in outcomes.items() if outcome["status"] == "failed"
            ]
            if not retry_item_ids:
                raise JobConflict(
                    "No recorded failed series remain; Resume pending for unattempted series"
                )
        return await self._submit(
            pid,
            run_dir,
            m,
            items,
            rec.selection.seg_id,
            skip=ok,
            resume_request_id=request_id,
            retry_item_ids=retry_item_ids,
        )

    def errors(self, pid: str, rid: str) -> list[TaskItemError]:
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            return rad.task_errors(pid, rid)
        run_dir = self.runs.run_dir(pid, rid)
        return [
            TaskItemError(item_id=k, status=v["status"], message=v.get("message") or "")
            for k, v in sorted(item_outcomes(run_dir).items())
            if v["status"] != "ok"
        ]

    def outputs(self, pid: str, rid: str) -> list[TaskRunOutput]:
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            return rad.task_outputs(pid, rid)
        return self.runs.read(self.runs.run_dir(pid, rid)).outputs
