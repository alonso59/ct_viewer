"""Task estimates (TSK-05, API-44): a sample run on up to 3 ready items, or a source dry run."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Final

from app.core.ids import new_ulid
from app.tasks import dry_run, protocol
from app.tasks.builtin import run_entry
from app.tasks.jobspec import JobSpecBase
from app.tasks.models import VOLUME_OUTPUTS, PreflightRequest, TaskEstimate, TaskManifest
from app.tasks.registry import RADIOMICS_TASK

SAMPLE_ITEMS: Final = 3


class EstimateBase(JobSpecBase):
    """Estimates: builtin sample, external manifest figures, source-task dry run (DCM-06)."""

    async def estimate(self, pid: str, task_id: str, req: PreflightRequest) -> TaskEstimate:
        info = self.registry.get(task_id)
        m = info.manifest
        if task_id == RADIOMICS_TASK:
            return await self._radiomics().estimate_task(pid, req)
        pre = await self.preflight(pid, task_id, req)
        n_units = pre.n_ready
        skipped = pre.n_selected - pre.n_ready
        if m.input == "source" and m.runtime.type == "builtin":
            return await self._dry_run(pid, m, req)
        if m.runtime.type == "external":
            spi = m.resources.seconds_per_item
            return TaskEstimate(
                n_units=n_units,
                n_skipped=skipped,
                seconds_per_item=spi,
                estimated_total_s=round(spi * n_units, 2) if spi is not None else None,
                basis="manifest" if spi is not None else "unknown",
            )
        settings, _ = self._settings(m, req.settings)
        sample_ids = pre.ready_item_ids[:SAMPLE_ITEMS]
        if not sample_ids:
            return TaskEstimate(
                n_units=0,
                n_skipped=skipped,
                seconds_per_item=None,
                estimated_total_s=None,
                basis="unknown",
            )
        idx = self.store.load(pid)
        seg_id = self._seg_id(self.workspace.get(pid), m, req.selection)
        sample = [idx.by_id[i] for i in sample_ids]
        job_dir = self.settings.workspace_root / ".scratch" / "estimates" / new_ulid()
        out_dir = job_dir / "out"
        spec = self._job_spec(
            pid,
            m,
            settings=settings,
            items=sample,
            seg_id=seg_id,
            output_dir=str(out_dir) if VOLUME_OUTPUTS & set(m.outputs) else None,
            source=None,
            scratch=job_dir,
        )
        protocol.write_job(
            job_dir,
            {
                **spec,
                "job_id": job_dir.name,
                "run_id": "estimate",
                "mode": "estimate",
                "resume": {"skip": []},
                "batch": {"size": m.resources.max_batch or len(sample)},
            },
        )
        t0 = time.monotonic()
        try:
            assert m.runtime.entry is not None
            await self.jobs.run_in_worker(run_entry, m.runtime.entry, str(job_dir))
            elapsed = time.monotonic() - t0
            result = protocol.read_result(job_dir) or {}
            errors = [
                f"{r.get('item_id')}: {r.get('message')}"
                for r in protocol.Tail(job_dir / protocol.PROGRESS).read()
                if r.get("t") == "item" and r.get("status") == "failed"
            ]
            size = (
                sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
                if out_dir.is_dir()
                else None
            )
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
        spi = elapsed / len(sample)
        if result.get("status") == "failed" and not errors:
            errors = [str(result.get("error") or "sample run failed")]
        return TaskEstimate(
            n_units=n_units,
            n_skipped=skipped,
            seconds_per_item=round(spi, 4),
            estimated_total_s=round(spi * n_units / max(1, self.jobs.workers), 2),
            output_bytes=int(size / len(sample) * n_units) if size else None,
            basis="sample",
            sample_item_ids=sample_ids,
            sample_errors=errors,
        )

    async def _dry_run(self, pid: str, m: TaskManifest, req: PreflightRequest) -> TaskEstimate:
        """A source task's estimate = its dry run (DCM-06): counts and storage, nothing written."""
        settings, _ = self._settings(m, req.settings)
        source = self._source(req.selection)
        await dry_run.require_dicom(m.id, Path(source))
        job_dir = self.settings.workspace_root / ".scratch" / "estimates" / new_ulid()
        spec = self._job_spec(
            pid, m, settings=settings, items=[], seg_id=None, output_dir=str(job_dir / "out"),
            source=source, scratch=job_dir,
        )  # fmt: skip
        protocol.write_job(
            job_dir, {**spec, "job_id": job_dir.name, "run_id": "estimate", "mode": "estimate"}
        )
        t0 = time.monotonic()
        try:
            assert m.runtime.entry is not None
            await self.jobs.run_in_worker(run_entry, m.runtime.entry, str(job_dir))
            result = protocol.read_result(job_dir) or {}
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
        return dry_run.estimate_of(result, time.monotonic() - t0, Path(source))
