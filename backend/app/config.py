from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    data_root: str
    dataset_dir: str | None
    dataset_roots: str | None
    webui_state_dir: str | None
    radiology_ui_token: str
    log_level: str
    port: int
    allow_data_mutations: bool
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


def get_settings() -> Settings:
    return Settings(
        data_root=os.environ.get("DATA_ROOT", "../../data/dataset"),
        dataset_dir=os.environ.get("DATASET_DIR") or None,
        dataset_roots=os.environ.get("DATASET_ROOTS") or None,
        webui_state_dir=os.environ.get("WEBUI_STATE_DIR") or None,
        radiology_ui_token=os.environ.get("RADIOLOGY_UI_TOKEN", ""),
        log_level=os.environ.get("LOG_LEVEL", "info"),
        port=_parse_port(os.environ.get("PORT")),
        allow_data_mutations=_parse_bool(os.environ.get("ALLOW_DATA_MUTATIONS"), default=False),
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
