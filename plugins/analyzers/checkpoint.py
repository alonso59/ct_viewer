"""Private metadata-only phase checkpoints. Image conversion is never called here."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from plugins import text
from plugins.analyzers import phase, row_key
from plugins.protocol import utc_now, write_json_atomic

BATCH_SIZE = 64


class AnalysisConflict(ValueError):
    """Pinned metadata/rules or a committed annotation batch no longer match."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _write(path: Path, value: Any) -> None:
    write_json_atomic(path, value)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        raise AnalysisConflict("Analyzer checkpoint is unavailable or corrupt") from None


def retry_phase(
    state: Path,
    *,
    seed: Path | None = None,
    seed_sha256: str | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    on_progress: Callable[[int, int], None] = lambda _done, _total: None,
) -> dict[str, Any]:
    if not (state / "inputs.json").exists() and seed is not None:
        try:
            pinned = json.loads(seed.read_bytes())
        except (OSError, ValueError):
            raise AnalysisConflict("Analyzer recovery seed is unavailable or corrupt") from None
        if _digest(pinned) != seed_sha256:
            raise AnalysisConflict("Analyzer recovery seed changed")
        if (
            not isinstance(pinned, dict)
            or set(pinned) != {"version", "inputs", "identity"}
            or pinned["version"] != 1
            or not isinstance(pinned["inputs"], dict)
            or set(pinned["inputs"]) != {"rows", "config"}
        ):
            raise AnalysisConflict("Analyzer recovery seed is corrupt")
        inputs = _inputs(pinned["inputs"]["rows"], pinned["inputs"]["config"])
        if pinned["identity"] != _identity(inputs):
            raise AnalysisConflict("Analyzer recovery metadata/settings/rules changed; start a new analysis")
        return analyze_phase(
            state,
            inputs["rows"],
            inputs["config"],
            cancelled=cancelled,
            on_progress=on_progress,
            recover_inputs=True,
        )
    inputs = _read(state / "inputs.json")
    if not isinstance(inputs, dict) or set(inputs) != {"rows", "config"}:
        raise AnalysisConflict("Pinned analyzer metadata is corrupt")
    return analyze_phase(state, inputs["rows"], inputs["config"], cancelled=cancelled, on_progress=on_progress)


def _inputs(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) or not isinstance(config, dict):
        raise AnalysisConflict("Pinned analyzer metadata is corrupt")
    fields = {*phase.INPUT_FIELDS, "item_id", "case_identity_key", "series_uid"}
    return {"rows": [{key: value for key, value in row.items() if key in fields} for row in rows], "config": config}


def _identity(inputs: dict[str, Any]) -> dict[str, Any]:
    assert phase.__file__ is not None and text.__file__ is not None
    return {
        "inputs": _digest(inputs),
        "rules_version": phase.RULES_VERSION,
        "code": [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (phase.__file__, text.__file__)],
    }


def write_seed(directory: Path, rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, str]:
    inputs = _inputs(rows, config)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise AnalysisConflict("Analyzer recovery seed requires a private directory")
    path = directory / "seed.json"
    payload = {"version": 1, "inputs": inputs, "identity": _identity(inputs)}
    if path.exists():
        if _read(path) != payload:
            raise AnalysisConflict("Analyzer recovery seed changed")
    else:
        _write(path, payload)
    fd = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"sha256": _digest(payload)}


def analyze_phase(
    state: Path,
    rows: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    cancelled: Callable[[], bool] = lambda: False,
    on_progress: Callable[[int, int], None] = lambda _done, _total: None,
    recover_inputs: bool = False,
) -> dict[str, Any]:
    rows = _inputs(rows, config)["rows"]
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    if state.stat().st_mode & 0o077:
        raise AnalysisConflict("Analyzer input checkpoint requires a private directory")
    with (state / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AnalysisConflict("Another attempt owns this analyzer checkpoint") from None
        return _analyze(state, rows, config, cancelled, on_progress, recover_inputs)


def _analyze(
    state: Path,
    rows: list[dict[str, Any]],
    config: dict[str, Any],
    cancelled: Callable[[], bool],
    on_progress: Callable[[int, int], None],
    recover_inputs: bool,
) -> dict[str, Any]:
    inputs = {"rows": rows, "config": config}
    keys = [row_key(row) for row in rows]
    if len(set(keys)) != len(keys) or any(key in {"", "|"} for key in keys):
        raise AnalysisConflict("Analyzer metadata contains missing or duplicate item identities")
    identity = _identity(inputs)
    path = state / "checkpoint.json"
    if path.exists():
        record = _read(path)
        if not isinstance(record, dict) or record.get("version") != 1 or record.get("identity") != identity:
            raise AnalysisConflict("Analyzer metadata/settings/rules changed; start a new analysis")
        if (
            not isinstance(record.get("batches"), dict)
            or type(record.get("attempt")) is not int
            or record["attempt"] < 0
            or record.get("status") not in {"running", "completed", "failed", "cancelled"}
        ):
            raise AnalysisConflict("Analyzer checkpoint is corrupt")
        if recover_inputs and not (state / "inputs.json").exists():
            _write(state / "inputs.json", inputs)
        if _digest(_read(state / "inputs.json")) != identity["inputs"]:
            raise AnalysisConflict("Pinned analyzer metadata changed")
    else:
        _write(state / "inputs.json", inputs)
        record = {"version": 1, "identity": identity, "attempt": 0, "batches": {}, "created_at": utc_now()}
    cached: dict[str, list[dict[str, Any]]] = {}
    expected = {str(n) for n in range(0, len(rows), BATCH_SIZE)}
    for name, digest in record["batches"].items():
        if name not in expected:
            raise AnalysisConflict("Analyzer checkpoint contains an unknown batch")
        batch = _read(state / f"batch-{name}.json")
        if not isinstance(batch, list) or _digest(batch) != digest:
            raise AnalysisConflict("Committed analyzer annotations changed")
        cached[name] = batch
    if record.get("status") == "completed":
        if set(cached) != expected:
            raise AnalysisConflict("Completed analyzer checkpoint is missing batches")
        return _result(
            record, [a for offset in range(0, len(rows), BATCH_SIZE) for a in cached[str(offset)]], len(rows)
        )
    annotations: list[dict[str, Any]] = []
    record.update(status="running", error=None, updated_at=utc_now(), attempt=record["attempt"] + 1)
    _write(path, record)
    try:
        for offset in range(0, len(rows), BATCH_SIZE):
            if cancelled():
                record["status"] = "cancelled"
                break
            key = str(offset)
            batch_path = state / f"batch-{key}.json"
            if key in record["batches"]:
                batch = cached[key]
            else:
                batch = [{**a, "item_id": a["key"]} for a in phase.analyze(rows[offset : offset + BATCH_SIZE], config)]
                _write(batch_path, batch)
                record["batches"][key] = _digest(batch)
                _write(path, record)
            annotations.extend(batch)
            on_progress(min(offset + BATCH_SIZE, len(rows)), len(rows))
        else:
            record["status"] = "completed"
    except Exception as exc:  # noqa: BLE001 - analyzer failure cannot invalidate committed conversion
        record.update(status="failed", error=f"{type(exc).__name__}: phase analyzer failed; retry analysis")
    record["updated_at"] = utc_now()
    _write(path, record)
    return _result(record, annotations, len(rows))


def _result(record: dict[str, Any], annotations: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {
        "task": "analyzer.phase",
        "status": record["status"],
        "attempt": record["attempt"],
        "rules_version": phase.RULES_VERSION,
        "completed_batches": len(record["batches"]),
        "done": sum(min(BATCH_SIZE, total - int(offset)) for offset in record["batches"]),
        "total": total,
        "error": record["error"],
        "annotations": annotations,
    }
