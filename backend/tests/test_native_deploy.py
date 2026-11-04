"""OPS-22: `scripts/rw-native.py` restores what a release needs; systemd is never called here."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

TOOL = Path(__file__).resolve().parents[2] / "scripts" / "rw-native.py"


@pytest.fixture
def tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("rw_native", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rw_native"] = module
    spec.loader.exec_module(module)
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(module, "systemctl", lambda *args: calls.append(args))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(module, "UNITS", tmp_path / "units")
    (tmp_path / "units").mkdir()
    return module


def _backup(tmp_path: Path, tool: ModuleType, release: dict[str, Any]) -> tuple[Path, Path]:
    state = tmp_path / "state"
    (state / "config").mkdir(parents=True)
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "release.json").write_text(json.dumps(release))
    (backup / tool.APP_UNIT).write_text("previous unit\n")
    tool.write_native_env(state, state / "releases/new", tmp_path / "pool")
    return backup, state


def test_rollback_to_a_native_release_points_its_environment_back(
    tmp_path: Path, tool: ModuleType
) -> None:
    release = {"deployment_kind": "native-conda", "tag": "old"}
    backup, state = _backup(tmp_path, tool, release)
    tool.restore(backup, state, tmp_path / "pool")
    env = (state / "config/native.env").read_text()
    old = state / "releases/old"
    assert f"PYTHONPATH={old / 'backend'}:{old / 'plugins/dicom/src'}\n" in env
    assert f"STATIC_ROOT={old / 'static'}\n" in env
    assert "releases/new" not in env
    assert json.loads((state / "config/release.json").read_text()) == release
    assert (tool.UNITS / tool.APP_UNIT).read_text() == "previous unit\n"


def test_rollback_to_a_container_release_leaves_the_unused_file(
    tmp_path: Path, tool: ModuleType
) -> None:
    backup, state = _backup(tmp_path, tool, {"deployment_kind": "local-udocker-package"})
    before = (state / "config/native.env").read_text()
    tool.restore(backup, state, tmp_path / "pool")
    assert (state / "config/native.env").read_text() == before
    assert (tool.UNITS / tool.APP_UNIT).read_text() == "previous unit\n"
