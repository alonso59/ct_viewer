"""Cooperative single-host GPU inventory and durable reservations (SEG-07, OPS-16)."""

from __future__ import annotations

import csv
import fcntl
import io
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from plugins.protocol import write_json_atomic


def select_devices(rows: list[dict[str, Any]], pool: list[str], requested: list[str], count: int) -> list[str]:
    if not 1 <= count <= 4:
        raise ValueError("GPU count must be 1..4")
    aliases: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key in (str(row["index"]), str(row["uuid"])):
            if key in aliases:
                raise ValueError("ambiguous GPU inventory")
            aliases[key] = row
    if any(value not in aliases for value in [*pool, *requested]):
        raise ValueError("unknown GPU")
    approved = {str(aliases[value]["uuid"]) for value in pool}
    explicit = [str(aliases[value]["uuid"]) for value in requested]
    if len(explicit) != len(set(explicit)) or not set(explicit) <= approved:
        raise ValueError("duplicate or outside-pool GPU request")

    def idle(row: dict[str, Any]) -> bool:
        return (
            type(row.get("used_mb")) is int
            and 0 <= row["used_mb"] <= 64
            and type(row.get("utilization")) is int
            and 0 <= row["utilization"] <= 5
            and row.get("pids") == []
        )

    if requested:
        chosen = explicit[:count]
        if any(not idle(aliases[value]) for value in chosen):
            raise ValueError("requested GPU is busy or unknown")
    else:
        chosen = [
            str(row["uuid"])
            for row in sorted(rows, key=lambda row: int(row["index"]))
            if row["uuid"] in approved and idle(row)
        ][:count]
    if len(chosen) != count:
        raise ValueError("insufficient available GPUs")
    return chosen


def inventory() -> list[dict[str, Any]]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        raise ValueError("GPU inventory unavailable: nvidia-smi missing")

    def query(fields: str) -> list[list[str]]:
        result = subprocess.run(
            [executable, fields, "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode:
            raise ValueError("GPU inventory unavailable")
        return [[value.strip() for value in row] for row in csv.reader(io.StringIO(result.stdout)) if row]

    rows: list[dict[str, Any]] = []
    try:
        for row in query("--query-gpu=index,uuid,name,memory.total,memory.used,utilization.gpu"):
            index, identity, name, total, used, utilization = row
            if not identity.startswith("GPU-") or min(int(index), int(used), int(utilization)) < 0 or int(total) <= 0:
                raise ValueError("invalid GPU telemetry")
            rows.append(
                {
                    "index": index,
                    "uuid": identity,
                    "name": name,
                    "total_mb": int(total),
                    "used_mb": int(used),
                    "utilization": int(utilization),
                    "pids": [],
                }
            )
        by_uuid = {row["uuid"]: row for row in rows}
        for identity, pid in query("--query-compute-apps=gpu_uuid,pid"):
            if identity not in by_uuid or int(pid) <= 0:
                raise ValueError("unknown GPU context")
            by_uuid[identity]["pids"].append(int(pid))
        if not rows or len(by_uuid) != len(rows):
            raise ValueError("empty or ambiguous inventory")
    except (TypeError, ValueError) as exc:
        raise ValueError("GPU inventory unknown or inconsistent") from exc
    return rows


class Pool:
    """One conservative host-wide active attempt; leases survive process death."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @contextmanager
    def locked(self) -> Iterator[None]:
        if not self.root.is_absolute() or self.root.resolve() != self.root:
            raise ValueError("pool root must be canonical and private")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        owner = self.root.stat()
        if owner.st_uid != os.getuid() or owner.st_mode & 0o077:
            raise ValueError("pool root must be private to this Unix identity")
        descriptor = os.open(self.root / "pool.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_uid != os.getuid()
                or details.st_mode & 0o077
                or details.st_nlink != 1
            ):
                raise ValueError("pool lock must be a private regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def _read(self) -> dict[str, Any] | None:
        try:
            descriptor = os.open(self.root / "lease.json", os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor) as handle:
            value = json.load(handle)
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("attempt"), str)
            or not isinstance(value.get("gpus"), list)
        ):
            raise TypeError("invalid pool lease; manual reconciliation required")
        return value

    def read(self) -> dict[str, Any] | None:
        with self.locked():
            return self._read()

    def reserve(self, record: dict[str, Any], *, claim: Callable[[], bool] | None = None) -> bool:
        with self.locked():
            if self._read() is not None:
                return False
            if claim is not None and not claim():
                return False
            write_json_atomic(self.root / "lease.json", record)
            return True

    def update(self, record: dict[str, Any]) -> None:
        with self.locked():
            previous = self._read()
            if previous is None or previous["attempt"] != record["attempt"]:
                raise ValueError("stale allocation generation")
            write_json_atomic(self.root / "lease.json", record)

    def release(self, attempt: str) -> bool:
        with self.locked():
            previous = self._read()
            if previous is None or previous["attempt"] != attempt:
                return False
            (self.root / "lease.json").unlink()
            return True
