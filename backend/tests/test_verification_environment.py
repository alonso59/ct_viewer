"""TST-22: required test prerequisites fail rather than silently losing coverage."""

from __future__ import annotations

from types import ModuleType, SimpleNamespace

import pytest

from tools import verify_environment as verification


def test_full_lane_rejects_missing_or_broken_radiomics(monkeypatch: pytest.MonkeyPatch) -> None:
    def load(name: str) -> ModuleType:
        if name == "radiomics":
            raise ImportError("radiomics unavailable")
        return ModuleType(name)

    monkeypatch.setattr(verification.importlib, "import_module", load)
    report = verification.check(full=True)
    assert report["ready"] is False
    assert any("radiomics" in error for error in report["errors"])


def test_full_lane_reports_binary_import_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def load(name: str) -> ModuleType:
        if name == "SimpleITK":
            raise OSError("incompatible binary")
        return ModuleType(name)

    monkeypatch.setattr(verification.importlib, "import_module", load)
    report = verification.check(full=True)
    assert report["ready"] is False
    assert any(
        "SimpleITK" in error and "incompatible binary" in error for error in report["errors"]
    )


def test_unsupported_python_refuses_test_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verification, "sys", SimpleNamespace(version_info=(3, 13, 0)))
    report = verification.check()
    assert report["ready"] is False
    assert any("3.12" in error for error in report["errors"])


def test_lean_lane_does_not_require_radiomics(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str] = []

    def load(name: str) -> ModuleType:
        requested.append(name)
        return ModuleType(name)

    monkeypatch.setattr(verification.importlib, "import_module", load)
    assert verification.check()["ready"] is True
    assert requested and "radiomics" not in requested


def test_full_lane_refuses_root_that_bypasses_source_permission_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(verification.importlib, "import_module", lambda name: ModuleType(name))
    report = verification.check(full=True)
    assert report["ready"] is False
    assert any("non-root" in error for error in report["errors"])
