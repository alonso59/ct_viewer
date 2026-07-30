from __future__ import annotations

import logging
import traceback

from fastapi import APIRouter, HTTPException, Query, Response

from app.services.mesh_cache import mesh_cache
from app.services.mesh_generator import generate_mesh
from app.services.volume_cache import volume_cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mesh"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RuntimeError):
        message = str(exc)
        if "load handle" in message.lower():
            return HTTPException(status_code=410, detail=message)
        return HTTPException(status_code=409, detail=message)
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    logger.error("Unexpected mesh error: %s\n%s", repr(exc), traceback.format_exc())
    return HTTPException(status_code=500, detail=f"Unexpected mesh error: {type(exc).__name__}: {exc}")


@router.get("/api/mesh/{label}")
def mesh_glb(
    label: int,
    load_handle: str = Query(...),
    smooth: bool = Query(default=True),
):
    try:
        _volume, mask, spacing = volume_cache.get_by_handle(load_handle)
        cache_key = mesh_cache.build_key(load_handle=load_handle, label=label, smooth=smooth)
        glb_bytes = mesh_cache.get(cache_key)
        if glb_bytes is None:
            glb_bytes = generate_mesh(mask=mask, label=label, spacing=spacing, smooth=smooth)
            if glb_bytes is not None:
                mesh_cache.set(cache_key, glb_bytes)
    except Exception as exc:
        raise _http_error(exc) from exc

    if glb_bytes is None:
        raise HTTPException(
            status_code=404,
            detail=f"No mesh is available for label {label}",
        )

    return Response(content=glb_bytes, media_type="model/gltf-binary")
