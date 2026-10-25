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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from plugins.analyzers import checkpoint
from plugins.dicom import pipeline, scan
from plugins.dicom.identity import Identity
from plugins.protocol import Job


def _versions() -> dict[str, str]:
    from importlib import metadata

    out = {"dicom.convert": pipeline.VERSION}
    for pkg in ("pydicom", "SimpleITK"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = ""
    return out


def run(
    job_dir: str,
    *,
    cached_discover: Callable[[Path], list[scan.Series]] | None = None,
    cached_file_total: int = 0,
) -> int:
    job = Job(job_dir)
    spec = job.spec
    source = Path(str((spec.get("source") or {}).get("path", "")))
    dataset = job.dataset_dir
    out_dir = job.output_dir
    if not source.exists() or dataset is None or out_dir is None:
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

    result = pipeline.run(
        source,
        settings,
        identity,
        nifti_dir=dataset / "nifti",
        sidecar_dir=dataset / "sidecars",
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
        cached_discover=cached_discover,
        cached_file_total=cached_file_total,
        retry_item_ids=spec.get("retry_item_ids"),
    )
    extra: dict[str, Any] = {
        "identity": identity.as_dict(),
        "estimate": {**result.counts, **result.storage},
    }
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
        if inputs_seed is not None:
            analysis["inputs_seed"] = inputs_seed
        analysis["run_id"] = spec.get("phase_run_id")
        phase_annotations = analysis.pop("annotations", [])
        if analysis["status"] == "completed":
            annotations = [*annotations, *phase_annotations]
        extra["provenance"] = {"phase_analyzer": analysis}
    workspace = bool(spec.get("workspace"))
    if workspace:  # rows relative to the dataset root, which is imported as-is
        for r in result.rows:
            r["relative_path"] = f"nifti/{r.get('filename', '')}"
            if r.get("dicom_sidecar"):
                r["dicom_sidecar"] = f"sidecars/{r['filename']}.dicom.json"
    if not dry:
        pipeline.write_jsonl(out_dir / "metadata.jsonl", result.rows)
        pipeline.write_jsonl(out_dir / "diagnostics.jsonl", [d.as_dict() for d in result.diagnostics])
        summary = {"counts": result.counts, "storage": result.storage, "versions": _versions(), "analysis": analysis}
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        pipeline.write_jsonl(job.rel("annotations.jsonl"), annotations)
        if (
            workspace
            and not job.cancelled()
            and not result.counts["failed"]
            and not result.counts["pending"]
            and result.resource_wait is None
        ):
            pipeline.write_jsonl(out_dir / "annotations.jsonl", annotations)
            manifest = {
                "dataset": 1,
                "name": out_dir.name,
                "task": {"id": "dicom.convert", "version": pipeline.VERSION},
                "run_id": spec.get("run_id"),
                "phase_run_id": spec.get("phase_run_id"),
                "source": str(source),
                "settings": job.settings,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "counts": result.counts,
            }
            (out_dir / "dataset.json").write_text(json.dumps(manifest, indent=2) + "\n")
        job.outputs_manifest += [
            {
                "kind": "metadata",
                "path": str(out_dir / "metadata.jsonl"),
                "sha256": _digest(out_dir / "metadata.jsonl"),
            },
            {"kind": "annotations", "path": "annotations.jsonl", "sha256": _digest(job.rel("annotations.jsonl"))},
        ]
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
