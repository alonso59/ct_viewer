"""Scheduler-owned execution: one attempt at a time through sbatch, squeue and scancel.

The scheduler allocates CPUs, memory, time and GPUs, so there is no device selection, sandbox or
user-service cgroup here. An attempt is found again by its unique job name. Its resources are those
of a compute profile, checked against the scheduler again right before the submission."""

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
import threading
import time
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.protocol import utc_now, write_json_atomic
from plugins.runner import scheduler, service
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
SUBMISSION_GRACE_S = 300.0
# The scheduler is asked about a running attempt, and about the site, no more often than this.
POLL_S = 10.0
SITE_REFRESH_S = 300.0
VERDICT_FRESH_S = 60.0
CHECK_REQUEST = "compute-check.json"


def job_name(attempt: str) -> str:
    return service.unit_name(attempt).removesuffix(".service")


def states(argv: list[str]) -> dict[str, str] | None:
    """Scheduler job id -> state from `id|state` lines; None when the command gives no answer."""
    try:
        result = scheduler.command(argv)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    rows = [line.split("|") for line in result.stdout.splitlines() if "|" in line]
    return {identity.strip(): state.split()[0] for identity, state in rows if state.strip()}


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
    backends: ClassVar[tuple[str, ...]] = ("slurm",)
    # the job keeps running after logout; the scheduler, not this runner, isolates devices
    capabilities: ClassVar[dict[str, bool]] = {
        "write_network_confinement": False,
        "device_exclusivity": False,
        "logout_persistence": True,
    }

    def __init__(self, path: Path, workspace: Path | None = None) -> None:
        super().__init__(path, workspace)
        self.site: dict[str, Any] | None = None
        self.site_key: tuple[Any, ...] = ()
        self.site_read = self.polled = 0.0
        self.reader: threading.Thread | None = None
        self.shown: dict[str, Any] = {}

    def scheduler_snapshot(self) -> dict[str, Any]:
        """Partitions, accounts, workspaces and every profile's verdict, as last read.

        Reading happens in a thread, so a slow scheduler never delays the heartbeat. Profiles are
        tested when they change or when the app asks; the site is read again every few minutes."""
        try:
            request = json.loads((self.workspace / CHECK_REQUEST).read_text()).get("id")
        except (OSError, ValueError, AttributeError):
            request = None
        profiles = scheduler.load_profiles(self.workspace, self.config)
        key = (json.dumps(profiles, sort_keys=True), request)
        due = self.site is None or key != self.site_key or time.monotonic() - self.site_read > SITE_REFRESH_S
        if due and (self.reader is None or not self.reader.is_alive()):
            self.reader = threading.Thread(target=self.read_site, args=(profiles, request, key), daemon=True)
            self.reader.start()
        return self.site or {
            "at": None,
            "error": "the scheduler has not been read yet",
            "partitions": None,
            "accounts": None,
            "request": None,
            "gpu_request": self.config.get("slurm", {}).get("gpu_request", "gres"),
            "profiles": [{**p, "status": "unchecked", "reason": "", "estimated_start": None} for p in profiles],
            "workspaces": None,
        }

    def read_site(self, profiles: list[dict[str, Any]], request: Any, key: tuple[Any, ...]) -> None:
        found = scheduler.discover()
        verdicts = (self.site or {}).get("profiles") if key == self.site_key else None
        site = {
            **found,
            "request": request,
            "gpu_request": self.config.get("slurm", {}).get("gpu_request", "gres"),
            "profiles": verdicts
            or [{**profile, **scheduler.check_profile(profile, self.config, found)} for profile in profiles],
            "workspaces": scheduler.workspaces(),
        }
        self.site, self.site_key, self.site_read = site, key, time.monotonic()

    def profile_for(self, settings: dict[str, Any]) -> dict[str, Any] | None:
        """The run's profile with a fresh verdict; None while the scheduler does not answer."""
        profiles = scheduler.load_profiles(self.workspace, self.config)
        wanted = settings.get("compute_profile")
        if wanted is None and len(profiles) == 1:
            wanted = profiles[0]["id"]
        profile = next((p for p in profiles if p.get("id") == wanted), None)
        if profile is None:
            raise ValueError("choose a compute profile for this run")
        known = next((p for p in (self.site or {}).get("profiles", []) if p.get("id") == wanted), None)
        fresh = known is not None and time.monotonic() - self.site_read < VERDICT_FRESH_S
        if known is None or not fresh or {**known, **profile} != known:
            known = {**profile, **scheduler.check_profile(profile, self.config, self.site or {})}
        if known["status"] == "rejected":
            raise ValueError(f"compute profile {profile['name']!r} was refused: {known['reason']}")
        return profile if known["status"] == "valid" else None

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
            *scheduler.resources(record["profile"], self.config, record["gpu_count"]),
            "--signal=B:TERM@60",
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
        profile = self.profile_for(spec.get("settings") or {})
        if profile is None:
            self.last_error = "waiting: the scheduler did not answer the profile check"
            return False
        skip = (spec.get("resume") or {}).get("skip", [])
        pending = sum(item.get("item_id") not in skip for item in spec.get("items", []))
        record = self.prepare(job, manifest, plugin, spec, [])
        expiring = scheduler.expiry_problem(Path(spec["output_dir"]).resolve(), profile["seconds"])
        if expiring:
            raise ValueError(expiring)
        del record["environment"]["CUDA_VISIBLE_DEVICES"]
        record["environment"]["RW_CPU_WORKERS"] = str(profile["cpus"])
        record["limits"] = {**record["limits"], **{name: profile[name] for name in ("cpus", "memory_mb", "seconds")}}
        record.update(
            state="submitting",
            scheduler_job="",
            submitted=time.time(),
            profile=profile,
            gpu_count=min(max(1, pending), profile["gpus"]),
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
            result = scheduler.command(self.submission(record, job), timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.last_error = f"cleanup_pending: submission unknown: {exc}"
            return True
        finally:
            # The wait for a job the scheduler does not list yet starts when the submission ended.
            record["submitted"] = time.time()
            write_json_atomic(job / "attempt.json", record)
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
        if record["scheduler_job"]:
            self.show(job, {**self.shown, "job_id": record["scheduler_job"], "state": state, "pending_reason": None})
            self.show(job, {**self.shown, **scheduler.accounting(record["scheduler_job"])})
        record["state"] = "finished"
        write_json_atomic(job / "attempt.json", record)
        if not self.pool.release(record["attempt"]):
            raise ValueError("allocation generation changed during cleanup")
        acknowledge_control(job, record["attempt"])
        self.record = None
        self.last_error = ""

    def show(self, job: Path, status: dict[str, Any]) -> None:
        """What the scheduler says about the attempt, for the app to display."""
        if status != self.shown:
            self.shown = status
            write_json_atomic(job / "scheduler.json", {**status, "at": utc_now()})

    def poll(self) -> None:
        record = self.record
        if record is None or time.monotonic() - self.polled < POLL_S:
            return
        self.polled = time.monotonic()
        self._validate_record(record)
        job, name = Path(record["job"]), job_name(record["attempt"])
        details = scheduler.job_status(name)
        if details is None:
            self.last_error = "cleanup_pending: scheduler state unavailable"
            return
        listed = {identity: row["state"] for identity, row in details.items()}
        if not listed:
            # Gone from the queue: accounting, where the site has it, names the final state.
            listed = accounted(name) or {}
        if len(listed) > 1 or (listed and record["scheduler_job"] not in ("", *listed)):
            self.last_error = "cleanup_pending: attempt identity is ambiguous"
            return
        state = next(iter(listed.values()), "UNKNOWN")
        if listed and state not in TERMINAL:
            identity = next(iter(listed))
            if identity in details:
                self.show(job, {**details[identity], "profile": (record.get("profile") or {}).get("name")})
            self.observed(identity, "running" if state == "RUNNING" else "queued")
            self.last_error = ""
            if (job / "cancel").exists():
                try:
                    scheduler.command(["scancel", identity])
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
                    # A submission accepted late must not run unowned.
                    try:
                        scheduler.command(["scancel", f"--name={name}", f"--user={os.getuid()}"])
                    except (OSError, subprocess.TimeoutExpired):
                        pass
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
