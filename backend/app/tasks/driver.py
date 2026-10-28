"""Driving a task attempt: submit the job, tail `progress.jsonl`, record item outcomes and logs,
finish the run record.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from app.core.errors import JobConflict
from app.core.fsio import append_jsonl, iter_jsonl
from app.core.ids import new_ulid, utc_now
from app.ingest.models import Item
from app.ingest.segsets import record_masks
from app.jobs.types import JobHandle, JobInfo, JobSpec
from app.tasks import control, protocol, registry
from app.tasks.builtin import run_entry
from app.tasks.dicom_execution import attempt_cleaned, run_dicom_job
from app.tasks.dry_run import DICOM_CONVERT
from app.tasks.identity import committed_outputs
from app.tasks.jobspec import inventory_spec
from app.tasks.models import (
    RESUMABLE_TASK_RUN,
    TERMINAL_TASK_RUN,
    ConversionTimeEstimate,
    TaskManifest,
    TaskRunCounts,
    TaskRunOutput,
    TaskRunProgress,
    TaskRunRecord,
    TaskRunStarted,
    TaskRunStatus,
)
from app.tasks.records import (
    CANCEL_GRACE_S,
    ITEMS,
    LEDGER,
    LOGS,
    Live,
    dicom_history,
    item_outcomes,
)
from app.tasks.registration import RegistrationBase

log = logging.getLogger("app.tasks")
POLL_S: Final = 0.2
RUNNER_LOST_S: Final = 60.0  # a claimed job whose runner has no fresh heartbeat for this long


class DriverBase(RegistrationBase):
    """One attempt of a run: builtin worker or external runner, then `_finish`."""

    def _check_conflict(self, pid: str, task_id: str) -> None:
        cur = self.jobs.active(pid, "task", task_id)
        if cur is not None:
            raise JobConflict(f"A {task_id} run is already active: {cur.job_id}")

    async def _submit(
        self,
        pid: str,
        run_dir: Path,
        m: TaskManifest,
        items: Sequence[Item],
        seg_id: str | None,
        skip: Sequence[str],
        *,
        recover: bool = False,
        resume_request_id: str | None = None,
        retry_item_ids: list[str] | None = None,
    ) -> TaskRunStarted:
        rid = run_dir.name
        rec = self.runs.read(run_dir)
        if not recover and rec.attempts and rec.status not in RESUMABLE_TASK_RUN:
            raise JobConflict("Task run is already active; reload before resuming")
        phase_run_id = rec.phase_run_id
        if m.id == DICOM_CONVERT and rec.settings.get("phase_analyzer", True):
            phase_run_id = phase_run_id or new_ulid()
        prior_attempt = rec.attempts
        job_id = rec.job_id if recover else new_ulid()
        if job_id is None:
            raise JobConflict("External recovery has no recorded job identity")
        job_dir = self.job_dir(m, job_id)
        if m.id == DICOM_CONVERT:
            job_dir = run_dir / "attempts" / job_id
        spec = (
            json.loads((job_dir / "job.json").read_text())
            if recover
            else self._job_spec(
                pid,
                m,
                settings=rec.settings,
                items=items,
                seg_id=seg_id,
                output_dir=rec.output_dir,
                source=rec.selection.source,
            )
        )
        preparing_masks = any(
            mask.get("removed_labels") for item in spec["items"] for mask in item["masks"].values()
        )
        publish_in_driver = preparing_masks or m.runtime.type == "external"
        payload = spec
        if not recover:
            payload = {
                **spec,
                **inventory_spec(run_dir, self.settings.workspace_root),
                "job_id": job_id,
                "run_id": rid,
                "mode": "run",
                "resume": {"skip": list(skip)},
                **({"retry_item_ids": retry_item_ids} if retry_item_ids is not None else {}),
                "batch": {"size": m.resources.max_batch or max(1, len(items))},
                **(
                    {
                        "attempt": rec.attempts + 1,
                        "dicom_process_protocol": 1,
                        "analysis_state": str(run_dir / "phase-analyzer"),
                        "phase_run_id": phase_run_id,
                        "phase_cancel": str(self._runs_dir(pid) / phase_run_id / protocol.CANCEL)
                        if phase_run_id
                        else None,
                    }
                    if m.id == DICOM_CONVERT
                    else {}
                ),
                **(
                    {
                        "identity": rec.identity,
                        "committed_outputs": committed_outputs(
                            rec.outputs, self.workspace.resolver(pid).resolve
                        ),
                    }
                    if rec.identity
                    else {}
                ),
            }
            if not publish_in_driver:
                protocol.write_job(job_dir, payload)
        live = Live(pid, rid, run_dir, job_dir, m, rec.selection.seg_id)
        events = [*iter_jsonl(run_dir / ITEMS), *iter_jsonl(run_dir / LOGS)]
        live.seen_events = {str(row["event_id"]) for row in events if row.get("event_id")}
        live.seen_items = {
            str(row["item_id"])
            for row in events
            if row.get("item_id") and str(row.get("event_id", "")).startswith(f"{job_id}:")
        }
        live.done = rec.progress_done if recover else 0
        live.dataset_dir = Path(spec["dataset_dir"]) if "dataset_dir" in spec else None
        live.registered = any(
            s.producer is not None and s.producer.run_id == rid
            for s in self.workspace.get(pid).segmentations
        )
        n_todo = (
            len(spec.get("items", []))
            if recover
            else len([i for i in items if i.item_id not in set(skip)])
        )

        async def driver(h: JobHandle) -> None:
            if preparing_masks:
                await self._prepare_mask_inputs(pid, payload, h)
            if not recover and publish_in_driver:
                async with self.locks(pid):
                    if h.stopped or self.runs.read(run_dir).job_id != job_id:
                        return
                    protocol.write_job(job_dir, payload)
            if m.runtime.type == "external":
                await self._drive_external(h, live, n_todo)
            else:
                await self._drive(h, live, n_todo)
            result = protocol.read_result(live.job_dir)
            if m.id == "segment.nnunet" and result and result.get("status") == "failed":
                failures = [
                    v.get("message")
                    for v in item_outcomes(live.run_dir).values()
                    if v.get("status") == "failed"
                ]
                raise RuntimeError(
                    result.get("error")
                    or next(
                        (message for message in failures if message),
                        "Task failed; see its error details",
                    )
                )

        async def on_finish(info: JobInfo) -> str | None:
            await self._finish(live, info)
            return rid

        job_spec = JobSpec(
            project_id=pid,
            kind="task",
            units=[],
            drain_workers=preparing_masks,
            driver=driver,
            on_finish=on_finish,
            ref=rid,
            job_id=job_id,
            key=m.id,
            detach_on_shutdown=m.runtime.type == "external"
            and m.resources.gpu in {"required", "optional"},
        )

        def prepare(rec: TaskRunRecord) -> None:
            if rec.attempts != prior_attempt:
                raise JobConflict("Task run attempt changed; reload before resuming")
            rec.error, rec.finished_at = None, None
            rec.attempts += 1
            rec.resume_request_id = resume_request_id
            rec.progress_cursor, rec.progress_done = 0, 0
            if m.id == DICOM_CONVERT:
                rec.phase_run_id = phase_run_id
                rec.execution = {
                    "attempt": rec.attempts,
                    "cleanup_verified": False,
                    "progress": TaskRunProgress(done=0, total=0).model_dump(),
                }

        if recover:
            self.jobs.submit(job_spec)

            def reattached(rec: TaskRunRecord) -> None:
                if not control.pending(rec):  # a pending pause/cancel keeps its stopping state
                    claimed = protocol.read_claim(job_dir) is not None
                    rec.status = "running" if claimed else "queued"
                rec.finished_at = None

            await self.runs.update(pid, run_dir, reattached)
        else:
            await self.runs.submit(
                pid,
                run_dir,
                job_spec,
                prepare=prepare,
                on_error=lambda: shutil.rmtree(job_dir, ignore_errors=True),
            )
        if m.id == DICOM_CONVERT:
            async with self.locks(pid):
                self.phase_runs.prepare(pid, self.runs.read(run_dir))
        return TaskRunStarted(run_id=rid, job_id=job_id, status="queued")

    async def _recover_external(self, pid: str, run_dir: Path) -> None:
        rec = self.runs.read(run_dir)
        if (
            rec.runtime != "external"
            or rec.job_id is None
            or rec.status in TERMINAL_TASK_RUN
            or self.runs.job(rec.job_id) is not None
        ):
            return
        job = self.queue_dir / rec.job_id
        if not (job / "job.json").is_file():
            return
        if rec.manifest_snapshot is not None:
            manifest = rec.manifest_snapshot
        else:
            info = self.registry.get(rec.task.id)
            if info.manifest_hash != rec.task.manifest_hash:
                raise JobConflict(
                    "Installed task manifest changed; external recovery requires review"
                )
            manifest = info.manifest
        if manifest.resources.gpu not in {"required", "optional"}:
            return
        spec = json.loads((job / "job.json").read_text())
        if spec.get("run_id") != rec.run_id or spec.get("job_id") != rec.job_id:
            raise JobConflict("External attempt identity does not match the run")
        await self._submit(pid, run_dir, manifest, [], rec.selection.seg_id, [], recover=True)

    async def _set_status(self, live: Live, status: TaskRunStatus) -> None:
        """Forward only, as `RunStore.set_status`; a pending control keeps pausing/cancelling."""

        def edit(rec: TaskRunRecord) -> bool:
            if rec.job_id != live.job_dir.name:
                return False
            if rec.status in TERMINAL_TASK_RUN or rec.status == status or control.pending(rec):
                return False
            rec.status = status
            if status == "running":
                rec.started_at = rec.started_at or utc_now()
            return True

        await self.runs.update(live.pid, live.run_dir, edit)

    async def _drive(self, h: JobHandle, live: Live, total: int) -> None:
        """Builtin: run the entry in a worker and tail its progress."""
        h.set_total(total)
        live.set_total = h.set_total
        tail = protocol.Tail(live.job_dir / protocol.PROGRESS)
        await self._set_status(live, "running")
        dicom = live.manifest.id == DICOM_CONVERT
        fut = asyncio.ensure_future(
            run_dicom_job(
                live.job_dir,
                workspace=self.settings.workspace_root,
                settings=self.settings,
                cancelled=lambda: h.stopped,
            )
            if dicom
            else h.run_in_worker(run_entry, live.manifest.runtime.entry, str(live.job_dir))
        )
        stop_at: float | None = None
        try:
            while True:
                await self._on_lines(live, tail.read())
                h.set_done(live.done)
                if fut.done():
                    break
                if h.stopped:
                    if not live.cancel_sent:
                        protocol.request_cancel(live.job_dir)
                        live.cancel_sent = True
                        stop_at = time.monotonic()
                    elif (
                        not dicom
                        and stop_at is not None
                        and time.monotonic() - stop_at > CANCEL_GRACE_S
                    ):
                        break
                await asyncio.sleep(POLL_S)
        finally:
            if dicom and not fut.done():
                fut.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await fut
            if fut.done() and not fut.cancelled():
                exit_code = int((fut.result() or {}).get("exit_code", 1))
                if exit_code != 0 and protocol.read_result(live.job_dir) is None:
                    raise RuntimeError(
                        f"task exited with code {exit_code}: "
                        + protocol.log_tail(live.job_dir)[-500:]
                    )
        await self._on_lines(live, tail.read())
        h.set_done(live.done)

    async def _drive_external(self, h: JobHandle, live: Live, total: int) -> None:
        """External: the host runner claims `queue/{job_id}`; we only tail it."""
        h.set_total(total)
        live.set_total = h.set_total
        rec = self.runs.read(live.run_dir)
        tail = protocol.Tail(
            live.job_dir / protocol.PROGRESS, offset=rec.progress_cursor, include_offsets=True
        )
        task_id = live.manifest.id
        claimed_by: str | None = None
        lost_since: float | None = None
        stop_at: float | None = None
        while True:
            await self._on_lines(live, tail.read(), cursor=tail.offset)
            h.set_done(live.done)
            if protocol.external_finished(live.job_dir):
                break
            claim = protocol.read_claim(live.job_dir)
            if claim is None and (live.job_dir / "pause").exists():
                break  # never claimed: the runner skips paused jobs
            if claim is None:
                waiting = not registry.runner_online(self.queue_dir, task_id)
                status: TaskRunStatus = "waiting_for_runner" if waiting else "queued"
                h.set_status("waiting_for_runner" if waiting else "queued")
                await self._set_status(live, status)
            elif claimed_by is None:
                claimed_by = str(claim.get("runner_id") or "")
                h.set_status("running")
                await self._set_status(live, "running")
            if claimed_by is not None:
                alive = any(
                    r.runner_id == claimed_by and r.fresh for r in registry.runners(self.queue_dir)
                )
                lost_since = None if alive else (lost_since or time.monotonic())
                if (
                    lost_since is not None
                    and time.monotonic() - lost_since > RUNNER_LOST_S
                    and not (live.job_dir / "attempt.json").exists()
                ):
                    raise RuntimeError(f"runner {claimed_by} stopped sending heartbeats")
            if h.stopped:
                if not live.cancel_sent:
                    protocol.request_cancel(live.job_dir)
                    live.cancel_sent = True
                    stop_at = time.monotonic()
                if protocol.read_claim(live.job_dir) is None:
                    break  # never claimed: the runner skips cancelled jobs
                if (
                    stop_at is not None
                    and time.monotonic() - stop_at > CANCEL_GRACE_S + 10
                    and not (live.job_dir / "attempt.json").exists()
                ):
                    break
            await asyncio.sleep(POLL_S)
        await self._on_lines(live, tail.read(), cursor=tail.offset)
        h.set_done(live.done)

    async def _on_lines(
        self, live: Live, lines: Sequence[dict[str, Any]], *, cursor: int | None = None
    ) -> None:
        if not lines:
            return
        current = self.runs.read(live.run_dir)
        if current.job_id != live.job_dir.name or current.status in TERMINAL_TASK_RUN:
            return
        item_rows: list[dict[str, Any]] = []
        logs: list[dict[str, Any]] = []
        masks: list[dict[str, Any]] = []
        stage_progress: dict[str, int | str] = {}
        conversion_time = None
        for line in lines:
            event = f"{live.job_dir.name}:{line['_offset']}" if "_offset" in line else None
            if event:
                if event in live.seen_events:
                    continue
                live.seen_events.add(event)
            t = line.get("t")
            if t == "total" and live.set_total is not None:
                total = int(line.get("n") or 0)
                live.set_total(total)
                stage_progress["total"] = total
            elif t == "log":
                logs.append(
                    {
                        "at": utc_now(),
                        "level": line.get("level", "info"),
                        "message": str(line.get("message", ""))[:2000],
                        **({"event_id": event} if event else {}),
                    }
                )
            elif t == "item":
                iid = str(line.get("item_id"))
                status = line.get("status")
                if status not in ("ok", "failed", "skipped"):
                    continue
                row = {
                    "item_id": iid,
                    "status": status,
                    "message": str(line.get("message") or "")[:2000],
                    **({"event_id": event} if event else {}),
                }
                if status == "ok":
                    try:
                        masks += await self._item_outputs(live, iid, line.get("outputs") or [])
                    except ValueError as exc:
                        row.update(status="failed", message=f"output: {exc}")
                if iid not in live.seen_items:
                    if live.manifest.id != DICOM_CONVERT or row["status"] == "ok":
                        live.done += 1
                    live.seen_items.add(iid)
                item_rows.append(row)
            elif t == "conversion_time" and live.manifest.id == DICOM_CONVERT:
                conversion_time = ConversionTimeEstimate.model_validate(line["estimate"])
            elif t == "stage" and live.manifest.id == DICOM_CONVERT:
                stage = line.get("stage")
                if stage == "admitted":
                    await self._set_status(live, "running")
                elif stage == "waiting_for_resources":
                    await self._set_status(live, "waiting_for_resources")
                    async with self.locks(live.pid):
                        current = self.runs.read(live.run_dir)
                        if (
                            current.job_id != live.job_dir.name
                            or current.status in TERMINAL_TASK_RUN
                        ):
                            return
                        current.execution = {
                            **(current.execution or {}),
                            "resource_wait": line.get("resource_wait"),
                        }
                        self.runs.write(live.run_dir, current)
                stage_progress.update(
                    stage=str(stage or ""),
                    stage_done=int(line.get("done") or 0),
                    stage_total=int(line.get("total") or 0),
                )
        if masks and not live.registered:
            await self._register_set(live, masks)
        async with self.locks(live.pid):
            rec = self.runs.read(live.run_dir)
            if rec.job_id != live.job_dir.name or rec.status in TERMINAL_TASK_RUN:
                return
            if item_rows:
                append_jsonl(live.run_dir / ITEMS, item_rows)
            if logs:
                append_jsonl(live.run_dir / LOGS, logs)
            if masks:
                record_masks(self.workspace.project_dir(live.pid), live.rid, masks)
            if live.manifest.id == DICOM_CONVERT:
                previous = (rec.execution or {}).get("progress", {})
                if stage_progress:
                    self.phase_runs.stage(live.pid, rec, stage_progress)
                rec.execution = {
                    **(rec.execution or {}),
                    "progress": TaskRunProgress.model_validate(
                        {"total": 0, **previous, **stage_progress, "done": live.done}
                    ).model_dump(),
                }
                if conversion_time is not None:
                    rec.execution["conversion_time"] = conversion_time.model_dump()
                if stage_progress.get("stage") == "admitted":
                    rec.execution["resource_wait"] = None
            rec.outputs += [output for output in live.outputs if output not in rec.outputs]
            if cursor is not None:
                rec.progress_cursor, rec.progress_done = cursor, live.done
            if live.manifest.resources.gpu == "required":
                self._record_gpu_ledger(live)
            self.runs.write(live.run_dir, rec)
        if masks and live.manifest.resources.gpu == "required":
            await self._reindex_masks(live.pid)

    async def _finish(self, live: Live, info: JobInfo) -> None:
        result = protocol.read_result(live.job_dir)
        async with self.locks(live.pid):
            rec = self.runs.read(live.run_dir)
            if rec.job_id != live.job_dir.name:
                return
            outcomes = {
                k: v
                for k, v in item_outcomes(live.run_dir).items()
                if k in set(rec.item_ids)
                or v["status"] == "skipped"
                or rec.task.id == DICOM_CONVERT
            }
            selected_total = info.total
            if rec.task.id == DICOM_CONVERT and result is None:
                outcomes, selected_total = await asyncio.to_thread(
                    dicom_history, live.run_dir, rec.attempts
                )
            n = Counter(v["status"] for v in outcomes.values())
            rec.counts = TaskRunCounts(
                items=len(rec.item_ids),
                ok=n["ok"],
                failed=n["failed"],
                skipped=n["skipped"],
                pending=max(0, len(rec.item_ids) - sum(n.values())),
            )
            if rec.task.id == DICOM_CONVERT:
                counts = (result or {}).get("estimate", {})
                rec.counts = TaskRunCounts(
                    items=int(counts.get("series", max(info.total, len(outcomes)))),
                    ok=int(counts.get("converted", 0))
                    + int(counts.get("already_converted", n["ok"])),
                    failed=int(counts.get("failed", n["failed"])),
                    skipped=int(counts.get("skipped", n["skipped"])),
                    pending=int(
                        counts.get("pending", max(0, selected_total - n["ok"] - n["failed"]))
                    ),
                )
            status: TaskRunStatus
            if info.status == "cancelled":
                status = "cancelled"
            elif info.status == "interrupted":
                status = "interrupted"
            elif info.status == "failed":
                status, rec.error = "failed", (result or {}).get("error") or info.error
            elif result is None:
                status = "failed"
                code = (protocol.read_exit(live.job_dir) or {}).get("code")
                why = f"exited with code {code}" if code is not None else "wrote no result.json"
                rec.error = f"task {why}: " + protocol.log_tail(live.job_dir)[-500:]
            else:
                raw = str(result.get("status"))
                status = raw if raw in TERMINAL_TASK_RUN else "failed"  # type: ignore[assignment]
                if n["failed"] and status == "completed":
                    status = "completed_with_errors"
                rec.error = result.get("error") or next(
                    (
                        v.get("message")
                        for v in outcomes.values()
                        if v["status"] == "failed" and v.get("message")
                    ),
                    None,
                )
                versions = result.get("versions")
                if isinstance(versions, dict):
                    rec.versions = {str(k): str(v) for k, v in versions.items()}
                provenance = result.get("provenance")
                if isinstance(provenance, dict):
                    rec.provenance = provenance
            rec.status = status
            if rec.task.id == DICOM_CONVERT:
                cleaned = attempt_cleaned(live.job_dir, rec.attempts)
                if result and result.get("conversion_time"):
                    rec.execution = {
                        **(rec.execution or {}),
                        "conversion_time": ConversionTimeEstimate.model_validate(
                            result["conversion_time"]
                        ).model_dump(),
                    }
                self.phase_runs.finish(live.pid, rec, live.job_dir, result or {})
                rec.execution = {
                    **(rec.execution or {}),
                    "attempt": rec.attempts,
                    "cleanup_verified": cleaned,
                }
                if not cleaned:
                    status = rec.status = "cleanup_pending"
            if control.pending(rec):
                if control.acknowledge(rec, live.job_dir):
                    status = rec.status
                    rec.error = rec.error if result is not None else None
                else:  # stopped without verified cleanup: allocation stays blocked
                    status = rec.status = "cleanup_pending"
            rec.started_at = rec.started_at or info.started_at
            rec.finished_at = utc_now()
            rec.outputs = [
                *rec.outputs,
                *(output for output in live.outputs if output not in rec.outputs),
            ]
            if live.registered:
                seg = self._target_seg(live)
                if not any(o.kind == "segmentation_set" and o.seg_id == seg for o in rec.outputs):
                    rec.outputs.append(TaskRunOutput(kind="segmentation_set", seg_id=seg))
            if rec.task.id == DICOM_CONVERT and rec.status == "completed" and result is not None:
                rec.execution = {**(rec.execution or {}), "registration_pending": True}
            self.runs.write(live.run_dir, rec)
            if live.manifest.resources.gpu == "required":
                self._record_gpu_ledger(live)
            elif live.outputs:
                append_jsonl(
                    self.workspace.project_dir(live.pid) / LEDGER,
                    [
                        {
                            "run_id": live.rid,
                            "task_id": rec.task.id,
                            "version": rec.task.version,
                            "settings_hash": rec.settings_hash,
                            "at": utc_now(),
                            "outputs": [{"ref": o.ref, "sha256": o.sha256} for o in live.outputs],
                        }
                    ],
                )
        if live.registered:
            await self._reindex_masks(live.pid)
        if result is not None and (
            status == "completed"
            or (status == "completed_with_errors" and live.manifest.id != DICOM_CONVERT)
        ):
            try:
                if live.manifest.id == DICOM_CONVERT:
                    await self._finalize_dicom(live, result)
                else:
                    await self._register_tabular(live, result)
            except Exception as exc:  # the run is done; a registration failure is recorded
                log.exception("task output registration failed", extra={"run_id": live.rid})
                await self._record_registration_error(live.pid, live.run_dir, exc)
        if live.manifest.runtime.type == "builtin" and live.manifest.id != DICOM_CONVERT:
            shutil.rmtree(live.job_dir, ignore_errors=True)  # disposable scratch
