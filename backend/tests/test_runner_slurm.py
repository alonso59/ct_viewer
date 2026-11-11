"""OPS-20: the SLURM supervisor against a fake scheduler. No cluster is involved, so GRES syntax,
accounting, shared storage and signal delivery on a real site stay unverified."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from plugins.runner import scheduler, slurm
from plugins.runner.deployment import validate_config
from plugins.runner.supervised import Supervisor

from tests.test_runner_deployment import config
from tests.test_runner_paths import setup

FAKE = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

root = Path(os.environ["FAKE_SLURM"])
tool = Path(sys.argv[0]).name
jobs = {p.stem: json.loads(p.read_text()) for p in sorted(root.glob("*.json"))}
options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
if (root / "down").exists() or (tool == "sacct" and (root / "no-accounting").exists()):
    sys.exit(1)
if tool == "sbatch":
    if "--test-only" in sys.argv:
        if (root / "refuse-profile").exists():
            sys.exit("sbatch: error: Invalid partition name specified")
        print("sbatch: Job 9 to start at 2026-11-12T10:00:00 using 3 processors", file=sys.stderr)
        sys.exit(0)
    if (root / "refuse").exists():
        sys.exit("sbatch: error: invalid account")
    identity = str(100 + len(jobs))
    job = {"name": options["job-name"], "state": "PENDING", "argv": sys.argv[1:], "listed": True}
    (root / f"{identity}.json").write_text(json.dumps(job))
    print(identity + ";cluster")
elif tool == "scancel":
    job = jobs[sys.argv[1]]
    job["state"] = "CANCELLED"
    (root / f"{sys.argv[1]}.json").write_text(json.dumps(job))
else:
    for identity, job in jobs.items():
        if job["name"] == options["name"] and (tool == "sacct" or job["listed"]):
            suffix = " by 1008" if job["state"] == "CANCELLED" else ""
            extra = "|Priority|n01|0:05|1:00" if tool == "squeue" else ""
            print(f"{identity}|{job['state']}{suffix}{extra}")
"""
TASK = (
    "import os, sys; from pathlib import Path; "
    "Path(sys.argv[1], 'seen.json').write_text(__import__('json').dumps("
    "{k: os.environ.get(k) for k in ('HOME', 'CUDA_VISIBLE_DEVICES', 'SLURM_JOB_NAME')}))"
)


class Cluster:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **scheduler: Any) -> None:
        self.root, tools = tmp_path / "scheduler", tmp_path / "tools"
        self.scratch = tmp_path / "scratch"
        for folder in (self.root, tools, self.scratch):
            folder.mkdir()
        for name in ("sbatch", "squeue", "scancel", "sacct"):
            (tools / name).write_text(FAKE)
            (tools / name).chmod(0o700)
        monkeypatch.setenv("PATH", f"{tools}:{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_SLURM", str(self.root))
        monkeypatch.setattr(slurm, "POLL_S", 0.0)
        self.supervisor, self.job, _dataset, self.spec = setup(
            tmp_path, backend="slurm", slurm={"scratch": str(self.scratch), **scheduler}
        )
        self.manifest = {"runtime": {"command": ["{python}", "-c", TASK, self.spec["output_dir"]]}}
        (self.job / "job.json").write_text(json.dumps(self.spec))

    def start(self) -> bool:
        return self.supervisor.start(self.job, self.manifest, self.job.parent, lambda job: True)

    def scheduled(self, identity: str = "100") -> dict[str, Any]:
        value: dict[str, Any] = json.loads((self.root / f"{identity}.json").read_text())
        return value

    def change(self, identity: str = "100", **values: Any) -> None:
        (self.root / f"{identity}.json").write_text(
            json.dumps({**self.scheduled(identity), **values})
        )

    def execute(self, state: str = "COMPLETED") -> None:
        """What the compute node does: run the submitted script inside the allocation."""
        job = self.scheduled()
        environment = {
            "PATH": os.environ["PATH"],
            "SLURM_JOB_NAME": job["name"],
            "CUDA_VISIBLE_DEVICES": "0",
        }
        subprocess.run([job["argv"][-1]], env=environment, check=False, timeout=60)
        self.change(state=state)

    def exit(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads((self.job / "exit.json").read_text())
        return value


def test_a_job_is_submitted_with_the_configured_resources_and_runs_in_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = Cluster(tmp_path, monkeypatch, partition="gpu", account="research")
    assert cluster.start()
    record = cluster.supervisor.record
    assert record is not None and (record["scheduler_job"], record["state"]) == ("100", "queued")
    argv = cluster.scheduled()["argv"]
    for expected in (
        f"--job-name=rw-seg-{record['attempt']}",
        "--cpus-per-task=3",
        "--mem=128M",
        "--time=1",
        "--gres=gpu:1",
        "--partition=gpu",
        "--account=research",
        "--export=NONE",
    ):
        assert expected in argv
    cluster.supervisor.poll()
    assert not (cluster.job / "exit.json").exists()
    cluster.change(state="RUNNING")
    cluster.supervisor.poll()
    assert json.loads((cluster.job / "attempt.json").read_text())["state"] == "running"
    cluster.execute()
    cluster.supervisor.poll()
    assert cluster.exit() | {"at": ""} == {
        "code": 0,
        "at": "",
        "attempt": record["attempt"],
        "cleanup_verified": True,
        "scheduler_state": "COMPLETED",
    }
    seen = json.loads((Path(cluster.spec["output_dir"]) / "seen.json").read_text())
    assert seen["HOME"].startswith(str(cluster.scratch)) and seen["CUDA_VISIBLE_DEVICES"] == "0"
    assert list(cluster.scratch.iterdir()) == []
    assert cluster.supervisor.record is None and cluster.supervisor.pool.read() is None


def test_the_browser_cannot_pick_devices_the_scheduler_assigns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    (cluster.job / "job.json").write_text(
        json.dumps({**cluster.spec, "settings": {"gpu_ids": ["0"]}})
    )
    with pytest.raises(ValueError, match="scheduler assigns GPUs"):
        cluster.start()
    assert not list(cluster.root.glob("*.json")) and cluster.supervisor.pool.read() is None


def test_a_refused_submission_fails_the_job_and_frees_the_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    (cluster.root / "refuse").touch()
    assert cluster.start()
    assert cluster.exit()["code"] == 125 and cluster.exit()["cleanup_verified"] is True
    assert "invalid account" in (cluster.job / "task.log").read_text()
    assert cluster.supervisor.record is None and cluster.supervisor.pool.read() is None


def test_cancel_reaches_a_job_that_is_still_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    assert cluster.start()
    (cluster.job / "cancel").touch()
    cluster.supervisor.poll()
    assert cluster.scheduled()["state"] == "CANCELLED" and not (cluster.job / "exit.json").exists()
    cluster.supervisor.poll()
    assert cluster.exit()["code"] == -15 and cluster.exit()["scheduler_state"] == "CANCELLED"


def test_a_new_runner_adopts_the_running_job_instead_of_submitting_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    assert cluster.start()
    cluster.change(state="RUNNING")
    cluster.supervisor.stop()
    restarted = slurm.supervisor(tmp_path / "deployment.json")
    restarted.verify()
    assert restarted.record is not None and restarted.record["scheduler_job"] == "100"
    assert not restarted.start(cluster.job, cluster.manifest, cluster.job.parent, lambda job: True)
    cluster.execute()
    restarted.poll()
    assert cluster.exit()["code"] == 0 and len(list(cluster.root.glob("*.json"))) == 1


def test_a_lost_submission_answer_is_recovered_by_the_job_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    command = scheduler.command

    def lost(argv: list[str], timeout: float = 15) -> subprocess.CompletedProcess[str]:
        result = command(argv, timeout)
        if argv[0] == "sbatch" and "--test-only" not in argv:
            raise subprocess.TimeoutExpired(argv, timeout)
        return result

    monkeypatch.setattr(scheduler, "command", lost)
    assert cluster.start()
    record = cluster.supervisor.record
    assert record is not None and record["scheduler_job"] == ""
    cluster.supervisor.poll()
    assert (record["scheduler_job"], record["state"]) == ("100", "queued")


@pytest.mark.parametrize("answered", [False, True])
def test_an_unlisted_attempt_waits_before_it_counts_as_never_submitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answered: bool
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    assert cluster.start()
    record = cluster.supervisor.record
    assert record is not None
    (cluster.root / "100.json").unlink()
    if not answered:
        record["scheduler_job"] = ""
    cluster.supervisor.poll()
    assert (
        cluster.supervisor.last_error.startswith("cleanup_pending")
        and not (cluster.job / "exit.json").exists()
    )
    record["submitted"] -= slurm.SUBMISSION_GRACE_S
    cluster.supervisor.poll()
    assert cluster.exit()["scheduler_state"] == ("UNKNOWN" if answered else "NOT_SUBMITTED")
    assert cluster.exit()["code"] == 1


def test_a_silent_scheduler_keeps_the_slot_and_reports_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    assert cluster.start()
    (cluster.root / "down").touch()
    cluster.supervisor.poll()
    assert cluster.supervisor.last_error == "cleanup_pending: scheduler state unavailable"
    assert cluster.supervisor.record is not None and not (cluster.job / "exit.json").exists()


@pytest.mark.parametrize("accounting", [True, False])
def test_a_job_killed_by_the_scheduler_fails_with_its_final_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accounting: bool
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    assert cluster.start()
    record = cluster.supervisor.record
    assert record is not None
    cluster.change(state="TIMEOUT", listed=False)
    if not accounting:
        (cluster.root / "no-accounting").touch()
        record["submitted"] -= slurm.SUBMISSION_GRACE_S
    cluster.supervisor.poll()
    state = "TIMEOUT" if accounting else "UNKNOWN"
    assert (cluster.exit()["code"], cluster.exit()["scheduler_state"]) == (1, state)
    assert f"Scheduler state: {state}" in (cluster.job / "task.log").read_text()


def test_the_allocation_must_expose_a_gpu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    assert cluster.start()
    record = cluster.supervisor.record
    assert record is not None
    monkeypatch.setenv("SLURM_JOB_NAME", f"rw-seg-{record['attempt']}")
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    assert slurm.run(cluster.job, record["attempt"]) == 1
    assert json.loads((cluster.job / "worker-exit.json").read_text())["code"] == 125
    monkeypatch.setenv("SLURM_JOB_NAME", "another-job")
    with pytest.raises(ValueError, match="stale or foreign"):
        slurm.run(cluster.job, record["attempt"])


def test_each_backend_gets_its_own_supervisor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    assert type(cluster.supervisor) is slurm.SlurmSupervisor
    with pytest.raises(ValueError, match="needs another supervisor"):
        Supervisor(tmp_path / "deployment.json")
    other = tmp_path / "other"
    other.mkdir()
    assert type(setup(other)[0]) is Supervisor


def test_runner_refuses_to_start_without_the_scheduler_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    with pytest.raises(ValueError, match="scheduler commands unavailable"):
        cluster.supervisor.verify()


def test_scratch_must_be_an_absolute_path() -> None:
    raw = config("slurm")
    raw["slurm"]["scratch"] = "/local/scratch"
    assert validate_config(raw)["slurm"]["scratch"] == "/local/scratch"
    raw["slurm"]["scratch"] = "$TMPDIR/../x"
    with pytest.raises(ValueError, match="scratch"):
        validate_config(raw)


PROFILES = [
    {
        "id": "small",
        "name": "Small",
        "account": "lab",
        "partition": "gpu",
        "gpus": 1,
        "cpus": 2,
        "memory_mb": 64,
        "seconds": 30,
    },
    {
        "id": "other",
        "name": "Other",
        "account": "lab",
        "partition": "gpu",
        "gpus": 1,
        "cpus": 1,
        "memory_mb": 32,
        "seconds": 30,
    },
]


def with_profiles(cluster: Cluster, profile: str | None) -> None:
    (cluster.supervisor.workspace / scheduler.PROFILES_FILE).write_text(
        json.dumps({"profiles": PROFILES})
    )
    spec = {**cluster.spec, "settings": {**cluster.spec.get("settings", {})}}
    if profile:
        spec["settings"]["compute_profile"] = profile
    (cluster.job / "job.json").write_text(json.dumps(spec))


def test_a_run_uses_the_resources_of_its_compute_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLURM_JOB_ID", "41")
    cluster = Cluster(tmp_path, monkeypatch, gpu_request="gpus")
    with_profiles(cluster, "small")
    assert cluster.start()
    record = cluster.supervisor.record
    assert record is not None and record["profile"]["id"] == "small"
    argv = cluster.scheduled()["argv"]
    assert {
        "--cpus-per-task=2",
        "--mem=64M",
        "--time=1",
        "--gpus=1",
        "--partition=gpu",
        "--account=lab",
    } <= set(argv)
    assert record["environment"]["RW_CPU_WORKERS"] == "2" and record["limits"]["cpus"] == 2
    cluster.supervisor.poll()
    shown = json.loads((cluster.job / "scheduler.json").read_text())
    assert (shown["job_id"], shown["state"], shown["pending_reason"], shown["node"]) == (
        "100",
        "PENDING",
        "Priority",
        "n01",
    )
    assert (shown["elapsed"], shown["time_limit"], shown["profile"]) == ("0:05", "1:00", "Small")
    cluster.execute()
    cluster.supervisor.poll()
    assert json.loads((cluster.job / "scheduler.json").read_text())["state"] == "COMPLETED"


def test_a_run_must_name_one_of_several_profiles_and_a_refused_profile_never_queues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    with_profiles(cluster, None)
    with pytest.raises(ValueError, match="choose a compute profile"):
        cluster.start()
    with_profiles(cluster, "missing")
    with pytest.raises(ValueError, match="choose a compute profile"):
        cluster.start()
    with_profiles(cluster, "small")
    (cluster.root / "refuse-profile").touch()
    with pytest.raises(ValueError, match="Invalid partition"):
        cluster.start()
    assert not list(cluster.root.glob("*.json")) and cluster.supervisor.record is None


def test_the_site_snapshot_is_read_in_the_background_and_lists_profile_verdicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cluster = Cluster(tmp_path, monkeypatch)
    with_profiles(cluster, "small")
    first = cluster.supervisor.scheduler_snapshot()
    assert first["at"] is None and [p["status"] for p in first["profiles"]] == [
        "unchecked",
        "unchecked",
    ]
    cluster.supervisor.reader.join(timeout=30)
    site = cluster.supervisor.scheduler_snapshot()
    assert [(p["id"], p["status"], p["estimated_start"]) for p in site["profiles"]] == [
        ("small", "valid", "2026-11-12T10:00:00"),
        ("other", "valid", "2026-11-12T10:00:00"),
    ]
    assert (
        site["partitions"] is None and site["workspaces"] is None and site["gpu_request"] == "gres"
    )
    (cluster.supervisor.workspace / slurm.CHECK_REQUEST).write_text(json.dumps({"id": "r1"}))
    cluster.supervisor.scheduler_snapshot()
    cluster.supervisor.reader.join(timeout=30)
    assert cluster.supervisor.scheduler_snapshot()["request"] == "r1"
