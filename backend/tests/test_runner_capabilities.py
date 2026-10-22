"""OPS-16/17, TST-22: prerequisite observations never certify effective isolation."""

from __future__ import annotations

import pytest
from plugins.runner import preflight


def test_shared_machine_root_cannot_be_a_bounded_app_filesystem() -> None:
    assert preflight.storage_bounded("/", str(2**100)) is False


def test_missing_host_commands_are_reported_without_policy_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    monkeypatch.delenv("RW_RUNNER_STORAGE_ROOT", raising=False)
    report = preflight.inspect_host()
    assert report["ready"] is False
    assert {
        "user_manager",
        "controllers",
        "logout_persistence",
        "bounded_storage",
    } <= set(report["blockers"])
    assert report["policy_changed"] is False
    assert report["gpu_work_started"] is False


def test_observed_prerequisites_do_not_certify_effective_enforcement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight.shutil, "which", lambda name: name)

    def command(argv: list[str]) -> tuple[bool, str]:
        return True, "yes" if argv[0] == "loginctl" else "/user.slice/example"

    monkeypatch.setattr(preflight, "command", command)
    monkeypatch.setattr(preflight, "controllers", lambda group: {"cpu", "memory", "pids"})
    monkeypatch.setattr(preflight, "storage_bounded", lambda root, budget: True)
    report = preflight.inspect_host()
    assert report["prerequisites_ready"] is True
    assert report["ready"] is False
    assert report["blockers"] == ["effective_containment"]


@pytest.mark.parametrize("group", ["", "../outside", "/../../outside"])
def test_invalid_control_group_does_not_escape_cgroup_root(group: str) -> None:
    assert preflight.controllers(group) == set()
