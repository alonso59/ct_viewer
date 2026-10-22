"""OPS-17, TST-22: an effective probe needs every result, not just a successful exit."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools import runner_host_probe as probe

CHECKS = {
    "memory_limit": True,
    "tasks_limit": True,
    "swap_limit": True,
    "cpu_limit": True,
    "source_visible": True,
    "read_only": True,
    "device_policy": True,
    "network_isolation": True,
    "setsid_stays_in_cgroup": True,
}


@pytest.mark.parametrize(
    "observations",
    [{"memory_limit": True}, {**CHECKS, "device_policy": "false"}, {**CHECKS, "read_only": False}],
)
def test_successful_service_exit_does_not_certify_incomplete_or_invalid_results(
    observations: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe.shutil, "which", lambda name: name)

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "systemctl":
            return subprocess.CompletedProcess(
                argv, 0, "LoadState=loaded\nActiveState=inactive\n", ""
            )
        return subprocess.CompletedProcess(argv, 0, json.dumps({"checks": observations}), "")

    monkeypatch.setattr(probe.subprocess, "run", run)
    assert probe.run_probe()["ready"] is False


def test_protected_fixture_mutation_invalidates_probe_even_when_child_claims_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe.shutil, "which", lambda name: name)

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "systemd-run":
            Path(argv[-2]).write_text("mutated")
        if argv[0] == "systemctl":
            return subprocess.CompletedProcess(
                argv, 0, "LoadState=loaded\nActiveState=inactive\n", ""
            )
        return subprocess.CompletedProcess(argv, 0, json.dumps({"checks": CHECKS}), "")

    monkeypatch.setattr(probe.subprocess, "run", run)
    report = probe.run_probe()
    assert report["ready"] is False and report["source_unchanged"] is False


def test_failed_unit_cleanup_prevents_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe.shutil, "which", lambda name: name)

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "systemctl":
            return subprocess.CompletedProcess(argv, 1, "", "stop failed")
        if argv[0] == "systemctl":
            return subprocess.CompletedProcess(
                argv, 0, "LoadState=loaded\nActiveState=inactive\n", ""
            )
        return subprocess.CompletedProcess(argv, 0, json.dumps({"checks": CHECKS}), "")

    monkeypatch.setattr(probe.subprocess, "run", run)
    report = probe.run_probe()
    assert report["ready"] is False
    assert report["cleanup_verified"] is False


def test_failed_effective_checks_are_explicit_blockers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe.shutil, "which", lambda name: name)
    observations = {**CHECKS, "read_only": False, "network_isolation": False}

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "systemctl":
            return subprocess.CompletedProcess(
                argv, 0, "LoadState=loaded\nActiveState=inactive\n", ""
            )
        return subprocess.CompletedProcess(argv, 0, json.dumps({"checks": observations}), "")

    monkeypatch.setattr(probe.subprocess, "run", run)
    report = probe.run_probe()
    assert report["blockers"] == ["network_isolation", "read_only"]


def test_collected_inactive_unit_is_verified_without_successful_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe.shutil, "which", lambda name: name)

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "systemctl":
            if "stop" in argv:
                return subprocess.CompletedProcess(argv, 5, "", "Unit not loaded")
            return subprocess.CompletedProcess(
                argv, 0, "LoadState=not-found\nActiveState=inactive\n", ""
            )
        return subprocess.CompletedProcess(argv, 0, json.dumps({"checks": CHECKS}), "")

    monkeypatch.setattr(probe.subprocess, "run", run)
    report = probe.run_probe()
    assert report["cleanup_verified"] is True
    assert report["ready"] is True


def test_unprivileged_mode_uses_process_sandbox_instead_of_namespace_properties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe.shutil, "which", lambda name: name)
    launched: list[str] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "systemctl":
            return subprocess.CompletedProcess(
                argv, 0, "LoadState=not-found\nActiveState=inactive\n", ""
            )
        launched.extend(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"checks": CHECKS}), "")

    monkeypatch.setattr(probe.subprocess, "run", run)
    assert probe.run_probe(unprivileged=True)["ready"] is True
    assert not any("PrivateUsers=" in value or "PrivateNetwork=" in value for value in launched)
    assert any(value.endswith("runner/sandbox.py") for value in launched)
