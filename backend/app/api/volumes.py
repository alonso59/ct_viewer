from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
import numpy as np

from app.models.dataset import VolumeGeometry, VolumeMetadata
from app.services.volume_cache import CachedSeries, volume_cache
from app.services.volume_metadata import stable_fingerprint


router = APIRouter(tags=["volumes"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RuntimeError):
        message = str(exc)
        if "load handle" in message.lower():
            return HTTPException(status_code=410, detail=message)
        return HTTPException(status_code=409, detail=message)
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected volume API error")


@router.get(
    "/api/volumes/{load_handle}/metadata",
    response_model=VolumeMetadata,
)
def volume_metadata(load_handle: str, request: Request):
    try:
        cached = volume_cache.get_record_by_handle(load_handle)
        etag = _quoted_etag(cached.metadata.fingerprint)
        if _etag_matches(request, etag):
            return Response(status_code=304, headers=_etag_headers(etag, cached.metadata.fingerprint))
        return JSONResponse(
            content=jsonable_encoder(cached.metadata),
            headers=_etag_headers(etag, cached.metadata.fingerprint),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/api/volumes/{load_handle}/ct")
def volume_ct_scalars(load_handle: str, request: Request):
    try:
        cached = volume_cache.get_record_by_handle(load_handle)
        geometry = cached.metadata.geometry
        fingerprint = stable_fingerprint(
            {
                "kind": "ct-scalars",
                "source": cached.metadata.source_fingerprint,
                "geometry": cached.metadata.geometry.model_dump(),
            }
        )
        etag = _quoted_etag(fingerprint)
        headers = _binary_headers(etag, fingerprint, geometry)
        if _etag_matches(request, etag):
            return Response(status_code=304, headers=headers)
        return Response(
            content=_array_bytes(cached.volume),
            media_type="application/octet-stream",
            headers=headers,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/api/volumes/{load_handle}/segmentation")
def volume_segmentation_labelmap(load_handle: str, request: Request):
    try:
        cached = volume_cache.get_record_by_handle(load_handle)
        if cached.mask is None:
            raise _missing_segmentation(cached)
        if cached.metadata.segmentation is None:
            raise HTTPException(status_code=404, detail="No segmentation labelmap is available")

        geometry = cached.metadata.segmentation.geometry
        fingerprint = stable_fingerprint(
            {
                "kind": "segmentation-labelmap",
                "source": cached.metadata.segmentation.source_fingerprint,
                "geometry": geometry.model_dump(),
                "labels": cached.metadata.segmentation.labels,
            }
        )
        etag = _quoted_etag(fingerprint)
        headers = _binary_headers(etag, fingerprint, geometry)
        if _etag_matches(request, etag):
            return Response(status_code=304, headers=headers)
        return Response(
            content=_array_bytes(cached.mask),
            media_type="application/octet-stream",
            headers=headers,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from exc


def _array_bytes(data: np.ndarray) -> bytes:
    return np.ascontiguousarray(data).tobytes(order="C")


def _missing_segmentation(cached: CachedSeries) -> HTTPException:
    if cached.metadata.segmentation is None:
        return HTTPException(status_code=404, detail="No segmentation labelmap is available")
    warning = next(
        (
            item.message
            for item in cached.metadata.alignment.warnings
            if item.code == "shape_mismatch"
        ),
        "Segmentation labelmap is not available for this load handle",
    )
    return HTTPException(status_code=409, detail=warning)


def _quoted_etag(fingerprint: str) -> str:
    return f'"{fingerprint}"'


def _etag_matches(request: Request, etag: str) -> bool:
    header = request.headers.get("if-none-match")
    if not header:
        return False
    return any(candidate.strip() in {"*", etag} for candidate in header.split(","))


def _etag_headers(etag: str, fingerprint: str) -> dict[str, str]:
    return {
        "ETag": etag,
        "Cache-Control": "private, max-age=3600",
        "X-Volume-Fingerprint": fingerprint,
    }


def _binary_headers(etag: str, fingerprint: str, geometry: VolumeGeometry) -> dict[str, str]:
    headers = _etag_headers(etag, fingerprint)
    headers.update(
        {
            "X-Volume-Dimensions": ",".join(str(value) for value in geometry.dimensions),
            "X-Volume-Dtype": geometry.dtype,
            "X-Volume-Byte-Order": geometry.byte_order,
            "X-Volume-Scalar-Range": ",".join(str(value) for value in geometry.scalar_range),
        }
    )
    return headers
