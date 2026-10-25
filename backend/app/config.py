from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Set by the image (`ENV CONTAINER_MODE=1` in the Dockerfile); unset in local dev.
    container_mode: bool = False
    workspace_root: Path = Path("/workspace")
    allowed_data_roots: str = ""
    allowed_derived_roots: str = ""
    managed_derived_root: Path | None = None
    # Read-only dir of external task manifests `*/task.json`.
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
    host_allocation_root: Path | None = None
    dicom_memory_mb: int | None = Field(default=None, ge=512, le=1048576)
    dicom_cpu_threads: int = Field(default=4, ge=1, le=12)
    dicom_header_mb: int = Field(default=8, ge=1, le=64)
    dicom_inventory_mb: int = Field(default=512, ge=1, le=16384)
    dicom_batch_size: int = Field(default=64, ge=1, le=512)
    dicom_cleanup_seconds: float = Field(default=28.0, ge=0.1, le=28.0)
    dicom_retention_days: int = Field(default=30, ge=1, le=3650)

    @model_validator(mode="after")
    def _dicom_limits(self) -> Settings:
        if self.job_workers + self.dicom_cpu_threads > 12:
            raise ValueError("JOB_WORKERS plus DICOM_CPU_THREADS must fit the 12 CPU budget")
        pool = self.host_allocation_root
        if pool is not None and (not pool.is_absolute() or pool.resolve() != pool):
            raise ValueError("HOST_ALLOCATION_ROOT must be absolute and canonical")
        if pool is not None and any(
            pool == root or root in pool.parents or pool in root.parents
            for root in self.allowed_roots
        ):
            raise ValueError("HOST_ALLOCATION_ROOT must not overlap a source root")
        return self

    @property
    def allocation_root(self) -> Path:
        return (
            self.host_allocation_root or self.workspace_root.resolve() / "plugins/dicom/host-pool"
        )

    @property
    def dicom_limits(self) -> dict[str, int | float | None]:
        return {
            "memory_mb": self.dicom_memory_mb,
            "cpu_threads": self.dicom_cpu_threads,
            "header_mb": self.dicom_header_mb,
            "inventory_mb": self.dicom_inventory_mb,
            "batch_size": self.dicom_batch_size,
            "cleanup_seconds": self.dicom_cleanup_seconds,
        }

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
            raise ValueError("ALLOWED_DATA_ROOTS must not be empty in container mode")
        return self

    @model_validator(mode="after")
    def _roots_must_not_overlap(self) -> Settings:
        if self.managed_derived_root is not None:
            expected = self.workspace_root.resolve().parent / "derived"
            if self.managed_derived_root.resolve() != expected:
                raise ValueError(
                    "MANAGED_DERIVED_ROOT must be the derived sibling of WORKSPACE_ROOT"
                )
        for d in self.derived_roots:
            if self.managed_derived_root is not None and d == self.managed_derived_root.resolve():
                continue
            for s in self.allowed_roots:
                if d == s or s in d.parents or d in s.parents:
                    raise ValueError(
                        f"roots-overlap: ALLOWED_DERIVED_ROOTS entry {str(d)!r} overlaps "
                        f"ALLOWED_DATA_ROOTS entry {str(s)!r}"
                    )
        return self

    @property
    def allowed_roots(self) -> list[Path]:
        """Resolved allowed roots. Empty means unrestricted (local dev only)."""
        return [Path(p).resolve() for p in self.allowed_data_roots.split(":") if p]

    @property
    def dataset_roots(self) -> list[Path]:
        """Write-once workspace datasets, readable as sources."""
        return [d / "_datasets" for d in self.derived_roots]

    @property
    def readable_roots(self) -> list[Path]:
        """Source guard roots; empty = unrestricted (dev), so datasets are only added to a
        restricted list."""
        roots = self.allowed_roots
        return [*roots, *self.dataset_roots] if roots else []

    @property
    def derived_roots(self) -> list[Path]:
        """Resolved writable derived roots. Empty means no derived root is allowed."""
        return [Path(p).resolve() for p in self.allowed_derived_roots.split(":") if p]

    @property
    def base_url(self) -> str:
        return (self.public_base_url or f"http://localhost:{self.port}").rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
