"""Runtime configuration from environment variables (OPS-03, docs/ops/DEPLOYMENT.md)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Set by the image (`ENV CONTAINER_MODE=1` in the Dockerfile); unset in local dev (OPS-04).
    container_mode: bool = False
    workspace_root: Path = Path("/workspace")
    allowed_data_roots: str = ""
    # Writable roots for `derived` path roots (OPS-11, ADR-0014); empty = no derived root.
    allowed_derived_roots: str = ""
    # Read-only dir of external task manifests `*/task.json` (TSK-01); empty = none.
    plugins_root: Path | None = None
    # Builtin plugins (`plugins/` next to `backend/`, `/app/plugins` in the image).
    builtin_plugins_root: Path = Path(__file__).resolve().parents[2] / "plugins"
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

    @field_validator("allowed_data_roots", "allowed_derived_roots")
    @classmethod
    def _absolute_roots(cls, v: str, info: ValidationInfo) -> str:
        for p in (p for p in v.split(":") if p):
            if not Path(p).is_absolute():
                raise ValueError(f"{str(info.field_name).upper()} entries must be absolute: {p!r}")
        return v

    @model_validator(mode="after")
    def _roots_required_in_container(self) -> Settings:
        if self.container_mode and not self.allowed_roots:
            raise ValueError("ALLOWED_DATA_ROOTS must not be empty in container mode (OPS-04)")
        return self

    @model_validator(mode="after")
    def _roots_must_not_overlap(self) -> Settings:
        """OPS-12 / BE-15: a derived root inside a data root (or vice versa) is refused."""
        for d in self.derived_roots:
            for s in self.allowed_roots:
                if d == s or s in d.parents or d in s.parents:
                    raise ValueError(
                        f"roots-overlap: ALLOWED_DERIVED_ROOTS entry {str(d)!r} overlaps "
                        f"ALLOWED_DATA_ROOTS entry {str(s)!r} (OPS-12)"
                    )
        return self

    @property
    def allowed_roots(self) -> list[Path]:
        """Resolved allowed roots (OPS-04). Empty means unrestricted (local dev only)."""
        return [Path(p).resolve() for p in self.allowed_data_roots.split(":") if p]

    @property
    def dataset_roots(self) -> list[Path]:
        """Write-once workspace datasets `{derived}/_datasets/` (TSK-13), readable as sources."""
        return [d / "_datasets" for d in self.derived_roots]

    @property
    def readable_roots(self) -> list[Path]:
        """Source guard roots: ALLOWED_DATA_ROOTS plus the workspace datasets (SRC-16); empty =
        unrestricted (dev), so datasets are only added to a restricted list."""
        roots = self.allowed_roots
        return [*roots, *self.dataset_roots] if roots else []

    @property
    def derived_roots(self) -> list[Path]:
        """Resolved writable derived roots (OPS-11). Empty means no derived root is allowed."""
        return [Path(p).resolve() for p in self.allowed_derived_roots.split(":") if p]

    @property
    def base_url(self) -> str:
        return (self.public_base_url or f"http://localhost:{self.port}").rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
