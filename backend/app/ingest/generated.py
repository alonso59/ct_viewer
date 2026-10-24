"""DCM-18/TSK-09: replay a logical conversion's import without appending it twice."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.errors import JobConflict, NotFound
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import is_ulid
from app.ingest.schemas import CommitResult

if TYPE_CHECKING:
    from app.ingest.service import IngestService


async def import_once(
    service: IngestService,
    project: str,
    run: str,
    metadata: bytes,
    *,
    root: str,
    alias: str,
    source_key: str,
) -> CommitResult:
    from app.ingest.service import SOURCES

    if not is_ulid(run):
        raise JobConflict("Generated import requires a valid logical run identity")
    directory = service.workspace.project_dir(project) / SOURCES
    path = directory / "generated" / f"{run}.json"
    identity = {
        "version": 1,
        "import_id": run,
        "sha256": hashlib.sha256(metadata).hexdigest(),
        "root": root,
        "alias": alias,
        "source_key": source_key,
    }
    async with service.locks(f"_generated_import:{project}"):
        receipt: dict[str, Any] = read_json(path) if path.exists() else identity
        if not isinstance(receipt, dict) or any(
            receipt.get(k) != value for k, value in identity.items()
        ):
            raise JobConflict(
                "Generated import metadata/root changed; preserve the existing snapshot"
            )
        previous_job = receipt.get("job_id")
        if previous_job is not None and (
            not isinstance(previous_job, str) or not is_ulid(previous_job)
        ):
            raise JobConflict("Generated import index receipt is corrupt")
        current = next(
            (r for r in service.workspace.get(project).path_roots if r.alias == alias), None
        )
        if current is None or Path(current.path) != Path(root):
            raise JobConflict("Generated import root changed; review the run's output destination")
        atomic_write_json(path, receipt)  # persist intent before any snapshot/import append
        existing = next((r for r in service.imports(project) if r.import_id == run), None)
        if existing is None:
            preview = await service.preview(
                project,
                root,
                alias=alias,
                uploads={"metadata": ("metadata.jsonl", metadata)},
                source_key=source_key,
            )
            result = await service.commit(project, preview.preview_id, import_id=run)
        else:
            snapshot = directory / run / "metadata.jsonl"
            if (
                existing.root != root
                or existing.alias != alias
                or existing.source_key != source_key
                or not snapshot.is_file()
                or hashlib.sha256(snapshot.read_bytes()).hexdigest() != identity["sha256"]
            ):
                raise JobConflict("Committed generated import is unavailable or incompatible")
            job_id = await _index_once(service, project, run, previous_job)
            result = CommitResult(import_id=run, job_id=job_id)
        atomic_write_json(path, {**identity, "job_id": result.job_id})
        return result


async def _index_once(service: IngestService, project: str, run: str, previous: str | None) -> str:
    status = service.store.status(project)
    job_id = previous or (status.job_id if status.import_id == run else None)
    if job_id:
        try:
            job = service.jobs.get(job_id)
            if (
                job.project_id == project
                and job.kind == "index"
                and job.status in {"queued", "running", "succeeded"}
            ):
                return job_id
        except NotFound:
            pass
    service._check_no_index_job(project)
    return await service._start_index(project, run)
