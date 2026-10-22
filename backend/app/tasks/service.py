"""Task service: list, validate, preflight, estimate, runs, outputs (TSK-01..12, API-42..47).

Stateless: routers build one per request from the app context. The API process writes the run
record (`tasks/runs/{run_id}/`), the segmentation-set registration and the derived ledger under
the project lock (BE-05); the task writes only its job dir and its `output_dir` (ADR-0014).
`radiomics.pyradiomics` is served by the radiomics service behind the same endpoints (RAD-13).
Modules: `records` → `selection` → `jobspec` → `estimate` → `registration` → `driver` → here.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from app.core import reviewer as reviewer_stamp
from app.core.errors import JobConflict, Problem, ValidationProblem
from app.core.fsio import append_jsonl
from app.core.ids import new_ulid, utc_now
from app.jobs.types import TERMINAL
from app.projects.models import SEG_ID_RE
from app.tasks import control, dry_run, protocol, registry
from app.tasks.driver import DriverBase
from app.tasks.identity import committed_outputs, create_identity, verify_resume
from app.tasks.models import (
    TaskInfo,
    TaskItemError,
    TaskList,
    TaskRef,
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
from app.tasks.records import CANCEL_GRACE_S, ITEMS, item_outcomes
from app.tasks.registry import RADIOMICS_TASK
from app.tasks.schema import normalize, settings_hash

_SEG_RE = re.compile(SEG_ID_RE)
log = logging.getLogger("app.tasks")


class TaskService(DriverBase):
    """Stateless facade of API-42..47: routers build one per request from the app context."""

    async def recover_all(self) -> None:
        for project in self.workspace.list():
            try:
                for run_dir in self.runs.run_dirs(project.project_id):
                    await self._recover_external(project.project_id, run_dir)
            except (Problem, OSError, ValueError):
                log.warning(
                    "External recovery needs review", extra={"project_id": project.project_id}
                )

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

    async def start(self, pid: str, req: TaskRunRequest, reviewer: str | None) -> TaskRunStarted:
        if req.task_id == RADIOMICS_TASK:
            return await self._radiomics().start_task(pid, req, reviewer)
        info = self.get(req.task_id)
        for previous in self.runs.run_dirs(pid):
            if self.runs.read(previous).task.id == req.task_id:
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
        if source is not None:
            await dry_run.require_dicom(m.id, Path(source))  # AUD-A2-07
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
        rid = new_ulid()
        out_dir = self._output_dir(pid, m, rid)
        now = utc_now()
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
                )
                for i in ready
            ],
            output_dir=str(out_dir) if out_dir else None,
            counts=TaskRunCounts(items=len(ready), skipped=len(items) - len(ready)),
        )
        run_dir = self._runs_dir(pid) / rid
        async with self.locks(pid):
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
        return await self._submit(pid, run_dir, m, ready, seg_id, skip=[])

    async def get_run(self, pid: str, rid: str) -> TaskRunDetail:
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            return await rad.task_detail(pid, rid)
        run_dir = self.runs.run_dir(pid, rid)
        await self._recover_external(pid, run_dir)
        await control.settle(self, pid, run_dir)
        rec = await self.runs.reconcile(pid, run_dir)
        job = self.runs.job(rec.job_id)
        progress = None
        if job is not None and job.status not in TERMINAL:
            progress = TaskRunProgress(done=job.done, total=job.total, eta_s=job.eta_s)
            if job.status == "waiting_for_runner" and rec.status == "queued":
                rec.status = "waiting_for_runner"
        return TaskRunDetail(**rec.model_dump(), progress=progress)

    async def list_runs(
        self, pid: str, task_id: str | None = None, *, archived: bool = False
    ) -> list[TaskRunListItem]:
        """Archived runs are listed only on request (J6); their records stay on disk."""
        out: list[TaskRunListItem] = []
        for run_dir in self.runs.run_dirs(pid):
            await self._recover_external(pid, run_dir)
            await control.settle(self, pid, run_dir)
            rec = await self.runs.reconcile(pid, run_dir)
            if rec.archived == archived:
                out.append(TaskRunListItem.model_validate(rec.model_dump()))
        if not archived:
            out += await self._radiomics().task_summaries(pid)
        if task_id is not None:
            out = [r for r in out if r.task.id == task_id]
        return sorted(out, key=lambda r: r.run_id, reverse=True)

    async def cancel(self, pid: str, rid: str) -> TaskRunDetail:
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            await rad.cancel(pid, rid)
            return await rad.task_detail(pid, rid)
        if self.runs.read(self.runs.run_dir(pid, rid)).supervised:
            return await control.request_control(self, pid, rid, "cancel")  # J5
        await self.runs.cancel(pid, self.runs.run_dir(pid, rid), CANCEL_GRACE_S + 5)
        return await self.get_run(pid, rid)

    async def pause(self, pid: str, rid: str) -> TaskRunDetail:
        """J3: stop dispatch, keep committed cases; `paused` once cleanup is verified."""
        if self._radiomics().has_run(pid, rid):
            raise JobConflict("This run does not support supervised controls")
        return await control.request_control(self, pid, rid, "pause")

    async def archive(self, pid: str, rid: str) -> TaskRunDetail:
        """J6: hide an inactive supervised run; records, masks and sources are kept."""
        if self._radiomics().has_run(pid, rid):
            raise JobConflict("Only inactive supervised runs can be archived")
        return await control.archive(self, pid, rid)

    async def resume(self, pid: str, rid: str) -> TaskRunStarted:
        """TSK-07: a new attempt that skips the items already `ok` (resume.skip)."""
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            d = await rad.resume(pid, rid)
            return TaskRunStarted(run_id=rid, job_id=d.job_id, status="queued")
        run_dir = self.runs.run_dir(pid, rid)
        await self._recover_external(pid, run_dir)
        await control.settle(self, pid, run_dir)
        previous = self.runs.read(run_dir)
        if previous.archived:
            raise JobConflict("Archived runs are read-only")
        if previous.runtime == "external" and previous.job_id:
            job = self.queue_dir / previous.job_id
            if (job / "attempt.json").exists() and not protocol.external_finished(job):
                raise JobConflict("Prior external attempt cleanup is pending; resume is blocked")
        rec = await self.runs.resumable(pid, run_dir)
        info = self.get(rec.task.id)
        m = info.manifest
        if m.version != rec.task.version:
            raise JobConflict(
                f"Run used {m.id} {rec.task.version}; installed is {m.version}. Start a new run."
            )
        self._check_conflict(pid, m.id)
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
        return await self._submit(pid, run_dir, m, items, rec.selection.seg_id, skip=ok)

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
