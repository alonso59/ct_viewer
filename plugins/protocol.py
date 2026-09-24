"""Task side of the run protocol (TASKS.md §Protocol, TSK-07). Standard library only.

    job = Job(job_dir)
    job.run_items(fn)          # fn(job, item) -> outputs; per-item failures don't stop the run
    job.finish(versions={...})

`progress.jsonl` lines: `{t: item|log|heartbeat, ...}`; `result.json` is written last, atomically.
Cancel = a `cancel` file in the job dir, checked between items.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROTOCOL = 1
JOB, PROGRESS, RESULT, CANCEL = "job.json", "progress.jsonl", "result.json", "cancel"

Outputs = list[dict[str, Any]]


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class SkipItem(Exception):
    """Raised by an item function: the item is `skipped` (not ready), never `failed` (TSK-04)."""


class Job:
    def __init__(self, job_dir: str | Path) -> None:
        self.dir = Path(job_dir)
        self.spec: dict[str, Any] = json.loads((self.dir / JOB).read_text(encoding="utf-8"))
        if self.spec.get("protocol") != PROTOCOL:
            raise ValueError(f"unsupported protocol {self.spec.get('protocol')!r}")
        self.settings: dict[str, Any] = self.spec.get("settings") or {}
        # Project context the backend adds (phase vocabulary, preset target profile, ANZ-05)
        self.context: dict[str, Any] = self.spec.get("context") or {}
        self.items: list[dict[str, Any]] = self.spec.get("items") or []
        self.rows: list[dict[str, Any]] = self.spec.get("rows") or []
        out = self.spec.get("output_dir")
        self.output_dir: Path | None = Path(out) if out else None
        ds = self.spec.get("dataset_dir")
        self.dataset_dir: Path | None = Path(ds) if ds else None  # append-only (ADR-0014)
        self.skip: set[str] = set((self.spec.get("resume") or {}).get("skip") or [])
        self.mode: str = self.spec.get("mode", "run")  # run | estimate
        self.counts = {"items": 0, "ok": 0, "failed": 0, "skipped": 0}
        self.outputs_manifest: Outputs = []
        self.started_at = utc_now()
        self._fh = (self.dir / PROGRESS).open("a", encoding="utf-8")

    # -- progress --------------------------------------------------------------------------

    def _line(self, obj: dict[str, Any]) -> None:
        self._fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._fh.flush()

    def item(
        self, item_id: str, status: str, outputs: Outputs | None = None, message: str = ""
    ) -> None:
        self.counts[status] = self.counts.get(status, 0) + 1
        self._line(
            {
                "t": "item",
                "item_id": item_id,
                "status": status,
                "outputs": outputs or [],
                "message": message,
            }
        )

    def log(self, message: str, level: str = "info") -> None:
        self._line({"t": "log", "level": level, "message": message})

    def total(self, n: int) -> None:
        """Unit count once known (source tasks discover theirs, e.g. DICOM series)."""
        self._line({"t": "total", "n": int(n)})

    def heartbeat(self) -> None:
        self._line({"t": "heartbeat"})

    def cancelled(self) -> bool:
        return (self.dir / CANCEL).exists()

    def rel(self, name: str) -> Path:
        """A workspace file of this job (tabular outputs), referenced relative to the job dir."""
        return self.dir / name

    # -- driving ---------------------------------------------------------------------------

    def run_items(self, fn: Callable[[Job, dict[str, Any]], Outputs]) -> None:
        """Call `fn` per item (resume skips `ok` items); stops between items on cancel."""
        for it in self.items:
            if self.cancelled():
                break
            iid = str(it["item_id"])
            if iid in self.skip:
                continue
            self.counts["items"] += 1
            try:
                outputs = fn(self, it)
            except SkipItem as exc:
                self.item(iid, "skipped", message=str(exc))
            except Exception as exc:
                self.item(iid, "failed", message=f"{type(exc).__name__}: {exc}")
                self.log(traceback.format_exc(limit=5), "debug")
            else:
                self.item(iid, "ok", outputs)
        self.counts["items"] = max(
            self.counts["items"], sum(self.counts[k] for k in ("ok", "failed", "skipped"))
        )

    def finish(
        self,
        *,
        versions: dict[str, str] | None = None,
        status: str | None = None,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if status is None:
            if self.cancelled():
                status = "cancelled"
            elif self.counts["failed"] and not self.counts["ok"]:
                status = "failed"
            elif self.counts["failed"]:
                status = "completed_with_errors"
            else:
                status = "completed"
        result = {
            "status": status,
            "counts": self.counts,
            "outputs_manifest": self.outputs_manifest,
            "versions": versions or {},
            "started_at": self.started_at,
            "finished_at": utc_now(),
        }
        if error:
            result["error"] = error
        result.update(extra or {})  # e.g. the converter's identity registry, a dry-run estimate
        self._fh.close()
        write_json_atomic(self.dir / RESULT, result)
        return result


def main(run: Callable[[str], int], argv: list[str]) -> int:
    """`python -m plugin <job_dir>` entry for external runtimes."""
    if len(argv) != 2:
        print("usage: <module> <job_dir>")
        return 2
    return run(argv[1])
