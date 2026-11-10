"""Scheduler-owned execution: one attempt at a time through sbatch, squeue and scancel.

The scheduler allocates CPUs, memory, time and GPUs, so there is no device selection, sandbox or
user-service cgroup here. An attempt is found again by its unique job name."""

from __future__ import annotations

import json
import os
import re
import resource
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.protocol import utc_now, write_json_atomic
from plugins.runner import gpu, service
from plugins.runner.attempt import on_signal, watch
from plugins.runner.supervised import Supervisor, acknowledge_control, stopping

TERMINAL = {
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "REVOKED",
    "TIMEOUT",
}
# An attempt the scheduler does not list is taken as gone or never submitted only after this long.
SUBMISSION_GRACE_S = 60.0


def job_name(attempt: str) -> str:
    return service.unit_name(attempt).removesuffix(".service")


def states(argv: list[str]) -> dict[str, str] | None:
    """Scheduler job id -> state from `id|state` lines; None when the command gives no answer."""
    try:
        result = service.command(argv, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    rows = [line.split("|") for line in result.stdout.splitlines() if "|" in line]
    return {identity.strip(): state.split()[0] for identity, state in rows if state.strip()}


def queued(name: str) -> dict[str, str] | None:
    return states(["squeue", "--noheader", f"--user={os.getuid()}", f"--name={name}", "--format=%i|%T"])


def accounted(name: str) -> dict[str, str] | None:
    return states(
        [
            "sacct",
            "--noheader",
            "--parsable2",
            "--allocations",
            "--starttime=now-30days",
            f"--user={os.getuid()}",
            f"--name={name}",
            "--format=JobID,State",
        ]
    )


class SlurmSupervisor(Supervisor):
    backends = ("slurm",)

    def verify(self) -> dict[str, Any]:
        missing = [tool for tool in ("sbatch", "squeue", "scancel") if shutil.which(tool) is None]
        if missing:
            raise ValueError("scheduler commands unavailable: " + ", ".join(missing))
        self.verify_allocation_policy()
        self.recover()
        return {"ready": True, "blockers": []}

    def diagnostics(self, *, verify_host: bool = False) -> dict[str, Any]:
        report = self.verify() if verify_host else {"ready": False, "blockers": ["effective_checks_not_run"]}
        return {
            **report,
            "backend": "slurm",
            "limits": self.config["limits"],
            "gpu_inventory": [],
            "limitations": [
                "the scheduler allocates and isolates resources",
                "no sandbox on compute nodes",
                "one attempt at a time",
                "not accepted on a real cluster",
            ],
        }

    def inventory_snapshot(self) -> dict[str, Any]:
        return {"at": utc_now(), "error": None, "devices": []}

    def check_devices(self) -> list[str]:
        return [str(index) for index in range(self.config["limits"]["gpus"])]

    def submission(self, record: dict[str, Any], job: Path) -> list[str]:
        limits, site = self.config["limits"], self.config.get("slurm", {})
        script = job / "scheduler.sh"
        worker = shlex.join([str(self.python), "-I", __file__, str(job), record["attempt"]])
        script.write_text(f"#!/bin/sh\nexec {worker}\n")
        script.chmod(0o700)
        return [
            "sbatch",
            "--parsable",
            "--export=NONE",
            f"--job-name={job_name(record['attempt'])}",
            f"--chdir={job}",
            f"--output={job / 'scheduler.log'}",
            "--open-mode=append",
            "--nodes=1",
            "--ntasks=1",
            f"--cpus-per-task={limits['cpus']}",
            f"--mem={limits['memory_mb']}M",
            f"--time={-(-limits['seconds'] // 60)}",
            f"--gres=gpu:{record['gpu_count']}",
            "--signal=B:TERM@60",
            *[f"--{name}={site[name]}" for name in ("partition", "account", "qos", "constraint") if name in site],
            str(script),
        ]

    def start(self, job: Path, manifest: dict[str, Any], plugin: Path, claim: Any) -> bool:
        if self.record is not None or stopping(job):
            return False
        self.verify_allocation_policy()
        spec = json.loads((job / "job.json").read_text())
        self.admit(job, manifest, plugin)
        if (spec.get("settings") or {}).get("gpu_ids"):
            raise ValueError("the scheduler assigns GPUs; leave the GPU selection empty")
        skip = (spec.get("resume") or {}).get("skip", [])
        pending = sum(item.get("item_id") not in skip for item in spec.get("items", []))
        record = self.prepare(job, manifest, plugin, spec, [])
        del record["environment"]["CUDA_VISIBLE_DEVICES"]
        record.update(
            state="submitting",
            scheduler_job="",
            submitted=time.time(),
            gpu_count=min(max(1, pending), gpu.MAX_GPUS, self.config["limits"]["gpus"]),
            scratch=self.config.get("slurm", {}).get("scratch", ""),
            write_roots=[str(job), record["write_roots"][1]],
            devices=[],
            native_commands=[],
        )
        if not self.pool.reserve(record, claim=lambda: claim(job)):
            self.last_error = "waiting for the participating host allocation"
            return False
        self.record = record
        write_json_atomic(job / "attempt.json", record)
        if stopping(job):
            self.finish(-signal.SIGTERM, "NOT_SUBMITTED")
            return True
        try:
            result = service.command(self.submission(record, job), timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.last_error = f"cleanup_pending: submission unknown: {exc}"
            return True
        identity = result.stdout.strip().split(";")[0]
        if result.returncode:
            with (job / "task.log").open("a") as handle:
                handle.write(f"Submission refused: {result.stderr.strip()[-1500:]}\n")
            self.finish(125, "NOT_SUBMITTED")
        elif re.fullmatch(r"\d+", identity):
            self.observed(identity, "queued")
        else:
            self.last_error = "cleanup_pending: submission answer unreadable"
        return True

    def observed(self, identity: str, state: str) -> None:
        record = self.record
        assert record is not None
        if (record["scheduler_job"], record["state"]) != (identity, state):
            record.update(scheduler_job=identity, state=state)
            self.pool.update(record)
            write_json_atomic(Path(record["job"]) / "attempt.json", record)

    def finish(self, code: int, state: str) -> None:
        record = self.record
        assert record is not None
        job = Path(record["job"])
        write_json_atomic(
            job / "exit.json",
            {
                "code": code,
                "at": utc_now(),
                "attempt": record["attempt"],
                "cleanup_verified": True,
                "scheduler_state": state,
            },
        )
        record["state"] = "finished"
        write_json_atomic(job / "attempt.json", record)
        if not self.pool.release(record["attempt"]):
            raise ValueError("allocation generation changed during cleanup")
        acknowledge_control(job, record["attempt"])
        self.record = None
        self.last_error = ""

    def poll(self) -> None:
        record = self.record
        if record is None:
            return
        self._validate_record(record)
        job, name = Path(record["job"]), job_name(record["attempt"])
        listed = queued(name)
        if listed is None:
            self.last_error = "cleanup_pending: scheduler state unavailable"
            return
        if not listed:
            # Gone from the queue: accounting, where the site has it, names the final state.
            listed = accounted(name) or {}
        if len(listed) > 1 or (listed and record["scheduler_job"] not in ("", *listed)):
            self.last_error = "cleanup_pending: attempt identity is ambiguous"
            return
        state = next(iter(listed.values()), "UNKNOWN")
        if listed and state not in TERMINAL:
            identity = next(iter(listed))
            self.observed(identity, "running" if state == "RUNNING" else "queued")
            self.last_error = ""
            if (job / "cancel").exists():
                try:
                    service.command(["scancel", identity])
                except (OSError, subprocess.TimeoutExpired) as exc:
                    self.last_error = f"cancel not delivered yet: {exc}"
            return
        try:
            outcome = json.loads((job / "worker-exit.json").read_text())
            code = outcome["code"] if outcome["attempt"] == record["attempt"] else 1
        except (OSError, ValueError, KeyError):
            if not listed:
                if time.time() - record["submitted"] < SUBMISSION_GRACE_S:
                    self.last_error = "cleanup_pending: the scheduler does not list the attempt yet"
                    return
                if not record["scheduler_job"]:
                    state = "NOT_SUBMITTED"
            code = -signal.SIGTERM if state == "CANCELLED" or (job / "cancel").exists() else 1
        if state != "COMPLETED":
            with (job / "task.log").open("a") as handle:
                handle.write(f"Scheduler state: {state}\n")
        self.finish(code, state)

    def stop(self) -> None:
        """A scheduler job outlives the runner; the next runner reconciles it by name."""


def supervisor(path: Path, workspace: Path | None = None) -> Supervisor:
    """The supervisor of the configured backend."""
    raw = json.loads(path.read_text())
    scheduled = isinstance(raw, dict) and raw.get("backend") == "slurm"
    return (SlurmSupervisor if scheduled else Supervisor)(path, workspace)


def run(job: Path, attempt: str) -> int:
    """The attempt inside its allocation: private scratch, bounded log, cancel and signals."""
    spec = json.loads((job / "attempt.json").read_text())
    if (
        spec["attempt"] != attempt
        or spec["uid"] != os.getuid()
        or os.environ.get("SLURM_JOB_NAME") != job_name(attempt)
    ):
        raise ValueError("stale or foreign attempt")
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if not visible:
        with (job / "task.log").open("a") as handle:
            handle.write("Launch blocked: the allocation exposes no GPU\n")
        write_json_atomic(job / "worker-exit.json", {"attempt": attempt, "code": 125})
        return 1
    scratch = spec["scratch"] or os.environ.get("SLURM_TMPDIR") or os.environ.get("TMPDIR") or "/tmp"
    runtime = Path(tempfile.mkdtemp(prefix=f"rw-{attempt}-", dir=scratch))
    try:
        for name in ("home", "tmp", "cache"):
            (runtime / name).mkdir()
        env = {
            **spec["environment"],
            "CUDA_VISIBLE_DEVICES": visible,
            "HOME": str(runtime / "home"),
            "TMPDIR": str(runtime / "tmp"),
            "XDG_CACHE_HOME": str(runtime / "cache"),
            "TORCH_HOME": str(runtime / "cache/torch"),
            "TORCHINDUCTOR_CACHE_DIR": str(runtime / "cache/inductor"),
        }
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        process = subprocess.Popen(
            spec["command"],
            cwd=spec["cwd"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            bufsize=0,
        )
        code = watch(process, job, spec["write_roots"])
        write_json_atomic(job / "worker-exit.json", {"attempt": attempt, "code": code})
        return 0 if code == 0 else 1
    finally:
        shutil.rmtree(runtime, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1]), sys.argv[2]))
