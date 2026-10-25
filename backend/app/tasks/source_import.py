"""Shared import orchestration for durable and legacy entry points (SRC-19)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.errors import JobConflict
from app.core.fsio import atomic_write_json, read_json, read_jsonl
from app.core.ids import new_ulid
from app.ingest.schemas import CommitResult
from app.ingest.service import SOURCES
from app.tasks import workspace_runs
from app.tasks.dicom_phase import PhaseRuns

if TYPE_CHECKING:
    from app.ingest.service import IngestService


async def commit_with_annotations(
    ingest: IngestService,
    project_id: str,
    preview_id: str,
    phase_runs: PhaseRuns,
    *,
    import_id: str | None = None,
) -> CommitResult:
    pv = ingest.preview_of(project_id, preview_id)
    import_id = import_id or new_ulid()
    found = workspace_runs.dataset_annotations(Path(pv.root), phase_runs) if pv.root else None
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
