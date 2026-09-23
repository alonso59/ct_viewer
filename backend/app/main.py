"""App factory (BE-*). Routers are mounted under /api/v1 (docs/backend/API.md)."""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.api.v1 import router as v1_router


def create_app() -> FastAPI:
    app = FastAPI(title="Radiology Workbench", version=__version__)
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
