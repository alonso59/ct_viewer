"""Runtime configuration from environment variables (OPS-03, docs/ops/DEPLOYMENT.md)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    workspace_root: Path = Path(".workspace")
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

    @property
    def allowed_roots(self) -> list[Path]:
        return [Path(p) for p in self.allowed_data_roots.split(":") if p]

    @property
    def base_url(self) -> str:
        return self.public_base_url or f"http://localhost:{self.port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
