"""Runtime configuration from environment variables (OPS-03, docs/ops/DEPLOYMENT.md)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Set by the image (`ENV CONTAINER_MODE=1` in the Dockerfile); unset in local dev (OPS-04).
    container_mode: bool = False
    workspace_root: Path = Path("/workspace")
    allowed_data_roots: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    public_base_url: str = ""
    job_workers: int = 2
    project_cache_max: int = 4
    cache_max_gb: int = 20
    viewer_max_loaded: int = 3
    log_level: str = "info"
    static_root: Path = Path("/app/static")

    @field_validator("port")
    @classmethod
    def _port_unprivileged(cls, v: int) -> int:
        if not 1024 <= v <= 65535:
            raise ValueError("PORT must be in 1024..65535")
        return v

    @field_validator("job_workers", "project_cache_max", "viewer_max_loaded")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
        return v

    @field_validator("allowed_data_roots")
    @classmethod
    def _absolute_roots(cls, v: str) -> str:
        for p in (p for p in v.split(":") if p):
            if not Path(p).is_absolute():
                raise ValueError(f"ALLOWED_DATA_ROOTS entries must be absolute: {p!r}")
        return v

    @model_validator(mode="after")
    def _roots_required_in_container(self) -> Settings:
        if self.container_mode and not self.allowed_roots:
            raise ValueError("ALLOWED_DATA_ROOTS must not be empty in container mode (OPS-04)")
        return self

    @property
    def allowed_roots(self) -> list[Path]:
        """Resolved allowed roots (OPS-04). Empty means unrestricted (local dev only)."""
        return [Path(p).resolve() for p in self.allowed_data_roots.split(":") if p]

    @property
    def base_url(self) -> str:
        return (self.public_base_url or f"http://localhost:{self.port}").rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
