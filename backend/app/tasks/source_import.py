"""Shared import orchestration for durable and legacy entry points (SRC-19)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.errors import JobConflict, NotFound, ValidationProblem
from app.core.fsio import atomic_write_json, read_json, read_jsonl
from app.core.ids import new_ulid
from app.ingest.schemas import CommitResult, ImportPreview
from app.ingest.service import SOURCES
from app.jobs.types import JobHandle, JobInfo, JobSpec
from app.tasks import workspace_runs
from app.tasks.dicom_phase import PhaseRuns
from app.tasks.source_models import (
    SourceImportContext,
    SourceImportUpdate,
    SourceOperation,
    SourceOperationControl,
)

if TYPE_CHECKING:
    from app.ingest.service import IngestService
    from app.tasks.source_operations import SourceOperations

ACTIVE = {"queued", "running", "cancelling"}


async def commit_with_annotations(
    ingest: IngestService,
    project_id: str,
    preview_id: str,
    phase_runs: PhaseRuns,
    *,
    import_id: str | None = None,
    allow_incomplete: bool = False,
) -> CommitResult:
    pv = ingest.preview_of(project_id, preview_id)
    incomplete = workspace_runs.incomplete_dataset(Path(pv.root)) if pv.root else None
    if incomplete is not None and not allow_incomplete:
        raise JobConflict(
            f"This dataset is incomplete: {incomplete['converted']} series converted, "
            f"{incomplete['failed']} failed, {incomplete['pending']} pending. Acknowledge to "
            "import the converted series; the others stay excluded with their reasons",
            actions=["acknowledge:incomplete_dataset"],
        )
    import_id = import_id or new_ulid()
    found = None
    if pv.root:
        found = workspace_runs.dataset_annotations(
            Path(pv.root), phase_runs, allow_incomplete=allow_incomplete
        )
    if found is not None and found[1]:
        meta, rows = found
        layers = [(meta, rows)]
        if meta.get("phase_task"):
            layers = [
                (meta, [r for r in rows if r["field"] != "phase"]),
                (
                    {**meta, "task": meta["phase_task"]},
                    [r for r in rows if r["field"] == "phase"],
                ),
            ]
        marker = ingest.workspace.project_dir(project_id) / SOURCES / import_id / "annotations.json"
        signature = hashlib.sha256(json.dumps(layers, sort_keys=True).encode()).hexdigest()
        async with ingest.locks(project_id):
            saved = read_json(marker) if marker.exists() else None
            ids = saved["runs"] if saved is not None else [new_ulid() for _ in layers]
            if len(ids) != len(layers) or (
                saved is not None and saved.get("signature") != signature
            ):
                raise JobConflict("The imported annotation layers changed; prepare a new import")
            atomic_write_json(marker, {"version": 1, "signature": signature, "runs": ids})
        for rid, (layer_meta, layer_rows) in zip(ids, layers, strict=True):
            if not layer_rows:
                continue
            async with ingest.locks(project_id):
                run_dir = ingest.workspace.project_dir(project_id) / "tasks" / "runs" / rid
                if not (run_dir / "run.json").is_file():
                    workspace_runs.write_imported_run(run_dir, layer_meta, layer_rows)
                elif (
                    not (run_dir / workspace_runs.ANNOTATIONS).is_file()
                    or read_jsonl(run_dir / workspace_runs.ANNOTATIONS) != layer_rows
                ):
                    raise JobConflict(
                        "An imported annotation snapshot changed; restore it before resuming"
                    )
            for field in sorted({str(r["field"]) for r in layer_rows}):
                await ingest.workspace.set_annotation_source(
                    project_id, field, rid, only_if_unset=True
                )
    return await ingest.commit(project_id, preview_id, import_id=import_id)


async def import_view(operations: SourceOperations, record: SourceOperation) -> SourceOperation:
    context = record.import_context
    assert context is not None and record.project_id is not None
    if context.preview_id:
        try:
            record.import_preview = await asyncio.to_thread(
                operations.ingest.preview_of, record.project_id, context.preview_id
            )
        except NotFound:
            if context.import_id is None:
                context.step = "detect"
                record.error = "The import preview expired; prepare it again with the saved options"
                return record
    if context.step == "preview":
        return record
    record.stage = "import_preview" if context.step == "previewing" else "import_index"
    record.progress_stage = record.stage
    job = None
    if context.job_id:
        with suppress(NotFound):
            job = operations.jobs.get(context.job_id)
    record.import_job = job
    if job is not None:
        record.progress = {"done": job.done, "total": job.total}
        record.error = job.error
        record.status = {"succeeded": "completed", "waiting_for_runner": "queued"}.get(
            job.status, job.status
        )  # type: ignore[assignment]
        record.cleanup_verified = False
        if job.status in {"succeeded", "failed", "cancelled", "interrupted"}:
            try:
                await operations.jobs.wait(job.job_id, timeout=0.001)
                current = operations.get(record.operation_id)
                if current.revision != record.revision:
                    return await import_view(operations, current)
                record.cleanup_verified = True
            except TimeoutError:
                record.status = "cancelling"
        return record
    status = await operations.ingest.index_status(record.project_id)
    if context.step == "index" and context.import_id and status.import_id == context.import_id:
        record.status = {
            "ready": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(status.state, "interrupted")  # type: ignore[assignment]
        record.error = status.error
        record.progress = {"done": status.n_items, "total": status.n_items}
    else:
        record.status = "cancelled" if record.control.get("action") == "cancel" else "interrupted"
        record.error = "Import work stopped; resume with the saved options and destination"
    record.cleanup_verified = True
    return record


async def save_import(
    operations: SourceOperations, operation: str, request: SourceImportUpdate
) -> SourceOperation:
    async with operations.locks(f"_source_operation:{operation}"):
        record = operations.get(operation)
        if not operations._check_control(record, request, "import_draft"):
            return await operations.view(operation)
        context = record.import_context
        if record.purpose != "discover" or context is None or record.stage != "discovered":
            raise JobConflict("Finish import source discovery before editing its draft")
        if record.project_id not in (None, request.project_id):
            raise JobConflict("Import belongs to a different project")
        operations.workspace.get(request.project_id)
        if context.step in {"previewing", "index"}:
            current = await import_view(operations, record.model_copy(deep=True))
            if current.status in ACTIVE or not current.cleanup_verified:
                raise JobConflict("Wait for import work to stop before editing its options")
        choices = request.model_dump(
            exclude={
                "expected_revision",
                "expected_attempt",
                "expected_run_attempt",
                "project_id",
            }
        )
        before = context.model_dump(include=set(choices))
        if choices != before:
            if context.import_id is not None:
                raise JobConflict("Start a separate import to change an already committed import")
            record.import_context = SourceImportContext(**choices)
        record.project_id = request.project_id
        record.control = {"action": "import_draft", **request.model_dump()}
        operations._write(record)
        return await operations.view(operation)


def submit_import(
    operations: SourceOperations, record: SourceOperation, *, commit: bool
) -> SourceOperation:
    context = record.import_context
    assert context is not None and record.project_id is not None
    if context.adapter not in {"metadata-v1", "nifti-files"}:
        raise ValidationProblem("Choose an import adapter before preparing a preview")
    if commit and context.preview_id is None:
        raise JobConflict("Prepare an import preview before committing")
    context.step = "index" if commit else "previewing"
    if commit:
        context.import_id = context.import_id or new_ulid()
    else:
        context.preview_id = None
    context.job_id = new_ulid()
    record.attempt += 1
    record.error = None
    operations._write(record)  # intent and identities survive a crash before dispatch
    attempt, jid, pid = record.attempt, context.job_id, record.project_id
    allow_incomplete = bool((record.control or {}).get("allow_incomplete"))
    prepared: ImportPreview | None = None
    index_job: str | None = None

    async def drive(handle: JobHandle) -> None:
        nonlocal prepared, index_job
        if handle.stopped:
            return
        handle.set_total(1)
        if commit:
            assert context.preview_id is not None and context.import_id is not None
            result = await commit_with_annotations(
                operations.ingest,
                pid,
                context.preview_id,
                operations.tasks.phase_runs,
                import_id=context.import_id,
                allow_incomplete=allow_incomplete,
            )
            index_job = result.job_id
            if handle.stopped:
                operations.jobs.cancel(index_job, drain=True)
                await operations.jobs.wait(index_job)
        else:
            prepared = await operations.ingest.preview(
                pid,
                record.source,
                alias=context.alias,
                adapter=context.adapter,  # type: ignore[arg-type]
                options=context.options,
                add=context.add,
            )
        handle.set_done(1)

    async def finish(info: JobInfo) -> str | None:
        async with operations.locks(f"_source_operation:{record.operation_id}"):
            current = operations.get(record.operation_id)
            draft = current.import_context
            if current.attempt != attempt or draft is None or draft.job_id != jid:
                return None
            if index_job is not None:
                draft.job_id = index_job
                if current.control.get("action") == "cancel":
                    operations.jobs.cancel(index_job, drain=True)
            elif info.status == "succeeded" and prepared is not None:
                draft.preview_id, draft.step = prepared.preview_id, "preview"
            current.error = info.error
            operations._write(current)
        return context.import_id if commit else (prepared.preview_id if prepared else None)

    operations.jobs.submit(
        JobSpec(
            project_id=pid,
            kind="task",
            key=f"source-import:{record.operation_id}",
            units=[],
            job_id=jid,
            driver=drive,
            on_finish=finish,
            drain_workers=True,
        )
    )
    return record


async def start_import(
    operations: SourceOperations,
    operation: str,
    request: SourceOperationControl,
    *,
    commit: bool = False,
) -> SourceOperation:
    async with operations.locks(f"_source_operation:{operation}"):
        record = operations.get(operation)
        action = "import_commit" if commit else "import_preview"
        if not operations._check_control(record, request, action):
            return await operations.view(operation)
        context = record.import_context
        if context is None or record.purpose != "discover" or record.project_id is None:
            raise JobConflict("Save the import draft in an explicit project first")
        if record.status != "completed" or record.stage != "discovered":
            raise JobConflict("Finish source discovery before preparing an import")
        if context.step in {"previewing", "index"}:
            current = await import_view(operations, record.model_copy(deep=True))
            if current.status in ACTIVE or not current.cleanup_verified:
                raise JobConflict("Import work is already active")
            if current.status == "completed" and context.step == "index":
                return current
        record.control = {"action": action, **request.model_dump()}
        submit_import(operations, record, commit=commit)
        return await operations.view(operation)
