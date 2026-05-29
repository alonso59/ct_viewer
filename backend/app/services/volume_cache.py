from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Sequence
import time
import uuid

import numpy as np

from app.config import get_settings
from app.models.dataset import VolumeInfo
from app.services.discovery import resolve_series_source
from app.services.mask_loader import load_mask
from app.services.nifti_loader import load_nifti
from app.services.numpy_loader import load_numpy
from app.services.workspace import validate_workspace_dataset_id


VOI_DISPLAY_SPACING = (1.0, 1.0, 1.0)


@dataclass
class CachedSeries:
    key: str
    series_id: str
    volume: np.ndarray
    mask: np.ndarray | None
    spacing: tuple[float, float, float]
    labels: list[int]
    byte_size: int


@dataclass
class HandleRecord:
    cache_key: str
    updated_at: float


class VolumeCache:
    def __init__(
        self,
        max_bytes: int,
        max_handles: int = 256,
        handle_ttl_seconds: int = 30 * 60,
    ):
        self.max_bytes = max(0, int(max_bytes))
        self.max_handles = max_handles
        self.handle_ttl_seconds = handle_ttl_seconds
        self._series_cache: OrderedDict[str, CachedSeries] = OrderedDict()
        self._series_cache_bytes = 0
        self._handles: OrderedDict[str, HandleRecord] = OrderedDict()
        self._lock = RLock()

    def load_series(
        self,
        dataset_id: str,
        patient_id: str,
        series_id: str,
        storage_path: str | None = None,
    ) -> VolumeInfo:
        with self._lock:
            self._purge_expired_handles()
            dataset_path = validate_workspace_dataset_id(dataset_id)
            source = resolve_series_source(dataset_path, patient_id, series_id, storage_path=storage_path)
            cache_key = f"{dataset_id}:{patient_id}:{series_id}:{source.storage_path or source.image_path}"
            return self._load_paths_locked(
                cache_key=cache_key,
                series_id=series_id,
                image_path=source.image_path,
                mask_path=source.mask_path,
                source_type=source.type,
                context=f"dataset={dataset_id}, patient={patient_id}, series={series_id}",
            )

    def load_case_source(
        self,
        *,
        dataset_id: str,
        case_id: str,
        series_id: str,
        image_path: str,
        mask_path: str | None,
        source_type: str,
        cache_key_suffix: str,
        spacing_override: Sequence[float] | None = None,
    ) -> VolumeInfo:
        with self._lock:
            self._purge_expired_handles()
            spacing_key = "unit" if self._is_voi_source(source_type) else self._spacing_key(spacing_override)
            cache_key = f"{dataset_id}:{case_id}:{series_id}:{cache_key_suffix}:{image_path}:{mask_path or ''}:{spacing_key}"
            return self._load_paths_locked(
                cache_key=cache_key,
                series_id=series_id,
                image_path=image_path,
                mask_path=mask_path,
                source_type=source_type,
                context=f"dataset={dataset_id}, case={case_id}, series={series_id}",
            )

    def _load_paths_locked(
        self,
        *,
        cache_key: str,
        series_id: str,
        image_path: str,
        mask_path: str | None,
        source_type: str,
        context: str,
    ) -> VolumeInfo:
        cached = self._series_cache.pop(cache_key, None)
        if cached is not None:
            self._series_cache[cache_key] = cached
            load_handle = self._register_handle(cache_key)
            return self._volume_info(series_id, load_handle, cached)

        try:
            if source_type == "nifti":
                volume, spacing = load_nifti(image_path)
                mask = load_mask(mask_path, is_nifti=True) if mask_path else None
            elif source_type == "voi" or source_type == "voi_numpy":
                volume = load_numpy(image_path)
                spacing = VOI_DISPLAY_SPACING
                mask = load_mask(mask_path, is_nifti=False) if mask_path else None
            elif source_type == "voi_nifti":
                volume, _spacing = load_nifti(image_path)
                spacing = VOI_DISPLAY_SPACING
                mask = load_mask(mask_path, is_nifti=True) if mask_path else None
            else:
                raise ValueError(f"Unsupported series type '{source_type}'")
        except (FileNotFoundError, ValueError) as exc:
            raise type(exc)(
                f"{exc} ({context})"
            ) from exc

        if mask is not None and volume.shape != mask.shape:
            raise ValueError(
                f"Volume shape {volume.shape} does not match mask shape {mask.shape}"
            )

        labels = sorted(int(value) for value in np.unique(mask) if value > 0) if mask is not None else []
        cached = CachedSeries(
            key=cache_key,
            series_id=series_id,
            volume=volume,
            mask=mask,
            spacing=spacing,
            labels=labels,
            byte_size=volume.nbytes + (mask.nbytes if mask is not None else 0),
        )
        self._series_cache[cache_key] = cached
        self._series_cache_bytes += cached.byte_size
        self._trim_series_cache(protected_key=cache_key)

        load_handle = self._register_handle(cache_key)
        return self._volume_info(series_id, load_handle, cached)

    def get_by_handle(
        self,
        load_handle: str,
    ) -> tuple[np.ndarray, np.ndarray | None, tuple[float, float, float]]:
        with self._lock:
            self._purge_expired_handles()
            if not load_handle:
                raise RuntimeError("Load handle is required")

            record = self._handles.get(load_handle)
            if record is None:
                raise RuntimeError("Load handle is invalid or expired")

            cached = self._series_cache.get(record.cache_key)
            if cached is None:
                self._handles.pop(load_handle, None)
                raise RuntimeError("Load handle is no longer available")

            self._series_cache.pop(record.cache_key, None)
            self._series_cache[record.cache_key] = cached
            self._handles.pop(load_handle, None)
            self._handles[load_handle] = HandleRecord(
                cache_key=record.cache_key,
                updated_at=time.monotonic(),
            )
            return cached.volume, cached.mask, cached.spacing

    def reset(self) -> None:
        with self._lock:
            self._series_cache.clear()
            self._series_cache_bytes = 0
            self._handles.clear()

    def _trim_series_cache(self, protected_key: str | None = None) -> None:
        while self._series_cache and self._series_cache_bytes > self.max_bytes:
            stale_key = next(iter(self._series_cache.keys()))
            if protected_key is not None and stale_key == protected_key and len(self._series_cache) == 1:
                break
            stale_entry = self._series_cache.pop(stale_key)
            self._series_cache_bytes -= stale_entry.byte_size
            self._drop_handles_for_cache_key(stale_key)

    def _register_handle(self, cache_key: str) -> str:
        handle = uuid.uuid4().hex
        self._handles[handle] = HandleRecord(cache_key=cache_key, updated_at=time.monotonic())
        while len(self._handles) > self.max_handles:
            self._handles.popitem(last=False)
        return handle

    def _drop_handles_for_cache_key(self, cache_key: str) -> None:
        stale_handles = [
            handle
            for handle, record in self._handles.items()
            if record.cache_key == cache_key
        ]
        for handle in stale_handles:
            self._handles.pop(handle, None)

    def _purge_expired_handles(self) -> None:
        now = time.monotonic()
        while self._handles:
            handle, record = next(iter(self._handles.items()))
            if now - record.updated_at <= self.handle_ttl_seconds:
                break
            self._handles.pop(handle, None)

    @staticmethod
    def _volume_info(series_id: str, load_handle: str, cached: CachedSeries) -> VolumeInfo:
        return VolumeInfo(
            series_id=series_id,
            load_handle=load_handle,
            shape=list(cached.volume.shape),
            spacing=[float(value) for value in cached.spacing],
            has_mask=cached.mask is not None,
            labels=list(cached.labels),
        )

    @staticmethod
    def _normalize_spacing_override(
        spacing_override: Sequence[float] | None,
    ) -> tuple[float, float, float] | None:
        if spacing_override is None or len(spacing_override) < 3:
            return None
        values = tuple(float(spacing_override[index]) for index in range(3))
        if all(np.isfinite(value) and value > 0 for value in values):
            return values
        return None

    @classmethod
    def _spacing_key(cls, spacing_override: Sequence[float] | None) -> str:
        spacing = cls._normalize_spacing_override(spacing_override)
        if spacing is None:
            return "unit"
        return ",".join(f"{value:g}" for value in spacing)

    @staticmethod
    def _is_voi_source(source_type: str) -> bool:
        return source_type in {"voi", "voi_numpy", "voi_nifti"}


volume_cache = VolumeCache(max_bytes=get_settings().volume_cache_max_bytes)
