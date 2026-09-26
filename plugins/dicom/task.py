"""`dicom.convert` task entry (builtin runtime, TSK-07): `run(job_dir) -> int`.

job.json extras: `source {path}`, `dataset_dir`, `dataset_ref` (`ALIAS:rel` of `dataset_dir`),
`identity` (the project registry), `previous_metadata` (the last run's rows), `project_id`.
result.json extras: `identity` (merged back by the backend), `estimate` (dry run, DCM-06).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from plugins.dicom import pipeline
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


def run(job_dir: str) -> int:
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
            json.loads(line)
            for line in Path(prev_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    identity = Identity.from_dict(spec.get("identity"))
    settings = pipeline.Settings.from_dict({**job.context, **job.settings})
    dry = job.mode == "estimate"

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
    )
    extra: dict[str, Any] = {
        "identity": identity.as_dict(),
        "estimate": {**result.counts, **result.storage},
    }
    if dry:  # DCM-06: which series converts, which is skipped and why, storage per series
        extra["estimate"]["series_plan"] = result.plan
    annotations = result.annotations
    if not job.settings.get("phase_analyzer", True):  # DCM-14: the phase layer is optional
        annotations = [a for a in annotations if a.get("field") != "phase"]
    workspace = bool(spec.get("workspace"))
    if workspace:  # TSK-13: rows relative to the dataset root, which is imported as-is (SRC-16)
        for r in result.rows:
            r["relative_path"] = f"nifti/{r.get('filename', '')}"
            if r.get("dicom_sidecar"):
                r["dicom_sidecar"] = f"sidecars/{r['filename']}.dicom.json"
    if not dry:
        pipeline.write_jsonl(out_dir / "metadata.jsonl", result.rows)
        pipeline.write_jsonl(
            out_dir / "diagnostics.jsonl", [d.as_dict() for d in result.diagnostics]
        )
        summary = {"counts": result.counts, "storage": result.storage, "versions": _versions()}
        (out_dir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        pipeline.write_jsonl(job.rel("annotations.jsonl"), annotations)
        if workspace:
            pipeline.write_jsonl(out_dir / "annotations.jsonl", annotations)
            manifest = {
                "dataset": 1,
                "name": out_dir.name,
                "task": {"id": "dicom.convert", "version": pipeline.VERSION},
                "run_id": spec.get("run_id"),
                "source": str(source),
                "settings": job.settings,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "counts": result.counts,
            }
            (out_dir / "dataset.json").write_text(json.dumps(manifest, indent=2) + "\n")
        job.outputs_manifest += [
            {"kind": "metadata", "path": str(out_dir / "metadata.jsonl")},
            {"kind": "annotations", "path": "annotations.jsonl"},
        ]
    failed_all = result.counts["failed"] and not (
        result.counts["converted"] + result.counts["already_converted"]
    )
    job.finish(versions=_versions(), status="failed" if failed_all else None, extra=extra)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]) if len(sys.argv) == 2 else 2)
