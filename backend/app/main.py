from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
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

app = FastAPI(title="Radiology WebUI API")
app.add_middleware(AuthMiddleware)
app.include_router(cases_router)
app.include_router(curation_router)
app.include_router(datasets_router)
app.include_router(mesh_router)
app.include_router(metadata_sync_router)
app.include_router(review_router)
app.include_router(settings_router)
app.include_router(slices_router)
app.include_router(volumes_router)
app.include_router(workspace_router)

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


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "status": "ok",
        "allow_data_mutations": settings.allow_data_mutations,
        "webui_state_dir": settings.webui_state_dir or "",
        "mpr_renderer": settings.mpr_renderer,
    }


@app.get("/{full_path:path}", include_in_schema=False)
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
