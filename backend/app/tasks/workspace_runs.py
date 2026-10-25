"""`scope: workspace` tasks run without a project.

Inputs come from a source path inside ALLOWED_DATA_ROOTS; outputs go to a new, write-once folder
`{first ALLOWED_DERIVED_ROOTS}/_datasets/{name}/` (a `-1`, `-2` … suffix when the name is taken);
run records live in `WORKSPACE_ROOT/plugins/{plugin}/runs/{run_id}/run.json`. The dataset holds
`metadata.jsonl` (the converter artifact), `nifti/`, `sidecars/`, `annotations.jsonl`
(analyzer layers) and `dataset.json`; it opens in Open mode and imports like any root,
and an import registers its annotations as an analyzer run of the project.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, Field

from app.config import Settings
from app.core.errors import DerivedRootRequired, JobConflict, NotFound, ValidationProblem
from app.core.fsio import atomic_write_json, iter_jsonl, read_json, write_jsonl_atomic
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.core.paths import PathGuard
from app.jobs.manager import JobManager
from app.jobs.types import JobHandle, JobInfo, JobSpec
from app.tasks import dry_run, protocol
from app.tasks.builtin import run_entry
from app.tasks.dicom_execution import attempt_cleaned, run_dicom_job
from app.tasks.dicom_phase import PhaseRuns
from app.tasks.dicom_resources import require_pixel_budget
from app.tasks.jobspec import bind_inventory, inventory_spec
from app.tasks.models import (
    RESUMABLE_TASK_RUN,
    TERMINAL_TASK_RUN,
    ConversionTimeEstimate,
    TaskEstimate,
    TaskManifest,
    TaskRef,
    TaskResourceWait,
    TaskRunRecord,
    TaskRunStarted,
    TaskRunStatus,
    TaskSelection,
)
from app.tasks.records import dicom_history
from app.tasks.registry import Registry
from app.tasks.schema import normalize, settings_hash

WORKSPACE_JOBS: Final = "_workspace"  # JobManager project key of workspace task jobs
DATASETS: Final = "_datasets"
DATASET_JSON: Final = "dataset.json"
ANNOTATIONS: Final = "annotations.jsonl"
POLL_S: Final = 0.2
_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class WorkspaceRunRequest(BaseModel):
    task_id: str
    settings: dict[str, Any] = Field(default_factory=dict)
    selection: TaskSelection
    name: str | None = Field(default=None, max_length=120)


class WorkspaceEstimateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    selection: TaskSelection


class WorkspaceRun(BaseModel):
    """`plugins/{plugin}/runs/{run_id}/run.json` and its API payload."""

    run_id: str
    task: TaskRef
    plugin: str
    name: str
    status: TaskRunStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    source: str
    dataset_dir: str
    settings: dict[str, Any]
    settings_hash: str
    counts: dict[str, int] = Field(default_factory=dict)
    # {done, total} series, and while it scans {stage, stage_done, stage_total}
    progress: dict[str, int | str] = Field(default_factory=dict)
    error: str | None = None
    job_id: str | None = None
    attempts: int = 1
    resume_request_id: str | None = None
    cleanup_verified: bool = True
    provenance: dict[str, Any] = Field(default_factory=dict)
    phase_run_id: str | None = None
    resource_wait: TaskResourceWait | None = None
    conversion_time: ConversionTimeEstimate | None = None


def default_dataset_name() -> str:
    return f"dataset-{date.today().isoformat()}"


def dataset_name(raw: str) -> str:
    return _NAME_RE.sub("-", raw).strip("-.")[:80] or "dataset"


class WorkspaceTasks:
    def __init__(
        self, settings: Settings, registry: Registry, guard: PathGuard, jobs: JobManager,
        owners: dict[str, str], phase_runs: PhaseRuns, locks: ProjectLocks,
    ) -> None:  # fmt: skip
        self.settings = settings
        self.phase_runs = phase_runs
        self.registry = registry
        self.guard = guard
        self.jobs = jobs
        self.owners = owners
        self.locks = locks

    def _manifest(self, task_id: str) -> TaskManifest:
        info = self.registry.get(task_id)
        m = info.manifest
        if m.scope != "workspace":
            raise ValidationProblem(
                f"{m.id} needs a project (scope: project)",
                errors=[{"loc": ["body", "task_id"], "msg": "not a workspace task"}],
            )
        if not info.available or m.runtime.type != "builtin" or m.input != "source":
            raise ValidationProblem(f"{m.id} cannot run as a workspace task")
        return m

    def _settings(self, m: TaskManifest, raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
        norm, issues = normalize(m.settings_schema, m.defaults, raw)
        errors = [
            {"loc": ["body", "settings", *i.loc], "msg": i.msg, "type": i.rule}
            for i in issues
            if i.severity == "error"
        ]
        if errors:
            raise ValidationProblem(f"Invalid settings for {m.id}", errors=errors)
        return norm, settings_hash(m.id, m.version, norm)

    def _source(self, sel: TaskSelection) -> Path:
        if not sel.source:
            raise ValidationProblem(
                "Choose a source folder or file",
                errors=[{"loc": ["body", "selection", "source"], "msg": "required"}],
            )
        path = self.guard.check(Path(sel.source))
        if not path.exists():
            raise ValidationProblem(
                f"{sel.source} does not exist",
                errors=[{"loc": ["body", "selection", "source"], "msg": "missing"}],
            )
        return path

    def _derived(self) -> Path:
        roots = self.settings.derived_roots
        if not roots:
            raise DerivedRootRequired(
                "ALLOWED_DERIVED_ROOTS is empty: the server has no writable folder for datasets",
                actions=["configure:ALLOWED_DERIVED_ROOTS"],
            )
        return roots[0]

    def _runs_dir(self, plugin: str) -> Path:
        return self.settings.workspace_root / "plugins" / plugin / "runs"

    def _plugin(self, m: TaskManifest) -> str:
        return self.owners.get(m.id, m.id.split(".")[0])

    def _read(self, run_dir: Path) -> WorkspaceRun:
        raw = read_json(run_dir / "run.json")
        if (raw.get("execution") or {}).get("phase_step"):
            recovered = self.phase_runs.recover(None, run_dir.name)
            return self.phase_runs.workspace_view(recovered.model_dump(mode="json"))
        return WorkspaceRun.model_validate(raw)

    def _write(self, run_dir: Path, run: WorkspaceRun) -> None:
        atomic_write_json(run_dir / "run.json", run.model_dump(mode="json"))

    def _find(self, rid: str) -> Path:
        if is_ulid(rid):
            for d in (self.settings.workspace_root / "plugins").glob(f"*/runs/{rid}"):
                if (d / "run.json").is_file():
                    return d
        raise NotFound(f"Workspace task run {rid!r} not found")

    def _spec(
        self, m: TaskManifest, settings: dict[str, Any], source: Path, out: Path
    ) -> dict[str, Any]:
        return {
            "task": {"id": m.id, "version": m.version},
            "settings": settings,
            "context": {
                "phase_vocabulary": [],  # no project: open vocabulary
                "packs": [],
                "target_profile": settings.get("target_profile") or "generic",
            },
            "items": [],
            "rows": [],
            "output_dir": str(out),
            "dataset_dir": str(out),
            "dataset_ref": "DATA:",
            "workspace": True,  # rows relative to the dataset root
            "source": {"path": str(source)},
            "project_id": "",
            "timing_destination": str(self.settings.derived_roots[0])
            if self.settings.derived_roots
            else None,
            **({"dicom_process_protocol": 1} if m.id == "dicom.convert" else {}),
        }

    def source_estimate_spec(
        self,
        task_id: str,
        source: str,
        settings: dict[str, Any],
        scratch: Path,
    ) -> dict[str, Any]:
        manifest = self._manifest(task_id)
        normalized, _ = self._settings(manifest, settings)
        return self._spec(manifest, normalized, Path(source), scratch / "out")

    async def estimate(
        self, task_id: str, req: WorkspaceEstimateRequest, progress_id: str | None = None
    ) -> TaskEstimate:
        """The dry run without a project: counts and storage, nothing written."""
        m = self._manifest(task_id)
        settings, _ = self._settings(m, req.settings)
        source = self._source(req.selection)
        job_dir = dry_run.job_dir(self.settings.workspace_root, progress_id)
        t0 = time.monotonic()
        try:
            await dry_run.require_dicom(m.id, source)
            spec = self._spec(m, settings, source, job_dir / "out")
            protocol.write_job(
                job_dir, {**spec, "job_id": job_dir.name, "run_id": "estimate", "mode": "estimate"}
            )
            assert m.runtime.entry is not None
            if m.id == "dicom.convert":
                await run_dicom_job(
                    job_dir, workspace=self.settings.workspace_root, settings=self.settings
                )
            else:
                await self.jobs.run_in_worker(run_entry, m.runtime.entry, str(job_dir))
            result = protocol.read_result(job_dir) or {}
        finally:
            if (
                not (job_dir / "resources.json").exists()
                or (job_dir / "allocation-exit.json").exists()
            ):
                shutil.rmtree(job_dir, ignore_errors=True)
        return dry_run.estimate_of(result, time.monotonic() - t0, source)

    async def start(
        self,
        req: WorkspaceRunRequest,
        *,
        run_id: str | None = None,
        source_inventory: dict[str, Any] | None = None,
    ) -> TaskRunStarted:
        m = self._manifest(req.task_id)
        settings, shash = self._settings(m, req.settings)
        if run_id is not None:
            if not is_ulid(run_id) or m.id != "dicom.convert":
                raise JobConflict("Reserved run identity is invalid")
            reserved = self._runs_dir(self._plugin(m)) / run_id
            if (reserved / "run.json").exists():
                prior = self.get(run_id)
                if (
                    prior.task.id != m.id
                    or prior.settings_hash != shash
                    or prior.source != req.selection.source
                ):
                    raise JobConflict("Reserved conversion request changed")
                bind_inventory(reserved, self.settings.workspace_root, source_inventory)
                return TaskRunStarted(run_id=run_id, job_id=prior.job_id, status=prior.status)
            if reserved.exists() and any(reserved.iterdir()):
                raise JobConflict(
                    "Reserved conversion record is missing; review retained attempt evidence"
                )
        source = self._source(req.selection)
        if source_inventory is None:
            await dry_run.require_dicom(m.id, source)
        if self.jobs.active(WORKSPACE_JOBS, "task", m.id) is not None:
            raise JobConflict(f"A {m.id} workspace run is already active")
        base = self._derived() / DATASETS
        if m.id == "dicom.convert":
            require_pixel_budget(self.settings)
        # never the source folder's name: DICOM folders are often patient names
        stem = dataset_name(req.name or default_dataset_name())
        out, n = base / stem, 0
        while out.exists():  # write-once: never reuse a dataset folder
            n += 1
            out = base / f"{stem}-{n}"
        info = self.registry.get(m.id)
        plugin = self._plugin(m)
        rid, job_id = run_id or new_ulid(), new_ulid()
        run_dir = self._runs_dir(plugin) / rid
        run_dir.mkdir(parents=True)
        run = WorkspaceRun(
            run_id=rid,
            task=TaskRef(id=m.id, version=m.version, manifest_hash=info.manifest_hash),
            plugin=plugin,
            name=out.name,
            status="queued",
            created_at=utc_now(),
            source=str(source),
            dataset_dir=str(out),
            settings=settings,
            settings_hash=shash,
            job_id=job_id,
            phase_run_id=new_ulid()
            if m.id == "dicom.convert" and settings.get("phase_analyzer", True)
            else None,
        )
        job_dir = (
            run_dir / "attempts" / job_id
            if m.id == "dicom.convert"
            else self.settings.workspace_root / ".scratch" / "jobs" / job_id
        )
        if m.id == "dicom.convert":
            atomic_write_json(job_dir / "reserved.json", {"attempt": 1})
        self._write(run_dir, run)
        self.phase_runs.prepare(None, run)
        bind_inventory(run_dir, self.settings.workspace_root, source_inventory)
        out.mkdir(parents=True)
        protocol.write_job(
            job_dir,
            {
                **self._spec(m, settings, source, out),
                **inventory_spec(run_dir, self.settings.workspace_root),
                "job_id": job_id,
                "run_id": rid,
                "mode": "run",
                "resume": {"skip": []},
                "batch": {"size": 1},
                "analysis_state": str(run_dir / "phase-analyzer"),
                "phase_run_id": run.phase_run_id,
                "phase_cancel": str(
                    self.settings.workspace_root
                    / "plugins/analyzers/runs"
                    / run.phase_run_id
                    / protocol.CANCEL
                )
                if run.phase_run_id
                else None,
            },
        )

        async def driver(h: JobHandle) -> None:
            await self._drive(h, m, run_dir, job_dir)

        async def on_finish(info: JobInfo) -> str | None:
            self._finish(run_dir, job_dir, info)
            return rid

        self.jobs.submit(
            JobSpec(
                project_id=WORKSPACE_JOBS, kind="task", units=[], driver=driver,
                on_finish=on_finish, ref=rid, job_id=job_id, key=m.id,
            )
        )  # fmt: skip
        return TaskRunStarted(run_id=rid, job_id=job_id, status="queued")

    async def _drive(self, h: JobHandle, m: TaskManifest, run_dir: Path, job_dir: Path) -> None:
        run = self._read(run_dir)
        run.status, run.started_at = "running", utc_now()
        if m.id == "dicom.convert":
            run.cleanup_verified = False
        self._write(run_dir, run)
        tail = protocol.Tail(job_dir / protocol.PROGRESS)
        assert m.runtime.entry is not None
        fut = asyncio.ensure_future(
            run_dicom_job(
                job_dir,
                workspace=self.settings.workspace_root,
                settings=self.settings,
                cancelled=lambda: h.stopped,
            )
            if m.id == "dicom.convert"
            else h.run_in_worker(run_entry, m.runtime.entry, str(job_dir))
        )
        done = total = 0
        stage: dict[str, int | str] = {}
        resource_wait: TaskResourceWait | None = None
        cancel_sent = False
        try:
            while True:
                for line in tail.read():
                    if line.get("t") == "total":
                        total = int(line.get("n") or 0)
                        h.set_total(total)
                    elif line.get("t") == "item":
                        if m.id != "dicom.convert" or line.get("status") == "ok":
                            done += 1
                        h.set_done(done)
                    elif line.get("t") == "conversion_time":
                        run = self._read(run_dir)
                        run.conversion_time = ConversionTimeEstimate.model_validate(
                            line["estimate"]
                        )
                        self._write(run_dir, run)
                    elif line.get("t") == "stage":
                        if isinstance(line.get("resource_wait"), dict):
                            resource_wait = TaskResourceWait.model_validate(line["resource_wait"])
                        elif line.get("stage") == "admitted":
                            resource_wait = None
                        stage = {
                            "stage": str(line.get("stage") or ""),
                            "stage_done": int(line.get("done") or 0),
                            "stage_total": int(line.get("total") or 0),
                        }
                run = self._read(run_dir)
                self.phase_runs.stage(None, run, stage)
                run.progress = {"done": done, "total": total, **stage}
                if stage.get("stage") == "waiting_for_resources":
                    run.status = "waiting_for_resources"
                    pending = (protocol.read_result(job_dir) or {}).get("resource_wait", {})
                    run.resource_wait = resource_wait
                    run.error = (
                        "Waiting for DICOM_MEMORY_MB; increase the budget and resume"
                        if pending
                        else "Waiting for a verified shared host allocation"
                    )
                elif stage.get("stage") == "admitted":
                    run.status, run.error = "running", None
                    run.resource_wait = None
                self._write(run_dir, run)
                if fut.done():
                    break
                if h.stopped and not cancel_sent:
                    protocol.request_cancel(job_dir)
                    cancel_sent = True
                await asyncio.sleep(POLL_S)
        finally:
            if m.id == "dicom.convert" and not fut.done():
                fut.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await fut
        res = fut.result() or {}
        if int(res.get("exit_code", 1)) != 0 and protocol.read_result(job_dir) is None:
            raise RuntimeError(protocol.log_tail(job_dir)[-500:] or "task failed")

    def _finish(self, run_dir: Path, job_dir: Path, info: JobInfo) -> None:
        run = self._read(run_dir)
        if run.task.id == "dicom.convert" and run.job_id != job_dir.name:
            return
        result = protocol.read_result(job_dir) or {}
        if result.get("conversion_time"):
            run.conversion_time = ConversionTimeEstimate.model_validate(result["conversion_time"])
        status: TaskRunStatus
        if info.status == "cancelled":
            status = "cancelled"
        elif info.status == "interrupted":
            status = "interrupted"
        elif info.status == "failed" or result.get("status") == "failed":
            status = "failed"
        elif result.get("status") in {"cancelled", "completed_with_errors", "interrupted"}:
            status = result["status"]
        else:
            status = "completed"
        if run.task.id == "dicom.convert":
            run.cleanup_verified = attempt_cleaned(job_dir, run.attempts)
            self.phase_runs.finish(None, run, job_dir, result)
            if not run.cleanup_verified:
                status = "cleanup_pending"
        counts = result.get("estimate") if isinstance(result.get("estimate"), dict) else {}
        if run.task.id == "dicom.convert" and not counts:
            self._recover_counts(run_dir, run)
        else:
            run.counts = {k: int(v) for k, v in (counts or {}).items() if isinstance(v, int)}
        run.error = info.error or (str(result["error"]) if result.get("error") else None)
        run.provenance = result.get("provenance") or {}
        if status == "completed" and not run.counts.get("series"):
            status, run.error = "failed", run.error or "No DICOM series found in the source"
        run.status, run.finished_at = status, utc_now()
        self._write(run_dir, run)
        if run.task.id != "dicom.convert":
            shutil.rmtree(job_dir, ignore_errors=True)

    def _recover_counts(self, run_dir: Path, run: WorkspaceRun) -> None:
        outcomes, total = dicom_history(run_dir, run.attempts)
        n = Counter(event["status"] for event in outcomes.values())
        run.counts = {
            **run.counts,
            "selected": total,
            "already_converted": n["ok"],
            "failed": n["failed"],
            "skipped": n["skipped"],
            "converted": 0,
            "pending": max(0, total - n["ok"] - n["failed"]),
        }

    def list(self) -> list[WorkspaceRun]:
        out = [self.get(d.parent.name) for d in (self.settings.workspace_root / "plugins").glob(
            "*/runs/*/run.json")]  # fmt: skip
        return sorted(out, key=lambda r: r.created_at, reverse=True)

    def get(self, rid: str) -> WorkspaceRun:
        run_dir = self._find(rid)
        run = self._read(run_dir)
        if run.task.id == "dicom.convert" and run.status not in TERMINAL_TASK_RUN:
            try:
                self.jobs.get(str(run.job_id))
            except NotFound:
                job = run_dir / "attempts" / str(run.job_id)
                run.cleanup_verified = attempt_cleaned(job, run.attempts)
                run.status = "interrupted" if run.cleanup_verified else "cleanup_pending"
                run.error = "Backend interrupted; resume after verified cleanup"
                self._recover_counts(run_dir, run)
                self._write(run_dir, run)
        return run

    async def resume(
        self,
        rid: str,
        *,
        expected_attempt: int | None = None,
        request_id: str | None = None,
        failed_only: bool = False,
    ) -> TaskRunStarted:
        run = self.get(rid)
        if run.task.id == "analyzer.phase" and run.provenance.get("source_conversion_run_id"):
            if failed_only:
                raise JobConflict("Retry failed is supported only for DICOM conversion")
            return await self.phase_runs.resume(None, rid, expected_attempt)
        async with self.locks(f"_dicom_control:{WORKSPACE_JOBS}:{rid}"):
            return await self._resume(rid, expected_attempt, request_id, failed_only)

    async def _resume(
        self, rid: str, expected_attempt: int | None, request_id: str | None, failed_only: bool
    ) -> TaskRunStarted:
        run = self.get(rid)
        if failed_only:
            if expected_attempt is None:
                raise JobConflict("Retry failed requires the conversion's current attempt")
            request_id = request_id or f"retry-failed:{rid}:{expected_attempt}"
            if run.attempts == expected_attempt + 1 and run.resume_request_id == request_id:
                return TaskRunStarted(run_id=rid, job_id=run.job_id, status=run.status)
        if expected_attempt is not None and run.attempts != expected_attempt:
            raise JobConflict("Conversion run attempt changed; reload before controlling it")
        run_dir = self._find(rid)
        if run.task.id != "dicom.convert":
            raise JobConflict("This workspace task does not support durable resume")
        require_pixel_budget(self.settings)
        if run.status not in RESUMABLE_TASK_RUN or not run.cleanup_verified:
            raise JobConflict("Only unfinished, cleanup-verified conversion runs may resume")
        if not run.job_id or not attempt_cleaned(run_dir / "attempts" / run.job_id, run.attempts):
            raise JobConflict("Prior DICOM execution cleanup is unconfirmed; resume is blocked")
        if (Path(run.dataset_dir) / DATASET_JSON).exists():
            raise JobConflict("Completed datasets are sealed; start a new conversion")
        if self.jobs.active(WORKSPACE_JOBS, "task", run.task.id) is not None:
            raise JobConflict("A DICOM workspace attempt is already active")
        manifest = self._manifest(run.task.id)
        if manifest.version != run.task.version:
            raise JobConflict("The reader version changed; start a new conversion")
        source = self._source(TaskSelection(source=run.source))
        retry_item_ids = None
        if failed_only:
            outcomes, _ = await asyncio.to_thread(dicom_history, run_dir, run.attempts)
            retry_item_ids = [
                iid for iid, outcome in outcomes.items() if outcome["status"] == "failed"
            ]
            if not retry_item_ids:
                raise JobConflict(
                    "No recorded failed series remain; Resume pending for unattempted series"
                )
        job_id = new_ulid()
        job = run_dir / "attempts" / job_id
        atomic_write_json(job / "reserved.json", {"attempt": run.attempts + 1})
        run.attempts += 1
        run.resume_request_id = request_id
        run.progress, run.resource_wait = {}, None
        run.conversion_time = None
        run.job_id, run.status, run.error, run.finished_at = job_id, "queued", None, None
        self._write(run_dir, run)
        self.phase_runs.prepare(None, run)
        protocol.write_job(
            job,
            {
                **self._spec(manifest, run.settings, source, Path(run.dataset_dir)),
                **inventory_spec(run_dir, self.settings.workspace_root),
                "job_id": job_id,
                "run_id": rid,
                "mode": "run",
                "attempt": run.attempts,
                **({"retry_item_ids": retry_item_ids} if retry_item_ids is not None else {}),
                "analysis_state": str(run_dir / "phase-analyzer"),
                "phase_run_id": run.phase_run_id,
                "phase_cancel": str(
                    self.settings.workspace_root
                    / "plugins/analyzers/runs"
                    / run.phase_run_id
                    / protocol.CANCEL
                )
                if run.phase_run_id
                else None,
            },
        )

        async def finish(info: JobInfo) -> str:
            self._finish(run_dir, job, info)
            return rid

        self.jobs.submit(
            JobSpec(
                project_id=WORKSPACE_JOBS,
                kind="task",
                units=[],
                ref=rid,
                job_id=job_id,
                key=run.task.id,
                driver=lambda handle: self._drive(handle, manifest, run_dir, job),
                on_finish=finish,
            )
        )
        return TaskRunStarted(run_id=rid, job_id=job_id, status="queued")

    async def cancel(self, rid: str, *, expected_attempt: int | None = None) -> WorkspaceRun:
        run = self.get(rid)
        if run.task.id == "analyzer.phase" and run.provenance.get("source_conversion_run_id"):
            await self.phase_runs.cancel(None, rid, expected_attempt)
            return self.get(rid)
        async with self.locks(f"_dicom_control:{WORKSPACE_JOBS}:{rid}"):
            return self._cancel(rid, expected_attempt)

    def _cancel(self, rid: str, expected_attempt: int | None) -> WorkspaceRun:
        run = self.get(rid)
        if expected_attempt is not None and run.attempts != expected_attempt:
            raise JobConflict("Conversion run attempt changed; reload before controlling it")
        if run.job_id and run.status in ("queued", "running", "waiting_for_resources"):
            if run.task.id == "dicom.convert":
                protocol.request_cancel(self._find(rid) / "attempts" / run.job_id)
                run.status = "cancelling"
                self._write(self._find(rid), run)
            self.jobs.cancel(run.job_id)
        return self.get(rid)


def dataset_annotations(
    root: Path, phase_runs: PhaseRuns
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """A workspace dataset's manifest and analyzer annotations, if `root` is one."""
    if not (root / DATASET_JSON).is_file():
        return None
    try:
        meta = read_json(root / DATASET_JSON)
    except (OSError, ValueError):
        return None
    rows = [r for r in iter_jsonl(root / ANNOTATIONS) if r.get("item_id") and r.get("field")]
    phase = phase_runs.dataset_phase(root, meta)
    if phase is not None:
        phase_task, phase_rows = phase
        meta = {**meta, "phase_task": phase_task}
        rows = [r for r in rows if r["field"] != "phase"] + phase_rows
    return meta, rows


def write_imported_run(run_dir: Path, meta: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """The dataset's annotations as a completed task run of the project."""
    task = meta.get("task") or {}
    now = utc_now()
    rec = TaskRunRecord(
        run_id=run_dir.name,
        task=TaskRef(id=str(task.get("id") or "dicom.convert"),
                     version=str(task.get("version") or ""), manifest_hash=""),
        name=f"Dataset {meta.get('name', '')}".strip(),
        status="completed",
        created_at=now,
        finished_at=now,
        runtime="builtin",
        settings=meta.get("settings") or {},
        settings_hash="",
        selection=TaskSelection(source=str(meta.get("source") or "")),
    )  # fmt: skip
    run_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl_atomic(run_dir / ANNOTATIONS, rows)
    atomic_write_json(run_dir / "run.json", rec.model_dump(mode="json"))
