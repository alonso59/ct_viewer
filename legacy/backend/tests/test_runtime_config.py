from __future__ import annotations

from app.config import get_settings


def test_mpr_renderer_defaults_to_png(monkeypatch):
    monkeypatch.delenv("MPR_RENDERER", raising=False)

    assert get_settings().mpr_renderer == "png"


def test_mpr_renderer_accepts_png(monkeypatch):
    monkeypatch.setenv("MPR_RENDERER", "png")

    assert get_settings().mpr_renderer == "png"


def test_mpr_renderer_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("MPR_RENDERER", "cornerstone")

    assert get_settings().mpr_renderer == "png"
