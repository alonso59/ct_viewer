from __future__ import annotations

from copy import deepcopy

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.models.dataset import VolumeInfo
from app.services.slice_cache import slice_cache
from app.services.slice_renderer import (
    DEFAULT_LAYER_CONFIG,
    default_layer_config,
    render_mask_overlay_slice,
    render_slice,
)
from app.services.volume_cache import volume_cache


router = APIRouter(tags=["slices"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RuntimeError):
        message = str(exc)
        if "load handle" in message.lower():
            return HTTPException(status_code=410, detail=message)
        return HTTPException(status_code=409, detail=message)
    if isinstance(exc, (IndexError, ValueError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Unexpected slice error")


def _parse_layers(layers: str | None) -> list[int]:
    if layers is None:
        return [1, 2]
    cleaned = layers.strip()
    if not cleaned:
        return []
    parsed: list[int] = []
    for part in cleaned.split(","):
        token = part.strip()
        if not token:
            continue
        parsed.append(int(token))
    return sorted(set(parsed))


def _layer_config_from_query(
    request: Request,
    layers: list[int],
) -> tuple[dict[int, dict], tuple[tuple[int, float], ...]]:
    layer_config = deepcopy(DEFAULT_LAYER_CONFIG)
    for label in layers:
        layer_config.setdefault(label, default_layer_config(label))

    opacity_signature: list[tuple[int, float]] = []
    for label, config in sorted(layer_config.items()):
        opacity_key = f"opacity_{label}"
        if opacity_key in request.query_params:
            config["alpha"] = float(request.query_params[opacity_key])
        opacity_signature.append((label, float(config["alpha"])))
    return layer_config, tuple(opacity_signature)


@router.post(
    "/api/datasets/{dataset_id}/patients/{patient_id}/series/{series_id}/load",
    response_model=VolumeInfo,
)
def load_series(
    dataset_id: str,
    patient_id: str,
    series_id: str,
    storage_path: str | None = Query(default=None),
):
    try:
        return volume_cache.load_series(
            dataset_id,
            patient_id,
            series_id,
            storage_path=storage_path,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/api/slice/{axis}/{index}")
def slice_png(
    axis: str,
    index: int,
    request: Request,
    load_handle: str = Query(...),
    ww: float = Query(default=300.0),
    wl: float = Query(default=100.0),
    layers: str | None = Query(default="1,2"),
):
    try:
        cached = volume_cache.get_record_by_handle(load_handle)
        visible_layers = _parse_layers(layers)
        layer_config, opacity_signature = _layer_config_from_query(request, visible_layers)

        cache_key = slice_cache.build_key(
            data_key=cached.metadata.fingerprint,
            axis=axis,
            index=index,
            ww=ww,
            wl=wl,
            layers=visible_layers,
            opacity_signature=opacity_signature,
        )
        cached_png = slice_cache.get(cache_key)
        if cached_png is not None:
            return Response(content=cached_png, media_type="image/png")

        png_bytes = render_slice(
            volume=cached.volume,
            mask=cached.mask,
            axis=axis,
            index=index,
            ww=ww,
            wl=wl,
            layers=visible_layers,
            layer_config=layer_config,
            spacing=cached.spacing,
        )
        slice_cache.set(cache_key, png_bytes)
    except Exception as exc:
        raise _http_error(exc) from exc

    return Response(content=png_bytes, media_type="image/png")


@router.get("/api/slice-overlay/{axis}/{index}")
def slice_mask_overlay_png(
    axis: str,
    index: int,
    request: Request,
    load_handle: str = Query(...),
    layers: str | None = Query(default="1,2"),
):
    try:
        cached = volume_cache.get_record_by_handle(load_handle)
        visible_layers = _parse_layers(layers)
        layer_config, opacity_signature = _layer_config_from_query(request, visible_layers)

        cache_key = slice_cache.build_key(
            data_key=cached.metadata.fingerprint,
            axis=f"overlay:{axis}",
            index=index,
            ww=0,
            wl=0,
            layers=visible_layers,
            opacity_signature=opacity_signature,
        )
        cached_png = slice_cache.get(cache_key)
        if cached_png is not None:
            return Response(content=cached_png, media_type="image/png")

        png_bytes = render_mask_overlay_slice(
            mask=cached.mask,
            axis=axis,
            index=index,
            layers=visible_layers,
            layer_config=layer_config,
            spacing=cached.spacing,
        )
        slice_cache.set(cache_key, png_bytes)
    except Exception as exc:
        raise _http_error(exc) from exc

    return Response(content=png_bytes, media_type="image/png")
