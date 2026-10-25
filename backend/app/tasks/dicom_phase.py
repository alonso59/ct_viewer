"""Phase layers have their own task records and keep conversion outputs sealed."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import computed_field

from app.config import Settings
from app.core.errors import JobConflict
from app.core.fsio import atomic_write_json, iter_jsonl, read_json, write_jsonl_atomic
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.events.bus import EventBus
from app.imaging.fingerprint import full_sha256
from app.ingest.store import IndexStore
from app.jobs.manager import JobManager
from app.jobs.runs import RunStore
from app.jobs.types import TERMINAL, JobHandle, JobInfo, JobSpec
from app.projects.service import Workspace
from app.tasks import protocol
from app.tasks.dicom_execution import attempt_cleaned, run_dicom_job
from app.tasks.models import (
    RESUMABLE_TASK_RUN,
    TERMINAL_TASK_RUN,
    TaskRef,
    TaskRunCounts,
    TaskRunOutput,
    TaskRunProgress,
    TaskRunRecord,
    TaskRunStarted,
    TaskSelection,
)
from app.tasks.registry import Registry
from app.tasks.schema import settings_hash

if TYPE_CHECKING:
    from app.tasks.workspace_runs import WorkspaceRun

WORKSPACE = "_workspace_phase"


class _PhaseRunRecord(TaskRunRecord):
    """Retain the WorkspaceRun disk shape for rollback without duplicating state."""

    @computed_field
    def plugin(self) -> str:
        return "analyzers"

    @computed_field
    def source(self) -> str:
        return self.selection.source or ""

    @computed_field
    def dataset_dir(self) -> str:
        return self.output_dir or ""

    @computed_field
    def progress(self) -> dict[str, Any]:
        return TaskRunProgress.model_validate(
            (self.execution or {}).get("progress", {})
        ).model_dump(exclude_none=True, exclude={"eta_s"})

    @computed_field
    def cleanup_verified(self) -> bool:
        return bool((self.execution or {}).get("cleanup_verified"))


class PhaseRuns:
    def __init__(
        self,
        settings: Settings,
        registry: Registry,
        workspace: Workspace,
        index: IndexStore,
        jobs: JobManager,
        bus: EventBus,
        locks: ProjectLocks,
    ) -> None:
        self.settings, self.registry, self.workspace = settings, registry, workspace
        self.index, self.jobs, self.bus = index, jobs, bus
        self.runs = RunStore(
            _PhaseRunRecord,
            self._root,
            jobs,
            locks,
            terminal=TERMINAL_TASK_RUN,
            resumable=RESUMABLE_TASK_RUN,
            noun="Phase run",
        )

    def _root(self, scope: str) -> Path:
        if scope == WORKSPACE:
            return self.settings.workspace_root / "plugins/analyzers/runs"
        return self.workspace.project_dir(scope) / "tasks/runs"

    def recover(self, pid: str | None, rid: str) -> _PhaseRunRecord:
        directory = self.runs.run_dir(pid or WORKSPACE, rid)
        run = self.runs.read(directory)
        if run.status in TERMINAL_TASK_RUN or self.runs.job(run.job_id) is not None:
            return run
        prior = directory
        if (run.execution or {}).get("shared_conversion_job"):
            parent_id = run.provenance.get("source_conversion_run_id")
            if not isinstance(parent_id, str) or not is_ulid(parent_id):
                raise JobConflict("Phase source conversion is unavailable")
            prior = (
                self.workspace.project_dir(pid) / "tasks/runs"
                if pid
                else self.settings.workspace_root / "plugins/dicom/runs"
            ) / parent_id
        cleaned = bool(
            run.job_id and attempt_cleaned(prior / "attempts" / run.job_id, run.attempts)
        )
        run.status = "interrupted" if cleaned else "cleanup_pending"
        run.error = "Backend interrupted; retry phase only after verified cleanup"
        run.execution = {**(run.execution or {}), "cleanup_verified": cleaned}
        self.runs.write(directory, run)
        return run

    def dataset_phase(
        self, root: Path, meta: dict[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        """Import a local completed phase layer without changing the portable dataset snapshot."""
        rid, parent_id = meta.get("phase_run_id"), meta.get("run_id")
        if not isinstance(rid, str) or not is_ulid(rid):
            return None
        if not isinstance(parent_id, str) or not is_ulid(parent_id):
            return None
        parent_dir = self.settings.workspace_root / "plugins/dicom/runs" / parent_id
        if not (parent_dir / "run.json").is_file() or not self.runs.has(WORKSPACE, rid):
            return None
        parent = read_json(parent_dir / "run.json")
        if (
            parent.get("phase_run_id") != rid
            or Path(parent.get("dataset_dir", "")).resolve() != root.resolve()
        ):
            return None
        run = self.recover(None, rid)
        if run.status != "completed" or run.provenance.get("source_conversion_run_id") != parent_id:
            return None
        output = self._root(WORKSPACE) / rid / "annotations.jsonl"
        manifest = next((o for o in run.outputs if o.kind == "annotations"), None)
        if manifest is None or not output.is_file() or full_sha256(output) != manifest.sha256:
            raise JobConflict("Completed phase layer changed; review it before importing")
        return run.task.model_dump(mode="json"), list(iter_jsonl(output))

    def prepare(
        self,
        pid: str | None,
        parent: TaskRunRecord | WorkspaceRun,
    ) -> None:
        """Called by the API writer; project callers hold the existing project lock."""
        if not parent.phase_run_id:
            return
        directory = self._root(pid or WORKSPACE) / parent.phase_run_id
        previous = None
        if (directory / "run.json").exists():
            previous = self.runs.read(directory)
            if previous.provenance.get("source_conversion_run_id") != parent.run_id:
                raise JobConflict("Phase run belongs to another conversion")
            if previous.job_id == parent.job_id:
                return
            if previous.status == "completed" or not (previous.execution or {}).get(
                "shared_conversion_job"
            ):
                return
            if previous.attempts >= parent.attempts:
                raise JobConflict("Phase attempt changed; reload before preparing it")
        info = self.registry.get("analyzer.phase")
        manifest = info.manifest
        source = parent.selection.source if isinstance(parent, TaskRunRecord) else parent.source
        record = _PhaseRunRecord(
            run_id=parent.phase_run_id,
            task=TaskRef(
                id=manifest.id, version=manifest.version, manifest_hash=info.manifest_hash
            ),
            name=manifest.title,
            status="queued",
            created_at=previous.created_at if previous else utc_now(),
            job_id=parent.job_id,
            runtime="builtin",
            settings={},
            settings_hash=settings_hash(manifest.id, manifest.version, {}),
            selection=TaskSelection(source=source),
            manifest_snapshot=manifest,
            attempts=parent.attempts,
            provenance={"source_conversion_run_id": parent.run_id},
            execution={
                "phase_step": True,
                "shared_conversion_job": True,
                "cleanup_verified": False,
                "progress": TaskRunProgress(done=0, total=0).model_dump(),
            },
            output_dir=str(directory) if pid is None else None,
        )
        self.runs.write(directory, record)

    def stage(
        self,
        pid: str | None,
        parent: TaskRunRecord | WorkspaceRun,
        row: dict[str, Any],
    ) -> None:
        if not parent.phase_run_id or row.get("stage") != "analyzing":
            return
        self.prepare(pid, parent)
        directory = self.runs.run_dir(pid or WORKSPACE, parent.phase_run_id)
        run = self.runs.read(directory)
        if run.job_id != parent.job_id or run.status in TERMINAL_TASK_RUN:
            return
        done = int(row.get("stage_done", row.get("done")) or 0)
        total = int(row.get("stage_total", row.get("total")) or 0)
        if run.status != "cancelling":
            run.status = "running"
        run.started_at = run.started_at or utc_now()
        run.progress_done = done
        run.execution = {
            **(run.execution or {}),
            "progress": TaskRunProgress(
                done=done,
                total=total,
                stage="analyzing",
                stage_done=done,
                stage_total=total,
            ).model_dump(),
        }
        self.runs.write(directory, run)

    def finish(
        self,
        pid: str | None,
        parent: TaskRunRecord | WorkspaceRun,
        job: Path,
        result: dict[str, Any],
    ) -> None:
        if not parent.phase_run_id:
            return
        self.prepare(pid, parent)
        directory = self.runs.run_dir(pid or WORKSPACE, parent.phase_run_id)
        run = self.runs.read(directory)
        if run.job_id != job.name or run.attempts != parent.attempts:
            return
        self._complete(pid, directory, run, job, result)

    def _complete(
        self,
        pid: str | None,
        directory: Path,
        run: _PhaseRunRecord,
        job: Path,
        result: dict[str, Any],
    ) -> None:
        if not attempt_cleaned(job, run.attempts):
            run.status = "cleanup_pending"
            self.runs.write(directory, run)
            return
        analysis = (result.get("provenance") or {}).get("phase_analyzer")
        if not isinstance(analysis, dict):
            run.status, run.error = "cancelled", "Conversion ended before phase analysis"
        else:
            self._apply_analysis(pid, directory, run, job, result, analysis)
        run.finished_at = run.finished_at or utc_now()
        run.execution = {
            **(run.execution or {}),
            "cleanup_verified": True,
            "progress": TaskRunProgress(
                done=run.progress_done,
                total=run.counts.items,
                stage="analyzing",
                stage_done=run.progress_done,
                stage_total=run.counts.items,
            ).model_dump(),
        }
        self.runs.write(directory, run)

    def _apply_analysis(
        self,
        pid: str | None,
        directory: Path,
        run: _PhaseRunRecord,
        job: Path,
        result: dict[str, Any],
        analysis: dict[str, Any],
    ) -> None:
        if analysis.get("run_id") != run.run_id:
            raise JobConflict("Phase result belongs to another run")
        status = analysis.get("status")
        if status not in {"completed", "failed", "cancelled"}:
            raise JobConflict("Phase result status is invalid")
        run.status, run.error = status, analysis.get("error")
        total = int(analysis.get("total") or 0)
        run.progress_done = min(total, max(0, int(analysis.get("done", run.progress_done))))
        if status == "completed":
            self._publish_annotations(pid, directory, run, job, result)
            run.progress_done = total
        run.counts = TaskRunCounts(
            items=total,
            ok=run.progress_done,
            failed=max(0, total - run.progress_done) if status == "failed" else 0,
        )
        run.versions = {"rules": str(analysis.get("rules_version") or "")}
        if status == "completed" and pid and not (run.execution or {}).get("shared_conversion_job"):
            run.status = "reconciling"

    def _publish_annotations(
        self,
        pid: str | None,
        directory: Path,
        run: _PhaseRunRecord,
        job: Path,
        result: dict[str, Any],
    ) -> None:
        outputs = result.get("outputs_manifest") or []
        manifest: dict[str, Any] = next((o for o in outputs if o.get("kind") == "annotations"), {})
        path = (job / str(manifest.get("path", ""))).resolve()
        if not path.is_relative_to(job.resolve()) or not path.is_file():
            raise JobConflict("Phase annotation output is unavailable")
        if not manifest.get("sha256") or full_sha256(path) != manifest["sha256"]:
            raise JobConflict("Phase annotation output changed")
        annotations = [a for a in iter_jsonl(path) if a.get("field") == "phase"]
        target = directory / "annotations.jsonl"
        if not target.exists():
            write_jsonl_atomic(target, annotations)
        elif list(iter_jsonl(target)) != annotations:
            raise JobConflict("Published phase annotations changed")
        run.item_ids = sorted({str(a["item_id"]) for a in annotations})
        run.outputs = [
            TaskRunOutput(
                kind="annotations",
                ref=f"tasks/runs/{run.run_id}/annotations.jsonl" if pid else "annotations.jsonl",
                sha256=full_sha256(target),
                detail="phase",
            )
        ]

    async def resume(
        self,
        pid: str | None,
        rid: str,
        expected_attempt: int | None,
    ) -> TaskRunStarted:
        scope = pid or WORKSPACE
        async with self.runs.locks(f"_phase_control:{scope}:{rid}"):
            directory = self.runs.run_dir(scope, rid)
            run = self.runs.read(directory)
            if expected_attempt is None:
                raise JobConflict(
                    "Phase retry requires its expected attempt; reload before retrying"
                )
            receipt = f"phase:{rid}:{expected_attempt}"
            if run.resume_request_id == receipt:
                return TaskRunStarted(run_id=rid, job_id=run.job_id, status=run.status)
            if run.attempts != expected_attempt or run.status not in RESUMABLE_TASK_RUN:
                raise JobConflict("Phase attempt/status changed; reload before retrying")
            parent_id = run.provenance.get("source_conversion_run_id")
            if not isinstance(parent_id, str) or not is_ulid(parent_id):
                raise JobConflict("Phase source conversion is unavailable")
            parent_dir = (
                self.workspace.project_dir(pid) / "tasks/runs"
                if pid
                else self.settings.workspace_root / "plugins/dicom/runs"
            ) / parent_id
            parent = read_json(parent_dir / "run.json")
            if parent.get("phase_run_id") != rid or parent.get("status") != "completed":
                raise JobConflict("Finish recovering the source conversion before retrying phase")
            prior = parent_dir if (run.execution or {}).get("shared_conversion_job") else directory
            if not run.job_id or not attempt_cleaned(prior / "attempts" / run.job_id, run.attempts):
                raise JobConflict("Phase execution cleanup is unconfirmed; retry is blocked")
            state = parent_dir / "phase-analyzer"
            phase_provenance = parent.get("provenance", {}).get("phase_analyzer", {})
            seed = phase_provenance.get("inputs_seed")
            seed_path = (
                parent_dir / "attempts" / str(parent.get("job_id")) / "phase-inputs/seed.json"
            )
            has_seed = isinstance(seed, dict) and bool(seed.get("sha256")) and seed_path.is_file()
            if not (state / "inputs.json").is_file() and not has_seed:
                raise JobConflict(
                    "Pinned phase metadata is unavailable; recover its inputs before retrying"
                )
            job_id = new_ulid()
            job = directory / "attempts" / job_id
            protocol.write_job(
                job,
                {
                    "operation": "phase",
                    "attempt": run.attempts + 1,
                    "dicom_process_protocol": 1,
                    "job_id": job_id,
                    "run_id": rid,
                    "analysis_state": str(state),
                    "phase_total": run.counts.items,
                    "analysis_seed": {"path": str(seed_path), "sha256": seed["sha256"]}
                    if has_seed
                    else None,
                },
            )
            atomic_write_json(job / "reserved.json", {"attempt": run.attempts + 1})

            async def driver(handle: JobHandle) -> None:
                await self.runs.set_status(scope, directory, "running")
                handle.set_total(run.counts.items)

                def progress(row: dict[str, Any]) -> None:
                    if row.get("stage") == "analyzing":
                        handle.set_total(int(row.get("total") or 0))
                        handle.set_done(int(row.get("done") or 0))

                await run_dicom_job(
                    job,
                    workspace=self.settings.workspace_root,
                    settings=self.settings,
                    cancelled=lambda: handle.stopped,
                    on_progress=progress,
                )

            async def finish(info: JobInfo) -> str:
                async with self.runs.locks(scope):
                    current = self.runs.read(directory)
                    if current.job_id != job_id:
                        return rid
                    result = protocol.read_result(job)
                    if result is None:
                        result = {
                            "provenance": {
                                "phase_analyzer": {
                                    "run_id": rid,
                                    "status": "cancelled"
                                    if info.status == "cancelled"
                                    else "failed",
                                    "total": current.counts.items,
                                    "error": info.error
                                    or "Phase worker interrupted; retry analysis",
                                }
                            }
                        }
                    self._complete(pid, directory, current, job, result)
                if pid and self.runs.read(directory).status == "reconciling":
                    try:
                        from app.ingest.service import IngestService

                        cfg = self.workspace.get(pid)
                        if cfg.annotation_sources.get("phase") in (None, rid):
                            await self.workspace.set_annotation_source(
                                pid, "phase", rid, only_if_unset=True
                            )
                            ingest = IngestService(
                                self.workspace, self.index, self.jobs, self.bus, self.runs.locks
                            )
                            indexed = await ingest.reindex(pid)
                            if indexed is not None:
                                outcome = await self.jobs.wait(indexed, 300)
                                if outcome.status != "succeeded":
                                    raise JobConflict(
                                        "Phase layer index did not complete; retry analysis"
                                    )
                        async with self.runs.locks(scope):
                            current = self.runs.read(directory)
                            if current.job_id == job_id:
                                current.status = "completed"
                                self.runs.write(directory, current)
                    except Exception as exc:
                        async with self.runs.locks(scope):
                            current = self.runs.read(directory)
                            if current.job_id == job_id:
                                current.status, current.error = (
                                    "failed",
                                    f"{type(exc).__name__}: phase layer registration failed; "
                                    "retry analysis",
                                )
                                self.runs.write(directory, current)
                return rid

            def prepare(current: TaskRunRecord) -> None:
                if current.attempts != expected_attempt:
                    raise JobConflict("Phase attempt changed before retry")
                current.attempts += 1
                current.resume_request_id = receipt
                current.error, current.finished_at, current.progress_done = None, None, 0
                current.execution = {
                    "phase_step": True,
                    "shared_conversion_job": False,
                    "cleanup_verified": False,
                    "progress": TaskRunProgress(done=0, total=current.counts.items).model_dump(),
                }

            await self.runs.submit(
                scope,
                directory,
                JobSpec(
                    project_id=pid or "_workspace",
                    kind="task",
                    units=[],
                    ref=rid,
                    job_id=job_id,
                    key=f"analyzer.phase:{rid}",
                    driver=driver,
                    on_finish=finish,
                ),
                prepare=prepare,
            )
            return TaskRunStarted(run_id=rid, job_id=job_id, status="queued")

    async def cancel(
        self,
        pid: str | None,
        rid: str,
        expected_attempt: int | None,
    ) -> None:
        scope = pid or WORKSPACE
        async with self.runs.locks(f"_phase_control:{scope}:{rid}"):
            directory = self.runs.run_dir(scope, rid)
            async with self.runs.locks(scope):
                run = self.runs.read(directory)
                if expected_attempt is None or run.attempts != expected_attempt:
                    raise JobConflict("Phase cancellation requires the current expected attempt")
                if run.status in TERMINAL_TASK_RUN:
                    return
                shared = (run.execution or {}).get("shared_conversion_job") is True
                job = directory if shared else directory / "attempts" / str(run.job_id)
                protocol.request_cancel(job)
                run.status = "cancelling"
                self.runs.write(directory, run)
            if not shared and run.job_id:
                self.jobs.cancel(run.job_id)

    def workspace_view(self, raw: dict[str, Any]) -> WorkspaceRun:
        from app.tasks.workspace_runs import WorkspaceRun

        run = TaskRunRecord.model_validate(raw)
        progress = TaskRunProgress.model_validate(
            (run.execution or {}).get(
                "progress",
                {
                    "done": run.progress_done,
                    "total": run.counts.items,
                },
            )
        )
        if not (run.execution or {}).get("shared_conversion_job") and run.job_id:
            live = self.runs.job(run.job_id)
            if live is not None and live.status not in TERMINAL:
                progress = TaskRunProgress(
                    done=live.done,
                    total=live.total,
                    stage="analyzing",
                    stage_done=live.done,
                    stage_total=live.total,
                )
        return WorkspaceRun(
            run_id=run.run_id,
            task=run.task,
            plugin="analyzers",
            name=run.name,
            status=run.status,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            source=run.selection.source or "",
            dataset_dir=run.output_dir or "",
            settings=run.settings,
            settings_hash=run.settings_hash,
            counts=run.counts.model_dump(),
            progress=progress.model_dump(exclude_none=True, exclude={"eta_s"}),
            error=run.error,
            job_id=run.job_id,
            attempts=run.attempts,
            cleanup_verified=bool((run.execution or {}).get("cleanup_verified")),
            provenance=run.provenance,
        )
