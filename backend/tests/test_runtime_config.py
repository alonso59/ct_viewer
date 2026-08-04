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


def test_allowed_data_roots_default_to_data_root(monkeypatch):
    monkeypatch.setenv("DATA_ROOT", "/data/research")
    monkeypatch.delenv("ALLOWED_DATA_ROOTS", raising=False)
    monkeypatch.delenv("ALLOW_UNRESTRICTED_DATA_PATHS", raising=False)

    settings = get_settings()

    assert settings.allowed_data_roots == ("/data/research",)
    assert settings.allow_unrestricted_data_paths is False


def test_desktop_runtime_configuration_is_explicit(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://tauri.localhost, http://localhost:5173")
    monkeypatch.setenv("RADIOLOGY_DESKTOP_RUNTIME", "true")

    settings = get_settings()

    assert settings.cors_origins == (
        "http://tauri.localhost",
        "http://localhost:5173",
    )
    assert settings.desktop_runtime is True
