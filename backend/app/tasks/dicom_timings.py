"""Measured stage durations; advisory history never controls task completion."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from app.core.fsio import atomic_write_json, read_json
from app.core.locks import FileLock, LockHeldError
from app.tasks.dicom_eta import MAX_BYTES, MAX_SAMPLES, _positive, context_signature

log = logging.getLogger(__name__)
STAGES = frozenset({"discovery", "planning", "registration", "analyzing"})


def record_stage(
    job: Path, stage: str, seconds: float, work: int, *, complete: bool = True
) -> dict[str, Any] | None:
    if stage not in STAGES or not _positive(seconds) or work < 0:
        return None
    sample: dict[str, Any] | None = None
    try:
        path = job / "stage-timings.json"
        if path.exists() and path.stat().st_size > MAX_BYTES:
            raise ValueError("Stage measurements exceed their budget")
        measured = read_json(path) if path.exists() else {"version": 1, "stages": {}}
        if (
            not isinstance(measured, dict)
            or measured.get("version") != 1
            or not isinstance(measured.get("stages"), dict)
        ):
            raise ValueError("Unsupported stage measurements")
        sample = measured["stages"].setdefault(
            stage, {"seconds": seconds, "work": work, "complete": complete}
        )
        if (
            not isinstance(sample, dict)
            or not _positive(sample.get("seconds"))
            or type(sample.get("work")) is not int
            or type(sample.get("complete")) is not bool
        ):
            sample = None
            raise ValueError("Invalid stage measurement")
        atomic_write_json(path, measured)
        binding = job / "timing-history-path.json"
        if not binding.exists() or not sample["complete"] or sample["work"] == 0:
            return sample
        authority = read_json(binding)
        history = Path(authority["path"]).with_name("stage-timing-history.json")
        spec = read_json(job / "job.json")
        source = spec.get("source") or spec.get("analysis_state")
        source = source.get("path") if isinstance(source, dict) else source
        if not isinstance(source, str):
            raise ValueError("Stage measurement has no source identity")
        destination = spec.get("timing_destination") or history.parent
        limits = {**read_json(job / "resources.json"), "job_workers": authority.get("job_workers")}
        effective = job / "worker-resources.json"
        if effective.exists():
            runtime = read_json(effective)
            limits = {
                **limits,
                "effective_cpus": len(runtime["affinity"]),
                "native_threads": runtime["native_threads"],
            }
        signature = context_signature(
            Path(source),
            Path(destination),
            {
                "stage": stage,
                "resumed": spec.get("attempt", 1) > 1,
                "scope": "workspace"
                if spec.get("workspace")
                else "project"
                if spec.get("project_id")
                else spec.get("operation"),
                "settings": spec.get("settings", {}),
            },
            limits,
        )
        event = hashlib.sha256(f"{job}:{stage}".encode()).hexdigest()
        row = {"context": signature, "event": event, "stage": stage, **sample}
        lock = FileLock(history.with_suffix(".lock"))
        deadline = time.monotonic() + 1
        while True:
            try:
                lock.acquire()
                break
            except LockHeldError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timing history writer is busy") from None
                time.sleep(0.01)
        try:
            data: dict[str, Any] = {"version": 1, "samples": []}
            if history.exists():
                with history.open("rb") as stream:
                    raw = stream.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError("Stage timing history exceeds its budget")
                data = json.loads(raw)
                if (
                    not isinstance(data, dict)
                    or set(data) != {"version", "samples"}
                    or data.get("version") != 1
                    or not isinstance(data.get("samples"), list)
                    or len(data["samples"]) > MAX_SAMPLES
                    or any(
                        not isinstance(item, dict)
                        or set(item) != {"context", "event", "stage", "seconds", "work", "complete"}
                        or not _positive(item.get("seconds"))
                        or type(item.get("work")) is not int
                        or item["work"] <= 0
                        or item.get("stage") not in STAGES
                        or item.get("complete") is not True
                        or not isinstance(item.get("event"), str)
                        or len(item["event"]) != 64
                        or not isinstance(item.get("context"), str)
                        or len(item["context"]) != 64
                        for item in data["samples"]
                    )
                ):
                    raise ValueError("Unsupported stage timing history")
            if not any(item.get("event") == event for item in data["samples"]):
                data["samples"] = [*data["samples"], row][-MAX_SAMPLES:]
                atomic_write_json(history, data)
        finally:
            lock.release()
        return sample
    except (OSError, ValueError, KeyError, TypeError, TimeoutError):
        log.warning("Stage timing history unavailable", extra={"stage": stage})
        return sample
