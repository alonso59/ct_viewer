"""Bounded local conversion history, used inside the owned worker."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import statistics
import sys
from collections import defaultdict
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

from app.core.fsio import atomic_write_json

MAX_SAMPLES = 2048
MAX_BYTES = 1024 * 1024
MIN_SAMPLES = 5


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _runtime() -> dict[str, Any]:
    traced = None
    try:
        status = Path("/proc/self/status").read_text()
        traced = any(
            line.startswith("TracerPid:") and line.split()[1] != "0" for line in status.splitlines()
        )
    except OSError:
        pass
    return {
        "python": [sys.executable, platform.python_implementation(), platform.python_version()],
        "libc": platform.libc_ver(),
        "traced": traced,
        "preload": os.environ.get("LD_PRELOAD"),
    }


def context_signature(
    source: Path, destination: Path, settings: dict[str, Any], limits: dict[str, Any]
) -> str:
    from plugins.dicom import commits, convert, pipeline, scan

    target = destination
    while not target.exists():
        target = target.parent
    code = []
    for module in (convert, pipeline, scan):
        assert module.__file__ is not None
        code.append(commits.file_digest(Path(module.__file__)))
    return _digest(
        {
            "host": [platform.node(), platform.machine()],
            "runtime": _runtime(),
            "source_storage": [str(source.resolve()), source.stat().st_dev],
            "output_storage": [str(destination.resolve()), target.stat().st_dev],
            "reader": commits.reader_versions(pipeline.VERSION),
            "compressor": metadata.version("isal"),
            "code": code,
            "settings": settings,
            "limits": limits,
        }
    )


def _positive(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


class ConversionTimer:
    """History is advisory; a broken history withdraws ETA without changing image commits.

    The DICOM execution lock serializes writers. No source identifiers, paths or headers are
    stored. Ranges are empirical and explicitly low confidence pending reference calibration.
    """

    def __init__(
        self,
        path: Path,
        signature: str,
        attempt: str,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.path, self.context, self.attempt, self.emit = path, _digest(signature), attempt, emit
        self.pending: dict[str, dict[str, Any]] = {}
        self.samples: list[dict[str, Any]] = []
        self.available = True
        self.observations = 0
        self.dirty = False
        try:
            with path.open("rb") as fh:
                raw = fh.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Timing history exceeds its budget")
            record = json.loads(raw)
            samples = record["samples"]
            if (
                record["version"] != 1
                or not isinstance(samples, list)
                or len(samples) > MAX_SAMPLES
            ):
                raise ValueError("Unsupported timing history")
            for sample in samples:
                if (
                    set(sample) != {"context", "class", "event", "rate"}
                    or not _positive(sample["rate"])
                    or any(
                        not isinstance(sample[k], str)
                        or len(sample[k]) != 64
                        or any(c not in "0123456789abcdef" for c in sample[k])
                        for k in ("context", "class", "event")
                    )
                ):
                    raise ValueError("Invalid timing sample")
            self.samples = samples
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            self.available = False

    def __call__(self, event: dict[str, Any]) -> dict[str, Any]:
        if event["t"] == "plan":
            self.pending = {
                unit["id"]: {"class": _digest(unit["class"]), "work": unit["work"]}
                for unit in event["units"]
            }
        elif event["t"] == "unit":
            committed = event.get("committed", True)
            unit = self.pending.get(event["id"])
            if committed:
                self.pending.pop(event["id"], None)
            seconds = event.get("seconds")
            if (
                unit
                and committed
                and self.available
                and _positive(seconds)
                and _positive(unit.get("work"))
            ):
                rate = seconds / unit["work"]
                identity = _digest([self.attempt, event["id"]])
                if _positive(rate) and not any(s["event"] == identity for s in self.samples):
                    self.samples.append(
                        {
                            "context": self.context,
                            "class": unit["class"],
                            "event": identity,
                            "rate": rate,
                        }
                    )
                    self.samples = self.samples[-MAX_SAMPLES:]
                    self.observations += 1
                    self.dirty = True
        if (
            self.dirty
            and self.available
            and (
                event["t"] == "finish"
                or self.observations in {1, MIN_SAMPLES}
                or self.observations % 16 == 0
                or not self.pending
            )
        ):
            try:
                atomic_write_json(self.path, {"version": 1, "samples": self.samples})
                self.dirty = False
            except OSError:
                self.available = False
        estimate = self.estimate()
        if self.emit is not None:
            self.emit({"t": "conversion_time", "estimate": estimate})
        return estimate

    def estimate(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "basis": "unknown",
            "confidence": "unknown",
            "sample_count": 0,
            "remaining_units": len(self.pending),
            "estimated_s": None,
            "lower_s": None,
            "upper_s": None,
        }
        if not self.pending:
            return {**result, "basis": "complete", "estimated_s": 0, "lower_s": 0, "upper_s": 0}
        if not self.available or any(not _positive(u.get("work")) for u in self.pending.values()):
            return result
        work: dict[str, float] = defaultdict(float)
        for unit in self.pending.values():
            work[unit["class"]] += unit["work"]
        rates: dict[str, list[float]] = {category: [] for category in work}
        for sample in self.samples:
            if sample["context"] == self.context and sample["class"] in rates:
                rates[sample["class"]].append(sample["rate"])
        result["sample_count"] = sum(len(values) for values in rates.values())
        if any(len(values) < MIN_SAMPLES for values in rates.values()):
            return result
        point = sum(statistics.median(rates[c]) * amount for c, amount in work.items())
        lower = sum(min(rates[c]) * 0.8 * amount for c, amount in work.items())
        upper = sum(max(rates[c]) * 1.25 * amount for c, amount in work.items())
        if not all(_positive(value) for value in (point, lower, upper)):
            return result
        return {
            **result,
            "basis": "history",
            "confidence": "low",
            "estimated_s": point,
            "lower_s": lower,
            "upper_s": upper,
        }


def for_job(job: Path) -> ConversionTimer | None:
    from dataclasses import asdict

    from plugins.dicom.pipeline import Settings

    from app.core.fsio import append_jsonl, read_json

    binding = job / "timing-history-path.json"
    if not binding.exists():
        return None
    spec = read_json(job / "job.json")
    destination = spec.get("timing_destination")
    if not destination or not Path(destination).exists():
        return None
    source = Path(spec["source"]["path"])
    limits = read_json(job / "resources.json")
    effective = read_json(job / "worker-resources.json")
    limits = {
        **limits,
        "effective_cpus": len(effective["affinity"]),
        "native_threads": effective["native_threads"],
    }
    pixel_settings = asdict(Settings.from_dict({**spec.get("context", {}), **spec["settings"]}))
    signature = context_signature(source, Path(destination), pixel_settings, limits)
    return ConversionTimer(
        Path(read_json(binding)["path"]),
        signature,
        str(job),
        lambda event: append_jsonl(job / "progress.jsonl", [event]),
    )
