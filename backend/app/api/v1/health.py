"""API-01: liveness, versions and UI runtime config."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.config import get_settings

router = APIRouter(tags=["health"])


class UiConfig(BaseModel):
    viewer_max_loaded: int
    public_base_url: str


class Health(BaseModel):
    status: str
    version: str
    ui_config: UiConfig


@router.get("/health", response_model=Health)
def health() -> Health:
    settings = get_settings()
    return Health(
        status="ok",
        version=__version__,
        ui_config=UiConfig(
            viewer_max_loaded=settings.viewer_max_loaded,
            public_base_url=settings.base_url,
        ),
    )
