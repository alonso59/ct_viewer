"""Driving a task attempt (TSK-06/07/11, BE-14): submit the job, tail `progress.jsonl`, record
item outcomes and logs, finish the run record.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from app.core.errors import JobConflict
from app.core.fsio import append_jsonl
from app.core.ids import new_ulid, utc_now
from app.ingest.models import Item
from app.ingest.segsets import record_masks
from app.jobs.types import JobHandle, JobInfo, JobSpec
from app.tasks import protocol, registry
from app.tasks.builtin import run_entry
from app.tasks.models import (
    TERMINAL_TASK_RUN,
    TaskManifest,
    TaskRunCounts,
    TaskRunOutput,
    TaskRunRecord,
    TaskRunStarted,
    TaskRunStatus,
)
from app.tasks.records import CANCEL_GRACE_S, ITEMS, LEDGER, LOGS, Live, item_outcomes
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
    ) -> TaskRunStarted:
        rid = run_dir.name
        rec = self.runs.read(run_dir)
        job_id = new_ulid()
        job_dir = self.job_dir(m, job_id)
        spec = self._job_spec(
            pid,
            m,
            settings=rec.settings,
            items=items,
            seg_id=seg_id,
            output_dir=rec.output_dir,
            source=rec.selection.source,
        )
        protocol.write_job(
            job_dir,
            {
                **spec,
                "job_id": job_id,
                "run_id": rid,
                "mode": "run",
                "resume": {"skip": list(skip)},
                "batch": {"size": m.resources.max_batch or max(1, len(items))},
            },
        )
        live = Live(pid, rid, run_dir, job_dir, m, rec.selection.seg_id)
        live.dataset_dir = Path(spec["dataset_dir"]) if "dataset_dir" in spec else None
        live.registered = any(
            s.producer is not None and s.producer.run_id == rid
            for s in self.workspace.get(pid).segmentations
        )
        n_todo = len([i for i in items if i.item_id not in set(skip)])

        async def driver(h: JobHandle) -> None:
            if m.runtime.type == "external":
                await self._drive_external(h, live, n_todo)
            else:
                await self._drive(h, live, n_todo)

        async def on_finish(info: JobInfo) -> str | None:
            await self._finish(live, info)
            return rid

        job_spec = JobSpec(
            project_id=pid,
            kind="task",
            units=[],
            driver=driver,
            on_finish=on_finish,
            ref=rid,
            job_id=job_id,
            key=m.id,
            meta={"run_id": rid, "task_id": m.id},
        )

        def prepare(rec: TaskRunRecord) -> None:
            rec.error, rec.finished_at = None, None
            rec.attempts += 1

        await self.runs.submit(
            pid,
            run_dir,
            job_spec,
            prepare=prepare,
            on_error=lambda: shutil.rmtree(job_dir, ignore_errors=True),
        )
        return TaskRunStarted(run_id=rid, job_id=job_id, status="queued")

    async def _set_status(self, live: Live, status: TaskRunStatus) -> None:
        await self.runs.set_status(live.pid, live.run_dir, status)

    async def _drive(self, h: JobHandle, live: Live, total: int) -> None:
        """Builtin: run the entry in a worker and tail its progress (TSK-07)."""
        h.set_total(total)
        live.set_total = h.set_total
        tail = protocol.Tail(live.job_dir / protocol.PROGRESS)
        entry = live.manifest.runtime.entry
        assert entry is not None
        await self._set_status(live, "running")
        fut = asyncio.ensure_future(h.run_in_worker(run_entry, entry, str(live.job_dir)))
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
                    elif stop_at is not None and time.monotonic() - stop_at > CANCEL_GRACE_S:
                        break
                await asyncio.sleep(POLL_S)
        finally:
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
        """External: the host runner claims `queue/{job_id}` (TSK-11, BE-14); we only tail it."""
        h.set_total(total)
        live.set_total = h.set_total
        tail = protocol.Tail(live.job_dir / protocol.PROGRESS)
        task_id = live.manifest.id
        claimed_by: str | None = None
        lost_since: float | None = None
        stop_at: float | None = None
        while True:
            await self._on_lines(live, tail.read())
            h.set_done(live.done)
            if (live.job_dir / protocol.RESULT).is_file() or (
                live.job_dir / protocol.EXIT
            ).is_file():
                break
            claim = protocol.read_claim(live.job_dir)
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
                if lost_since is not None and time.monotonic() - lost_since > RUNNER_LOST_S:
                    raise RuntimeError(f"runner {claimed_by} stopped sending heartbeats")
            if h.stopped:
                if not live.cancel_sent:
                    protocol.request_cancel(live.job_dir)
                    live.cancel_sent = True
                    stop_at = time.monotonic()
                if claimed_by is None:
                    break  # never claimed: the runner skips cancelled jobs
                if stop_at is not None and time.monotonic() - stop_at > CANCEL_GRACE_S + 10:
                    break
            await asyncio.sleep(POLL_S)
        await self._on_lines(live, tail.read())
        h.set_done(live.done)

    async def _on_lines(self, live: Live, lines: Sequence[dict[str, Any]]) -> None:
        if not lines:
            return
        item_rows: list[dict[str, Any]] = []
        logs: list[dict[str, Any]] = []
        masks: list[dict[str, Any]] = []
        for line in lines:
            t = line.get("t")
            if t == "total" and live.set_total is not None:
                live.set_total(int(line.get("n") or 0))
            elif t == "log":
                logs.append(
                    {
                        "at": utc_now(),
                        "level": line.get("level", "info"),
                        "message": str(line.get("message", ""))[:2000],
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
                }
                if status == "ok":
                    try:
                        masks += await self._item_outputs(live, iid, line.get("outputs") or [])
                    except ValueError as exc:
                        row = {"item_id": iid, "status": "failed", "message": f"output: {exc}"}
                live.done += 1
                item_rows.append(row)
        if masks and not live.registered:
            await self._register_set(live, masks)
        async with self.locks(live.pid):
            if item_rows:
                append_jsonl(live.run_dir / ITEMS, item_rows)
            if logs:
                append_jsonl(live.run_dir / LOGS, logs)
            if masks:
                record_masks(self.workspace.project_dir(live.pid), live.rid, masks)

    async def _finish(self, live: Live, info: JobInfo) -> None:
        result = protocol.read_result(live.job_dir)
        async with self.locks(live.pid):
            rec = self.runs.read(live.run_dir)
            outcomes = {
                k: v
                for k, v in item_outcomes(live.run_dir).items()
                if k in set(rec.item_ids) or v["status"] == "skipped"
            }
            n = Counter(v["status"] for v in outcomes.values())
            rec.counts = TaskRunCounts(
                items=len(rec.item_ids), ok=n["ok"], failed=n["failed"], skipped=n["skipped"]
            )
            status: TaskRunStatus
            if info.status == "cancelled":
                status = "cancelled"
            elif info.status == "interrupted":
                status = "interrupted"
            elif info.status == "failed":
                status, rec.error = "failed", info.error
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
                rec.error = result.get("error")
                versions = result.get("versions")
                if isinstance(versions, dict):
                    rec.versions = {str(k): str(v) for k, v in versions.items()}
            rec.status = status
            rec.started_at = rec.started_at or info.started_at
            rec.finished_at = utc_now()
            rec.outputs = [*rec.outputs, *live.outputs]
            if live.registered:
                seg = self._target_seg(live)
                if not any(o.kind == "segmentation_set" and o.seg_id == seg for o in rec.outputs):
                    rec.outputs.append(TaskRunOutput(kind="segmentation_set", seg_id=seg))
            self.runs.write(live.run_dir, rec)
            if live.outputs:
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
        if result is not None and status in ("completed", "completed_with_errors"):
            try:
                await self._register_tabular(live, result)
            except Exception as exc:  # the run is done; a registration failure is recorded
                log.exception("task output registration failed", extra={"run_id": live.rid})
                async with self.locks(live.pid):
                    rec = self.runs.read(live.run_dir)
                    rec.error = f"output registration: {type(exc).__name__}: {exc}"
                    self.runs.write(live.run_dir, rec)
        if live.manifest.runtime.type == "builtin":
            shutil.rmtree(live.job_dir, ignore_errors=True)  # disposable scratch (PRJ layout)
