"""What the scheduler reports and accepts: partitions, accounts, compute profiles, job status.

Nothing here knows a site: every name comes from the scheduler's own answers or the operator file.
A value the scheduler does not give stays `None`; it is never guessed."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from plugins.protocol import utc_now
from plugins.runner import gpu

NAME = r"[A-Za-z0-9][A-Za-z0-9_.:-]*"
PROFILE_ID = r"[a-z0-9][a-z0-9-]{0,39}"
PROFILES_FILE = "compute-profiles.json"
MAX_PROFILES = 8
MAX_PROFILES_BYTES = 65536
# Variables of an enclosing allocation would make a child submission inherit its job context, and
# the format variables would change the output read here. The site's configuration path stays.
INHERITED = ("SLURM_", "SBATCH_", "SQUEUE_", "SACCT_", "SINFO_", "SRUN_", "SALLOC_")
KEPT = ("SLURM_CONF",)


def command(argv: list[str], timeout: float = 15) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key in KEPT or not key.startswith(INHERITED)}
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout, check=False)


def answer(argv: list[str], timeout: float = 15) -> str | None:
    """Standard output of a query; None when the tool is missing, fails or does not answer."""
    if shutil.which(argv[0]) is None:
        return None
    try:
        result = command(argv, timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None if result.returncode else result.stdout


def seconds(text: str) -> int | None:
    """A scheduler duration (`MM`, `MM:SS`, `HH:MM:SS`, `D-HH[:MM[:SS]]`); None when unlimited or unreadable."""
    match = re.fullmatch(r"(?:(\d+)-)?(\d+)(?::(\d+))?(?::(\d+))?", text.strip())
    if match is None:
        return None
    days, first, second, third = (None if part is None else int(part) for part in match.groups())
    if days is not None:
        return ((days * 24 + (first or 0)) * 60 + (second or 0)) * 60 + (third or 0)
    if third is not None:
        return ((first or 0) * 60 + (second or 0)) * 60 + third
    if second is not None:
        return (first or 0) * 60 + second
    return (first or 0) * 60


def discover() -> dict[str, Any]:
    """Partitions and the user's accounts as the scheduler reports them now."""
    found: dict[str, Any] = {"at": utc_now(), "error": None, "partitions": None, "accounts": None}
    listed = answer(["sinfo", "--noheader", "--format=%R|%a|%l|%G"])
    if listed is None:
        found["error"] = "the scheduler did not list its partitions"
    else:
        partitions: dict[str, dict[str, Any]] = {}
        for line in listed.splitlines():
            parts = [part.strip() for part in line.split("|")]
            parts[0] = parts[0].rstrip("*")  # some formats mark the default partition
            if len(parts) != 4 or not re.fullmatch(NAME, parts[0]):
                continue
            entry = partitions.setdefault(
                parts[0], {"name": parts[0], "up": False, "max_seconds": None, "gpu_types": [], "gpus": False}
            )
            entry["up"] = entry["up"] or parts[1] == "up"
            entry["max_seconds"] = seconds(parts[2])
            entry["gpus"] = entry["gpus"] or "gpu" in parts[3]
            for kind in re.findall(r"gpu:([A-Za-z][A-Za-z0-9_.-]*):\d+", parts[3]):
                if kind not in entry["gpu_types"]:
                    entry["gpu_types"].append(kind)
        found["partitions"] = sorted(partitions.values(), key=lambda entry: entry["name"])
    associations = answer(["sshare", "-U", "--noheader", "--parsable2", "--format=Account"])
    if associations is None:
        associations = answer(
            ["sacctmgr", "--noheader", "--parsable2", "show", "assoc", f"user={os.getuid()}", "format=account"]
        )
    if associations is not None:
        found["accounts"] = sorted(
            {line.strip() for line in associations.splitlines() if re.fullmatch(NAME, line.strip())}
        )
    return found


def workspaces(timeout: float = 15) -> dict[str, Any] | None:
    """Managed workspaces `ws_list` reports; None where the site has no such tool."""
    if shutil.which("ws_list") is None:
        return None
    listed = answer(["ws_list"], timeout)
    if listed is None:
        return {"at": utc_now(), "error": "ws_list did not answer", "items": []}
    items: list[dict[str, Any]] = []
    for line in listed.splitlines():
        key, found, value = (part.strip() for part in line.partition(":"))
        if not found:
            continue
        if key.lower() == "id":
            items.append({"name": value, "path": None, "filesystem": None, "expires": None, "extensions": None})
        elif items and key.lower() == "workspace directory":
            items[-1]["path"] = value
        elif items and key.lower() == "filesystem name":
            items[-1]["filesystem"] = value
        elif items and key.lower() == "available extensions" and value.isdigit():
            items[-1]["extensions"] = int(value)
        elif items and key.lower() == "expiration date":
            try:
                moment = datetime.strptime(value, "%a %b %d %H:%M:%S %Y").astimezone()
                items[-1]["expires"] = moment.isoformat()
            except ValueError:
                pass
    return {"at": utc_now(), "error": None, "items": [item for item in items if item["path"]]}


def expiry_problem(output: Path, seconds_needed: int) -> str:
    """Why a run of this length cannot write to `output`: its workspace, read now, ends first."""
    for item in (workspaces(timeout=5) or {}).get("items", []):
        if not item["expires"] or not output.is_relative_to(Path(item["path"]).resolve()):
            continue
        if datetime.fromisoformat(item["expires"]).timestamp() < datetime.now().timestamp() + seconds_needed:
            return (
                f"workspace {item['name']} expires before the requested time ends; "
                "extend it or choose a shorter compute profile"
            )
    return ""


def implicit_profile(config: dict[str, Any]) -> dict[str, Any]:
    """The one profile of a deployment whose user defined none: the operator file's own values."""
    limits, site = config["limits"], config.get("slurm", {})
    return {
        "id": "default",
        "name": "Default",
        "account": site.get("account"),
        "partition": site.get("partition"),
        "gpus": min(gpu.MAX_GPUS, limits["gpus"]),
        "cpus": limits["cpus"],
        "memory_mb": limits["memory_mb"],
        "seconds": limits["seconds"],
    }


def load_profiles(workspace: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        descriptor = os.open(workspace / PROFILES_FILE, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            raw = json.loads(handle.read(MAX_PROFILES_BYTES))
        profiles = [p for p in raw["profiles"] if isinstance(p, dict)][:MAX_PROFILES]
    except (OSError, ValueError, KeyError, TypeError):
        profiles = []
    return profiles or [implicit_profile(config)]


def static_problem(profile: dict[str, Any], config: dict[str, Any]) -> str:
    """Why the operator's limits refuse this profile; empty when they allow it."""
    limits, site = config["limits"], config.get("slurm", {})
    if not isinstance(profile.get("id"), str) or not re.fullmatch(PROFILE_ID, profile["id"]):
        return "invalid profile id"
    for name in ("account", "partition"):
        value = profile.get(name) or site.get(name)
        allowed = site.get(name + "s") or ([site[name]] if name in site else None)
        if value is None:
            if allowed is not None:
                return f"choose a {name}: the operator allows {', '.join(allowed)}"
            continue
        if not isinstance(value, str) or not re.fullmatch(NAME, value):
            return f"invalid {name}"
        if allowed is not None and value not in allowed:
            return f"{name} {value} is not allowed by the operator"
    bounds = {
        "gpus": min(gpu.MAX_GPUS, limits["gpus"]),
        "cpus": limits["cpus"],
        "memory_mb": limits["memory_mb"],
        "seconds": limits["seconds"],
    }
    for name, maximum in bounds.items():
        value = profile.get(name)
        if type(value) is not int or not 1 <= value <= maximum:
            return f"{name} must be 1..{maximum}"
    return ""


def resources(profile: dict[str, Any], config: dict[str, Any], gpus: int) -> list[str]:
    """The resource arguments of a validated profile; every value is a checked name or an integer."""
    site = config.get("slurm", {})
    request = f"--gpus={gpus}" if site.get("gpu_request") == "gpus" else f"--gres=gpu:{gpus}"
    return [
        "--nodes=1",
        "--ntasks=1",
        f"--cpus-per-task={profile['cpus']}",
        f"--mem={profile['memory_mb']}M",
        f"--time={-(-profile['seconds'] // 60)}",
        request,
        *[
            f"--{name}={profile.get(name) or site[name]}"
            for name in ("partition", "account")
            if profile.get(name) or site.get(name)
        ],
        *[f"--{name}={site[name]}" for name in ("qos", "constraint") if name in site],
    ]


def check_profile(profile: dict[str, Any], config: dict[str, Any], found: dict[str, Any]) -> dict[str, Any]:
    """`valid`, `rejected` with the reason, or `unchecked` while the scheduler does not answer."""
    verdict: dict[str, Any] = {"status": "rejected", "reason": "", "checked_at": utc_now(), "estimated_start": None}
    verdict["reason"] = static_problem(profile, config)
    if verdict["reason"]:
        return verdict
    partitions = {entry["name"]: entry for entry in found.get("partitions") or []}
    partition = profile.get("partition") or config.get("slurm", {}).get("partition")
    if found.get("partitions") is not None and partition:
        entry = partitions.get(partition)
        if entry is None or not entry["up"]:
            verdict["reason"] = f"partition {partition} is not available"
            return verdict
        if entry["max_seconds"] is not None and profile["seconds"] > entry["max_seconds"]:
            verdict["reason"] = "the requested time exceeds the partition's limit"
            return verdict
    accounts = found.get("accounts")
    account = profile.get("account") or config.get("slurm", {}).get("account")
    if accounts is not None and account and account not in accounts:
        verdict["reason"] = f"account {account} is not one of yours"
        return verdict
    argv = ["sbatch", "--test-only", "--export=NONE", *resources(profile, config, profile["gpus"]), "--wrap=true"]
    try:
        result = command(argv)
    except (OSError, subprocess.TimeoutExpired):
        return {**verdict, "status": "unchecked", "reason": "the scheduler did not answer"}
    text = (result.stderr or result.stdout).strip()
    if result.returncode:
        verdict["reason"] = text.splitlines()[-1][-300:] if text else "the scheduler refused the request"
        return verdict
    start = re.search(r"to start at (\S+)", text)
    return {**verdict, "status": "valid", "estimated_start": start.group(1) if start else None}


def job_status(name: str) -> dict[str, dict[str, Any]] | None:
    """The user's queued or running jobs called `name`, by id; None when the scheduler is silent."""
    listed = answer(["squeue", "--noheader", f"--user={os.getuid()}", f"--name={name}", "--format=%i|%T|%r|%N|%M|%l"])
    if listed is None:
        return None
    jobs: dict[str, dict[str, Any]] = {}
    for line in listed.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) == 6 and parts[1]:
            jobs[parts[0]] = {
                "job_id": parts[0],
                "state": parts[1].split()[0],
                "pending_reason": parts[2] if parts[2] not in ("", "None") else None,
                "node": parts[3] or None,
                "elapsed": parts[4] or None,
                "time_limit": parts[5] or None,
            }
    return jobs


def accounting(identity: str) -> dict[str, Any]:
    """What accounting knows about a finished job; keys are absent where the site has no such tool."""
    report: dict[str, Any] = {}
    row = answer(
        [
            "sacct",
            "--noheader",
            "--parsable2",
            "--allocations",
            f"--jobs={identity}",
            "--format=State,Elapsed,ExitCode,NodeList",
        ],
        timeout=5,
    )
    parts = (row or "").strip().split("\n")[0].split("|")
    if len(parts) == 4 and parts[0]:
        report["accounting"] = dict(zip(("state", "elapsed", "exit_code", "nodes"), parts, strict=True))
    efficiency = answer(["seff", identity], timeout=5)
    if efficiency:
        report["efficiency"] = efficiency.strip()[-2000:]
    return report
