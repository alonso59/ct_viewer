"""In-image DICOM worker entry; arguments contain only the private attempt directory."""

from __future__ import annotations

import ctypes
import json
import os
import signal
import sys
import time
from collections.abc import Mapping
from pathlib import Path


def arm_parent_death(expected_parent: int) -> None:
    """Stop a worker orphaned during a backend crash, before importing native readers."""
    parent = os.getppid()
    if parent != expected_parent:
        os.kill(os.getpid(), signal.SIGKILL)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # Linux OCI PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "Cannot arm DICOM worker parent-death cleanup")
    if os.getppid() != parent:
        os.kill(os.getpid(), signal.SIGKILL)


def main(job_dir: Path) -> int:
    launch = json.loads((job_dir / "launch.json").read_text())
    arm_parent_death(int(launch["parent"]["pid"]))
    from app.core.fsio import append_jsonl, atomic_write_json, read_json, write_jsonl_atomic
    from app.tasks import protocol

    atomic_write_json(job_dir / "worker-ready.json", {"pid": os.getpid()})
    while not (job_dir / "dispatch").exists():
        time.sleep(0.01)
    from app.tasks.dicom_resources import apply_worker

    apply_worker(job_dir)
    from app.tasks.dicom_timings import record_stage
    from app.tasks.source_inventory import SourceInventory

    spec = read_json(job_dir / protocol.JOB)
    limits = read_json(job_dir / "resources.json") if (job_dir / "resources.json").exists() else {}

    def stop() -> bool:
        return (job_dir / protocol.CANCEL).exists()

    if spec.get("operation") == "phase":
        import hashlib

        from plugins.analyzers.checkpoint import AnalysisConflict, retry_phase

        started = time.monotonic()
        try:
            seed = spec.get("analysis_seed")
            analysis = retry_phase(
                Path(spec["analysis_state"]),
                seed=Path(seed["path"]) if seed else None,
                seed_sha256=seed["sha256"] if seed else None,
                cancelled=stop,
                on_progress=lambda done, total: append_jsonl(
                    job_dir / protocol.PROGRESS,
                    [
                        {
                            "t": "stage",
                            "stage": "analyzing",
                            "done": done,
                            "total": total,
                        }
                    ],
                ),
            )
        except (AnalysisConflict, OSError) as exc:
            analysis = {
                "status": "failed",
                "total": int(spec.get("phase_total", 0)),
                "error": str(exc)
                if isinstance(exc, AnalysisConflict)
                else f"{type(exc).__name__}: phase checkpoint unavailable; retry analysis",
            }
        record_stage(
            job_dir,
            "analyzing",
            time.monotonic() - started,
            int(analysis.get("done", 0)),
            complete=analysis.get("status") == "completed",
        )
        annotations = analysis.pop("annotations", [])
        output = job_dir / "annotations.jsonl"
        write_jsonl_atomic(output, annotations)
        analysis["run_id"] = spec["run_id"]
        atomic_write_json(
            job_dir / protocol.RESULT,
            {
                "status": analysis["status"],
                "provenance": {"phase_analyzer": analysis},
                "outputs_manifest": [
                    {
                        "kind": "annotations",
                        "path": output.name,
                        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                    }
                ],
            },
        )
        return 0
    if spec.get("operation") == "open":
        from app.tasks.dicom_stage import convert_series

        error = convert_series(
            spec["source"],
            spec["files"],
            spec["destination"],
            limits["memory_mb"],
            expected_fingerprint=spec.get("expected_fingerprint"),
        )
        atomic_write_json(job_dir / protocol.RESULT, {"error": error})
        return 0
    if spec.get("operation", "task") == "task":
        from plugins.dicom.task import run

        from app.tasks.dicom_eta import for_job

        timer = for_job(job_dir)

        binding = spec.get("source_inventory")
        if binding:
            with SourceInventory(Path(binding["path"]), Path(spec["source"]["path"])) as inventory:
                summary = inventory.scan(
                    cancelled=stop,
                    batch_size=int(limits.get("batch_size", 64)),
                    max_bytes=int(limits.get("inventory_mb", 512)) * 1024**2,
                )
                if not summary["complete"] or summary["generation"] != binding["generation"]:
                    atomic_write_json(
                        job_dir / protocol.RESULT,
                        {
                            "status": "failed",
                            "error": (
                                "Source plan conflict: discovery changed; prepare a new dry run"
                            ),
                        },
                    )
                    return 0
                code = run(
                    str(job_dir),
                    cached_discover=inventory.discover,
                    cached_file_total=summary["dicom"],
                    on_timing=timer,
                )
        else:
            code = run(str(job_dir), on_timing=timer)
        task_result = protocol.read_result(job_dir) or {}
        analysis = task_result.get("provenance", {}).get("phase_analyzer", {})
        if analysis.get("duration_s") is not None:
            record_stage(
                job_dir,
                "analyzing",
                analysis["duration_s"],
                int(analysis.get("done", 0)),
                complete=analysis.get("status") == "completed",
            )
        publication = task_result.get("provenance", {}).get("dataset_publication_seconds")
        if publication is not None:
            counts = task_result.get("estimate", {})
            record_stage(
                job_dir,
                "registration",
                publication,
                int(counts.get("converted", 0)) + int(counts.get("already_converted", 0)),
                complete=not stop() and not counts.get("failed") and not counts.get("pending"),
            )
        return code
    last_tick = float("-inf")

    def progress(counters: Mapping[str, object]) -> None:
        nonlocal last_tick
        if time.monotonic() - last_tick >= 0.25:
            append_jsonl(job_dir / protocol.PROGRESS, [{"t": "inventory", **counters}])
            last_tick = time.monotonic()

    if spec["operation"] == "inventory":
        started = time.monotonic()
        open_ready = False
        inventory_path = Path(spec.get("inventory", job_dir.parent / "inventory.sqlite"))
        with SourceInventory(inventory_path, Path(spec["source"])) as inventory:
            summary = inventory.scan(
                cancelled=stop,
                on_progress=progress,
                batch_size=int(limits.get("batch_size", 64)),
                max_bytes=int(limits.get("inventory_mb", 512)) * 1024**2,
            )
            measured = record_stage(
                job_dir,
                "discovery",
                time.monotonic() - started,
                int(summary["files"]),
                complete=bool(summary["complete"]),
            )
            if measured is not None:
                summary["discovery_time"] = measured
            if spec.get("purpose") == "open" and summary["complete"]:
                import hashlib

                from app.tasks.source_open import prepare_open, reader_identity

                session = prepare_open(
                    inventory,
                    cancelled=lambda: (job_dir / protocol.CANCEL).exists(),
                    on_progress=progress,
                )
                if session is not None:
                    session.sid = spec["operation_id"]
                    atomic_write_json(
                        job_dir / "open-session.json", session.model_dump(mode="json")
                    )
                    summary["open_session_sha256"] = hashlib.sha256(
                        (job_dir / "open-session.json").read_bytes()
                    ).hexdigest()
                    summary["open_reader"] = reader_identity()
                    open_ready = True
        atomic_write_json(job_dir / protocol.RESULT, {"summary": summary, "open_ready": open_ready})
        return 0
    if spec["operation"] == "estimate":
        from plugins.dicom import pipeline
        from plugins.dicom.identity import Identity

        from app.tasks.dicom_eta import for_job

        started = time.monotonic()
        last_stage = ""

        def stage(name: str, done: int, total: int) -> None:
            nonlocal last_stage, last_tick
            if name != last_stage or time.monotonic() - last_tick >= 0.25 or done == total:
                append_jsonl(
                    job_dir / protocol.PROGRESS,
                    [
                        {
                            "t": "stage",
                            "stage": name,
                            "done": done,
                            "total": total,
                        }
                    ],
                )
                last_stage, last_tick = name, time.monotonic()

        source = Path(spec["source"]["path"])
        identity = Identity.from_dict(spec.get("identity"))
        with SourceInventory(Path(spec["inventory"]), source) as inventory:
            summary = inventory.scan(
                cancelled=stop,
                on_progress=progress,
                batch_size=int(limits.get("batch_size", 64)),
                max_bytes=int(limits.get("inventory_mb", 512)) * 1024**2,
            )
            if not summary["complete"]:
                atomic_write_json(
                    job_dir / protocol.RESULT, {"status": "failed", "summary": summary}
                )
                return 0
            planned = time.monotonic()
            result = pipeline.run(
                source,
                pipeline.Settings.from_dict({**spec.get("context", {}), **spec["settings"]}),
                identity,
                nifti_dir=Path(spec["dataset_dir"]) / "nifti",
                sidecar_dir=Path(spec["dataset_dir"]) / "sidecars",
                ref_rel="dataset",
                ref_alias="DERIVED",
                salt=str(spec.get("project_id", "")),
                previous=[],
                dry_run=True,
                cancelled=stop,
                on_stage=stage,
                cached_discover=inventory.discover,
                cached_file_total=summary["dicom"],
                on_timing=for_job(job_dir),
            )
        record_stage(
            job_dir,
            "planning",
            time.monotonic() - planned,
            int(result.counts["series"]),
            complete=not stop(),
        )
        atomic_write_json(
            job_dir / protocol.RESULT,
            {
                "status": "cancelled" if stop() else "completed",
                "summary": summary,
                "estimate": {**result.counts, **result.storage, "series_plan": result.plan},
                "identity": identity.as_dict(),
                "duration_s": time.monotonic() - started,
                "conversion_time": result.conversion_time,
            },
        )
        return 0
    raise ValueError("Unsupported DICOM worker operation")


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
