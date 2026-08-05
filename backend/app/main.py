from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.cases import router as cases_router
from app.api.curation import router as curation_router
from app.api.datasets import router as datasets_router
from app.api.mesh import router as mesh_router
from app.api.metadata_sync import router as metadata_sync_router
from app.api.review import router as review_router
from app.api.settings import router as settings_router
from app.api.slices import router as slices_router
from app.api.volumes import router as volumes_router
from app.api.workspace import router as workspace_router
from app.config import get_settings
from app.middleware.auth import AuthMiddleware
from app.services.desktop_lifecycle import request_shutdown


def _resolve_static_dir() -> Path:
    configured = os.environ.get("STATIC_ROOT")
    if configured:
        return Path(configured).resolve()

    container_static = Path("/app/static")
    if container_static.is_dir():
        return container_static.resolve()

    return (Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve()


_STATIC_DIR = _resolve_static_dir()


def _safe_static_file(relative_path: str) -> Path | None:
    candidate = (_STATIC_DIR / relative_path).resolve()
    if not candidate.is_relative_to(_STATIC_DIR):
        return None
    if not candidate.is_file():
        return None
    return candidate


def create_app() -> FastAPI:
    application = FastAPI(title="Radiology WebUI API")
    application.add_middleware(AuthMiddleware)
    settings = get_settings()
    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    application.include_router(cases_router)
    application.include_router(curation_router)
    application.include_router(datasets_router)
    application.include_router(mesh_router)
    application.include_router(metadata_sync_router)
    application.include_router(review_router)
    application.include_router(settings_router)
    application.include_router(slices_router)
    application.include_router(volumes_router)
    application.include_router(workspace_router)

    @application.get("/api/health")
    def health() -> dict[str, str | bool]:
        runtime_settings = get_settings()
        return {
            "status": "ok",
            "allow_data_mutations": runtime_settings.allow_data_mutations,
            "webui_state_dir": runtime_settings.webui_state_dir or "",
            "mpr_renderer": runtime_settings.mpr_renderer,
        }

    if settings.desktop_runtime:

        @application.get("/api/desktop/ready", include_in_schema=False)
        def desktop_ready() -> dict[str, str]:
            return {"status": "ready"}

        @application.post("/api/desktop/shutdown", include_in_schema=False)
        def desktop_shutdown() -> dict[str, str]:
            if not request_shutdown():
                raise HTTPException(status_code=503, detail="Desktop shutdown is not ready")
            return {"status": "stopping"}

    @application.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        if not _STATIC_DIR.is_dir():
            raise HTTPException(
                status_code=404,
                detail=f"Frontend static build not found at {_STATIC_DIR}",
            )

        normalized = full_path.strip("/")
        if normalized:
            static_file = _safe_static_file(normalized)
            if static_file is not None:
                return FileResponse(static_file)

        index_path = _STATIC_DIR / "index.html"
        if not index_path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"Frontend index.html not found at {_STATIC_DIR / 'index.html'}",
            )
        return FileResponse(index_path)

    return application


app = create_app()
