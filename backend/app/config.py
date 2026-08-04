from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    data_root: str
    allowed_data_roots: tuple[str, ...]
    allow_unrestricted_data_paths: bool
    cors_origins: tuple[str, ...]
    desktop_runtime: bool
    webui_state_dir: str | None
    radiology_ui_token: str
    log_level: str
    port: int
    allow_data_mutations: bool
    mpr_renderer: str
    volume_cache_max_bytes: int
    slice_cache_max_bytes: int
    mesh_cache_max_bytes: int


def _parse_port(value: str | None) -> int:
    if value is None:
        return 8000
    try:
        return int(value)
    except (TypeError, ValueError):
        return 8000


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_nonnegative_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _parse_mpr_renderer(value: str | None) -> str:
    normalized = (value or "png").strip().lower()
    if normalized == "png":
        return normalized
    return "png"


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def get_settings() -> Settings:
    data_root = os.environ.get("DATA_ROOT", "../../data/dataset")
    allowed_roots_raw = os.environ.get("ALLOWED_DATA_ROOTS")
    allowed_data_roots = tuple(
        part.strip()
        for part in (allowed_roots_raw or data_root).split(os.pathsep)
        if part.strip()
    ) or (data_root,)
    return Settings(
        data_root=data_root,
        allowed_data_roots=allowed_data_roots,
        allow_unrestricted_data_paths=_parse_bool(
            os.environ.get("ALLOW_UNRESTRICTED_DATA_PATHS"),
            default=False,
        ),
        cors_origins=_parse_csv(os.environ.get("CORS_ORIGINS")),
        desktop_runtime=_parse_bool(
            os.environ.get("RADIOLOGY_DESKTOP_RUNTIME"),
            default=False,
        ),
        webui_state_dir=os.environ.get("WEBUI_STATE_DIR") or None,
        radiology_ui_token=os.environ.get("RADIOLOGY_UI_TOKEN", ""),
        log_level=os.environ.get("LOG_LEVEL", "info"),
        port=_parse_port(os.environ.get("PORT")),
        allow_data_mutations=_parse_bool(os.environ.get("ALLOW_DATA_MUTATIONS"), default=False),
        mpr_renderer=_parse_mpr_renderer(os.environ.get("MPR_RENDERER")),
        volume_cache_max_bytes=_parse_nonnegative_int(
            os.environ.get("VOLUME_CACHE_MAX_BYTES"),
            768 * 1024 * 1024,
        ),
        slice_cache_max_bytes=_parse_nonnegative_int(
            os.environ.get("SLICE_CACHE_MAX_BYTES"),
            128 * 1024 * 1024,
        ),
        mesh_cache_max_bytes=_parse_nonnegative_int(
            os.environ.get("MESH_CACHE_MAX_BYTES"),
            256 * 1024 * 1024,
        ),
    )
