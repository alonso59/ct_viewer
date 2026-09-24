"""Config validation (OPS-03, OPS-04)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_dev_mode_allows_empty_roots() -> None:
    s = Settings(_env_file=None, allowed_data_roots="")
    assert s.container_mode is False
    assert s.allowed_roots == []


@pytest.mark.parametrize("roots", ["", ":", "::"])
def test_container_mode_refuses_empty_roots(roots: str) -> None:
    with pytest.raises(ValidationError, match="OPS-04"):
        Settings(_env_file=None, container_mode=True, allowed_data_roots=roots)


def test_container_mode_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CONTAINER_MODE", "1")
    monkeypatch.delenv("ALLOWED_DATA_ROOTS", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    monkeypatch.setenv("ALLOWED_DATA_ROOTS", f"{tmp_path}:{tmp_path / 'b'}")
    s = Settings(_env_file=None)
    assert s.container_mode is True
    assert len(s.allowed_roots) == 2


def test_relative_root_rejected() -> None:
    with pytest.raises(ValidationError, match="absolute"):
        Settings(_env_file=None, container_mode=True, allowed_data_roots="data")


@pytest.mark.parametrize("port", [80, 1023, 70000])
def test_privileged_or_invalid_port_rejected(port: int) -> None:
    with pytest.raises(ValidationError, match="PORT"):
        Settings(_env_file=None, port=port)
