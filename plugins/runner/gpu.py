"""Cooperative single-host GPU inventory and durable reservations."""

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

RESOURCE_POLICY = "dicom-resources.json"
MIN_FREE_MB = 16 * 1024


def available(row: dict[str, Any], minimum_mb: int = MIN_FREE_MB) -> bool:
    return (
        type(row.get("used_mb")) is int
        and type(row.get("total_mb")) is int
        and 0 <= row["used_mb"] <= row["total_mb"]
        and row["total_mb"] - row["used_mb"] >= minimum_mb
    )


def select_devices(
    rows: list[dict[str, Any]],
    pool: list[str],
    requested: list[str],
    count: int,
    minimum_mb: int = MIN_FREE_MB,
) -> list[str]:
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

    if requested:
        chosen = explicit[:count]
        if any(not available(aliases[value], minimum_mb) for value in chosen):
            raise ValueError(f"requested GPU needs at least {minimum_mb} MiB free; memory is insufficient or unknown")
    else:
        chosen = [
            str(row["uuid"])
            for row in sorted(rows, key=lambda row: int(row["index"]))
            if row["uuid"] in approved and available(row, minimum_mb)
        ][:count]
    if len(chosen) != count:
        raise ValueError("insufficient available GPUs")
    return chosen


def device_path(identity: str) -> Path:
    for info in Path("/proc/driver/nvidia/gpus").glob("*/information"):
        fields = {
            key.strip(): value.strip()
            for line in info.read_text().splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
        }
        if fields.get("GPU UUID") != identity:
            continue
        minor = fields.get("Device Minor", "")
        if not minor.isascii() or not minor.isdecimal():
            raise ValueError("GPU device minor is unavailable")
        path = Path(f"/dev/nvidia{int(minor)}")
        node = path.stat()
        if not stat.S_ISCHR(node.st_mode) or os.minor(node.st_rdev) != int(minor):
            raise ValueError("GPU device node does not match driver metadata")
        return path
    raise ValueError("GPU device mapping is unavailable")


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
    def locked(self, *, blocking: bool = True) -> Iterator[None]:
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
            fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
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

    def identity(self) -> dict[str, int]:
        with self.locked():
            details = self.root.stat()
            return {"device": details.st_dev, "inode": details.st_ino}

    def _sync(self) -> None:
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def reserve(self, record: dict[str, Any], *, claim: Callable[[], bool] | None = None) -> bool:
        with self.locked():
            if self._read() is not None:
                return False
            if claim is not None and not claim():
                return False
            write_json_atomic(self.root / "lease.json", record)
            self._sync()
            return True

    def update(self, record: dict[str, Any]) -> None:
        with self.locked():
            previous = self._read()
            if previous is None or previous["attempt"] != record["attempt"]:
                raise ValueError("stale allocation generation")
            write_json_atomic(self.root / "lease.json", record)
            self._sync()

    def release(self, attempt: str) -> bool:
        with self.locked():
            previous = self._read()
            if previous is None or previous["attempt"] != attempt:
                return False
            (self.root / "lease.json").unlink()
            self._sync()
            return True
