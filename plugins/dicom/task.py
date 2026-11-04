"""`dicom.convert` task entry: `run(job_dir) -> int`.

job.json extras: `source {path}`, `dataset_dir`, `dataset_ref` (`ALIAS:rel` of `dataset_dir`),
`identity` (the project registry), `previous_metadata` (the last run's rows), `project_id`.
result.json extras: `identity` (merged back by the backend), `estimate` (dry run).
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from rw_dicom import dataset, pipeline
from rw_dicom.analyzers import checkpoint
from rw_dicom.durable import write_jsonl
from rw_dicom.identity import Identity

from plugins.protocol import Job


def _versions() -> dict[str, str]:
    from importlib import metadata

    out = {"dicom.convert": pipeline.VERSION}
    for pkg in ("rw-dicom", "pydicom", "SimpleITK", "isal"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = ""
    return out


def run(
    job_dir: str,
    *,
    inventory: pipeline.SeriesSource | None = None,
    cached_file_total: int = 0,
    on_timing: pipeline.Timing | None = None,
) -> int:
    job = Job(job_dir)
    spec = job.spec
    source = Path(str((spec.get("source") or {}).get("path", "")))
    dataset_dir = job.dataset_dir
    out_dir = job.output_dir
    if not source.exists() or dataset_dir is None or out_dir is None:
        job.finish(status="failed", error="source, dataset_dir and output_dir are required")
        return 0
    alias, _, rel = str(spec.get("dataset_ref", "DERIVED:")).partition(":")
    previous: list[dict[str, Any]] = []
    prev_path = spec.get("previous_metadata")
    if prev_path and Path(prev_path).is_file():
        previous = [
            json.loads(line) for line in Path(prev_path).read_text(encoding="utf-8").splitlines() if line.strip()
        ]
    identity = Identity.from_dict(spec.get("identity"))
    settings = pipeline.Settings.from_dict({**job.context, **job.settings})
    dry = job.mode == "estimate"
    runtime = json.loads((job.dir / "resources.json").read_text()) if (job.dir / "resources.json").exists() else {}

    def progress(iid: str, status: str, outputs: list[dict[str, Any]], message: str) -> None:
        job.counts["items"] += 1
        job.item(iid, status, outputs, message)

    try:
        result = pipeline.run(
            source,
            settings,
            identity,
            nifti_dir=dataset_dir / "nifti",
            sidecar_dir=dataset_dir / "sidecars",
            ref_rel=rel,
            ref_alias=alias,
            salt=str(spec.get("project_id", "")),
            previous=previous,
            dry_run=dry,
            progress=progress,
            cancelled=job.cancelled,
            on_total=job.total,
            on_stage=job.stage,
            checkpoint=out_dir / "conversion-pin.json" if not dry else None,
            memory_mb=runtime.get("memory_mb"),
            inventory=inventory,
            cached_file_total=cached_file_total,
            retry_item_ids=spec.get("retry_item_ids"),
            on_timing=on_timing,
            on_bytes=None if dry else job.bytes_progress,
            workers=int(runtime.get("workers", 1)),
            allow_mixed_versions=bool(spec.get("allow_mixed_versions")),
        )
    except pipeline.MixedVersions as exc:
        job.finish(status="failed", error=str(exc), versions=_versions())
        return 0
    extra: dict[str, Any] = {
        "identity": identity.as_dict(),
        "estimate": {**result.counts, **result.storage},
    }
    if result.conversion_time is not None:
        extra["conversion_time"] = result.conversion_time
    if result.resource_wait is not None:
        extra["resource_wait"] = result.resource_wait
    if dry:  # which series converts, which is skipped and why, storage per series
        extra["estimate"]["series_plan"] = result.plan
    annotations = result.annotations
    analysis = None
    if (
        not dry
        and job.settings.get("phase_analyzer", True)
        and not job.cancelled()
        and not result.counts["failed"]
        and not result.counts["pending"]
        and result.resource_wait is None
        and result.analyzer_rows
    ):
        job.stage("analyzing", 0, len(result.analyzer_rows))
        inputs_seed = None
        analysis_started = time.monotonic()
        try:
            inputs_seed = checkpoint.write_seed(
                job.dir / "phase-inputs",
                result.analyzer_rows,
                {"phase_vocabulary": job.context.get("phase_vocabulary", [])},
            )
            analysis = checkpoint.analyze_phase(
                Path(spec.get("analysis_state", job.dir / "phase-analyzer")),
                result.analyzer_rows,
                {"phase_vocabulary": job.context.get("phase_vocabulary", [])},
                cancelled=lambda: (
                    job.cancelled() or bool(spec.get("phase_cancel") and Path(spec["phase_cancel"]).exists())
                ),
                on_progress=lambda done, total: job.stage("analyzing", done, total),
            )
        except Exception as exc:  # noqa: BLE001 -- optional analysis cannot fail committed conversion
            analysis = {
                "task": "analyzer.phase",
                "status": "failed",
                "total": len(result.analyzer_rows),
                "error": str(exc)
                if isinstance(exc, checkpoint.AnalysisConflict)
                else f"{type(exc).__name__}: phase analyzer failed; retry analysis",
            }
        analysis["duration_s"] = time.monotonic() - analysis_started
        if inputs_seed is not None:
            analysis["inputs_seed"] = inputs_seed
        analysis["run_id"] = spec.get("phase_run_id")
        phase_annotations = analysis.pop("annotations", [])
        if analysis["status"] == "completed":
            annotations = [*annotations, *phase_annotations]
        extra["provenance"] = {"phase_analyzer": analysis}
    publication_started = time.monotonic()
    workspace = bool(spec.get("workspace"))
    if workspace:  # rows relative to the dataset root, which is imported as-is
        dataset.relative_rows(result.rows)
    if not dry:
        summary = {
            "counts": result.counts,
            "storage": result.storage,
            "versions": _versions(),
            "analysis": analysis,
            "units_by_versions": result.units_by_versions,
        }
        manifest = None
        if workspace:
            manifest = dataset.manifest(
                name=out_dir.name,
                run_id=spec.get("run_id"),
                phase_run_id=spec.get("phase_run_id"),
                source=source,
                settings=job.settings,
                result=result,
            )
        dataset.write(
            out_dir,
            rows=result.rows,
            diagnostics=[d.as_dict() for d in result.diagnostics],
            summary=summary,
            annotations=annotations,
            dataset=manifest,
            complete=dataset.is_complete(result, job.cancelled()),
        )
        write_jsonl(job.rel("annotations.jsonl"), annotations)
        job.outputs_manifest += [
            {
                "kind": "metadata",
                "path": str(out_dir / "metadata.jsonl"),
                "sha256": _digest(out_dir / "metadata.jsonl"),
            },
            {"kind": "annotations", "path": "annotations.jsonl", "sha256": _digest(job.rel("annotations.jsonl"))},
        ]
    if workspace and not dry:
        extra.setdefault("provenance", {})["dataset_publication_seconds"] = time.monotonic() - publication_started
    failed_all = result.counts["failed"] and not (result.counts["converted"] + result.counts["already_converted"])
    status = None
    error = None
    if result.resource_wait is not None:
        status = "waiting_for_resources"
    elif not job.cancelled() and result.counts["pending"]:
        status = "interrupted"
        error = "Unattempted series remain; Resume pending to finish this conversion"
    elif failed_all:
        status = "failed"
    job.finish(
        versions=_versions(),
        status=status,
        error=error,
        extra=extra,
    )
    return 0


def _digest(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]) if len(sys.argv) == 2 else 2)
