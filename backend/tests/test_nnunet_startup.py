"""SEG-02: a valid registered model is usable without the KiTS profile being installed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from plugins.nnunet import check


def test_startup_advertises_an_independent_valid_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot: dict[str, Any] = {
        "generation": "one",
        "profiles": [
            {"id": "liver-ct", "available": True},
            {"id": "kits2023-dataset220", "available": False, "reason": "missing artifact"},
        ],
    }
    monkeypatch.setattr(check, "catalog", lambda **kwargs: snapshot, raising=False)
    monkeypatch.setattr(check.shutil, "which", lambda name: f"/approved/bin/{name}")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    assert check.main() == 0
    assert json.loads(capsys.readouterr().out)["model_catalog"] == snapshot


def test_missing_trainer_marks_a_profile_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.nnunet.catalog import catalog

    from tests.test_nnunet_catalog import model

    model(tmp_path, monkeypatch)
    snapshot = catalog(trainer_available=lambda name: False)
    assert snapshot["profiles"][0]["available"] is False
    assert "trainer" in snapshot["profiles"][0]["reason"]
