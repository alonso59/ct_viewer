"""BE-16: a DICOM worker participates in the runner's conservative host allocation."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from app.config import Settings
from app.core.fsio import atomic_write_json
from app.tasks.dicom_execution import attempt_cleaned


class HostAllocation:
    def __init__(self, settings: Settings, job: Path, attempt: int) -> None:
        from plugins.runner.gpu import Pool

        self.settings, self.job, self.attempt = settings, job, attempt
        self.pool = Pool(settings.allocation_root)
        self.generation = "dicom-" + hashlib.sha256(f"{job}:{attempt}".encode()).hexdigest()[:32]
        self.workspace_identity = self._workspace_identity()
        self.blocked_reason = "host_allocation"

    def _workspace_identity(self) -> dict[str, int]:
        details = self.settings.workspace_root.stat()
        return {"device": details.st_dev, "inode": details.st_ino}

    def _record(self) -> dict[str, Any]:
        return {
            "owner": "dicom",
            "owner_version": 1,
            "attempt": self.generation,
            "gpus": [],
            "workspace": str(self.settings.workspace_root),
            "workspace_identity": self.workspace_identity,
            "job": str(self.job),
            "job_attempt": self.attempt,
            "namespace": os.readlink("/proc/self/ns/pid"),
            "limits": self.settings.dicom_limits,
        }

    def _recoverable(self, record: dict[str, Any]) -> bool:
        return bool(
            record.get("owner") == "dicom"
            and record.get("owner_version") == 1
            and record.get("workspace_identity") == self.workspace_identity
            and record.get("namespace") == os.readlink("/proc/self/ns/pid")
            and record.get("workspace") == str(self.settings.workspace_root)
            and attempt_cleaned(Path(record["job"]), int(record["job_attempt"]))
        )

    def acquire(self) -> bool:
        from app.tasks.registry import runners

        identity = (
            {"device": self.pool.root.stat().st_dev, "inode": self.pool.root.stat().st_ino}
            if self.pool.root.exists()
            else None
        )
        if any(
            r.fresh and (r.execution or {}).get("allocation") != identity
            for r in runners(self.settings.workspace_root / "queue")
        ):
            self.blocked_reason = "runner_policy_mismatch"
            return False
        try:
            with self.pool.locked(blocking=False):
                previous = self.pool._read()
                if previous is not None and not self._recoverable(previous):
                    self.blocked_reason = "host_allocation"
                    return False
                atomic_write_json(self.pool.root / "lease.json", self._record())
                return True
        except BlockingIOError:
            return False

    def release(self) -> bool:
        try:
            with self.pool.locked(blocking=False):
                previous = self.pool._read()
                if previous is None or previous["attempt"] != self.generation:
                    return False
                if not attempt_cleaned(self.job, self.attempt):
                    return False
                (self.pool.root / "lease.json").unlink()
                self.pool._sync()
                return True
        except BlockingIOError:
            return False
