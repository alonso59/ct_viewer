"""ADR-0055 §7-§9 against fake scheduler tools: discovery, profile validation, clean environment.
No cluster is involved; the real tools' output formats stay unverified (OPS-20)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from plugins.runner import scheduler

TOOLS = {
    "sinfo": "gpu_short*|up|8:00:00|gpu:a100:4(S:0-1)\ngpu_short*|up|8:00:00|gpu:a40:8\n"
    "cpu_long|up|7-00:00:00|(null)\nold|down|infinite|(null)\n",
    "sshare": "lab\nlab\nteaching\n",
    "ws_list": "id: scans\n     workspace directory  : /lustre/scratch/u-scans\n"
    "     remaining time       : 29 days 23 hours\n"
    "     expiration date      : Thu Dec 10 12:00:00 2026\n"
    "     filesystem name      : scratch\n     available extensions : 3\n",
}
CONFIG: dict[str, Any] = {
    "limits": {"cpus": 8, "memory_mb": 32768, "tasks": 64, "seconds": 86400, "gpus": 2},
    "slurm": {"gpu_request": "gpus", "partitions": ["gpu_short", "cpu_long"]},
}
PROFILE = {
    "id": "a100",
    "name": "One A100",
    "account": "lab",
    "partition": "gpu_short",
    "gpus": 1,
    "cpus": 8,
    "memory_mb": 16384,
    "seconds": 28800,
}


@pytest.fixture
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "tools"
    folder.mkdir()
    for name, text in TOOLS.items():
        (folder / name).write_text(f"#!/bin/sh\ncat <<'EOF'\n{text}EOF\n")
    (folder / "sbatch").write_text(
        '#!/bin/sh\nenv > "$SEEN"\necho "$@" > "$SEEN.argv"\n[ -e "$SEEN.refuse" ] && '
        '{ echo "sbatch: error: Invalid account" >&2; exit 1; }\n'
        'echo "sbatch: Job 77 to start at 2026-11-12T10:00:00 using 8 processors on nodes n1" >&2\n'
    )
    for tool in folder.iterdir():
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}:/usr/bin:/bin")
    monkeypatch.setenv("SEEN", str(tmp_path / "seen"))
    return tmp_path


def test_durations_are_read_and_unlimited_stays_unknown() -> None:
    assert scheduler.seconds("30") == 1800
    assert scheduler.seconds("8:00:00") == 28800
    assert scheduler.seconds("7-00:00:00") == 604800
    assert scheduler.seconds("1-12") == 129600
    assert scheduler.seconds("infinite") is None


def test_discovery_reports_partitions_gpu_types_and_accounts(tools: Path) -> None:
    found = scheduler.discover()
    assert found["error"] is None and found["accounts"] == ["lab", "teaching"]
    by_name = {entry["name"]: entry for entry in found["partitions"]}
    assert by_name["gpu_short"] == {
        "name": "gpu_short",
        "up": True,
        "max_seconds": 28800,
        "gpu_types": ["a100", "a40"],
        "gpus": True,
    }
    assert by_name["cpu_long"]["max_seconds"] == 604800 and not by_name["cpu_long"]["gpus"]
    assert by_name["old"]["max_seconds"] is None and not by_name["old"]["up"]


def test_a_silent_scheduler_is_unknown_not_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    found = scheduler.discover()
    assert found["partitions"] is None and found["accounts"] is None and found["error"]
    assert scheduler.workspaces() is None
    verdict = scheduler.check_profile(PROFILE, CONFIG, found)
    assert verdict["status"] == "unchecked" and verdict["estimated_start"] is None


def test_a_valid_profile_is_tested_by_the_scheduler_in_a_clean_environment(
    tools: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLURM_JOB_ID", "41")
    monkeypatch.setenv("SBATCH_PARTITION", "inherited")
    verdict = scheduler.check_profile(PROFILE, CONFIG, scheduler.discover())
    assert (verdict["status"], verdict["estimated_start"]) == ("valid", "2026-11-12T10:00:00")
    argv = (tools / "seen.argv").read_text().split()
    assert {
        "--test-only",
        "--export=NONE",
        "--gpus=1",
        "--partition=gpu_short",
        "--account=lab",
    } <= set(argv)
    assert "--time=480" in argv and "--mem=16384M" in argv
    inherited = [
        line
        for line in (tools / "seen").read_text().splitlines()
        if line.startswith(("SLURM_", "SBATCH_"))
    ]
    assert inherited == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"partition": "old"}, "not allowed by the operator"),
        ({"partition": "cpu_long", "seconds": 86400 * 8}, "seconds must be"),
        ({"seconds": 86400}, "exceeds the partition's limit"),
        ({"account": "other"}, "not one of yours"),
        ({"gpus": 3}, "gpus must be 1..2"),
        ({"partition": "gpu --wrap=id"}, "invalid partition"),
        ({"id": "../x"}, "invalid profile id"),
    ],
)
def test_a_profile_outside_the_limits_or_the_site_is_rejected_without_asking(
    tools: Path, change: dict[str, Any], reason: str
) -> None:
    verdict = scheduler.check_profile({**PROFILE, **change}, CONFIG, scheduler.discover())
    assert verdict["status"] == "rejected" and reason in verdict["reason"]
    assert not (tools / "seen.argv").exists()


def test_the_scheduler_s_refusal_is_reported(tools: Path) -> None:
    (tools / "seen.refuse").touch()
    verdict = scheduler.check_profile(PROFILE, CONFIG, scheduler.discover())
    assert verdict["status"] == "rejected" and "Invalid account" in verdict["reason"]


def test_an_empty_account_or_partition_means_the_operator_s_single_value(tools: Path) -> None:
    single = {**CONFIG, "slurm": {"account": "lab", "partition": "gpu_short"}}
    profile = {**PROFILE, "account": None, "partition": None}
    assert scheduler.static_problem(profile, single) == ""
    assert {"--account=lab", "--partition=gpu_short"} <= set(
        scheduler.resources(profile, single, 1)
    )
    assert (
        "choose a partition: the operator allows gpu_short, cpu_long"
        in scheduler.static_problem(profile, CONFIG)
    )
    assert scheduler.static_problem({**profile, "partition": "gpu_short"}, CONFIG) == ""


def test_without_user_profiles_the_operator_file_is_the_one_profile(tmp_path: Path) -> None:
    config = {**CONFIG, "slurm": {"partition": "gpu", "account": "lab"}}
    (profile,) = scheduler.load_profiles(tmp_path, config)
    assert (profile["id"], profile["partition"], profile["gpus"]) == ("default", "gpu", 2)
    assert scheduler.static_problem(profile, config) == ""
    assert "--gres=gpu:1" in scheduler.resources(profile, config, 1)


def test_workspaces_are_read_from_the_site_tool(tools: Path) -> None:
    listed = scheduler.workspaces()
    assert listed is not None and listed["error"] is None
    (item,) = listed["items"]
    assert (item["name"], item["path"], item["filesystem"], item["extensions"]) == (
        "scans",
        "/lustre/scratch/u-scans",
        "scratch",
        3,
    )
    assert item["expires"].startswith("2026-12-10T12:00:00")
    assert os.environ["PATH"].startswith(str(tools))
