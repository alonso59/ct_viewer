from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
import time
import uuid

import numpy as np

from app.config import get_settings
from app.models.dataset import VolumeInfo, VolumeMetadata
from app.services.discovery import resolve_series_source
from app.services.mask_loader import load_mask
from app.services.nifti_loader import load_nifti
from app.services.numpy_loader import load_numpy
from app.services.volume_metadata import (
    build_volume_metadata,
    labels_for_mask,
    validate_volume_alignment,
)
from app.services.workspace import validate_workspace_dataset_id


@dataclass
class CachedSeries:
    key: str
    series_id: str
    volume: np.ndarray
    mask: np.ndarray | None
    spacing: tuple[float, float, float]
    labels: list[int]
    metadata: VolumeMetadata
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
    ) -> VolumeInfo:
        with self._lock:
            self._purge_expired_handles()
            cache_key = f"{dataset_id}:{case_id}:{series_id}:{cache_key_suffix}:{image_path}:{mask_path or ''}"
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
                loaded_volume = load_nifti(image_path)
                loaded_mask = load_mask(mask_path, is_nifti=True) if mask_path else None
            elif source_type == "voi" or source_type == "voi_numpy":
                loaded_volume = load_numpy(image_path)
                loaded_mask = load_mask(mask_path, is_nifti=False) if mask_path else None
            elif source_type == "voi_nifti":
                loaded_volume = load_nifti(image_path)
                loaded_mask = load_mask(mask_path, is_nifti=True) if mask_path else None
            else:
                raise ValueError(f"Unsupported series type '{source_type}'")
        except (FileNotFoundError, ValueError) as exc:
            raise type(exc)(
                f"{exc} ({context})"
            ) from exc

        alignment = validate_volume_alignment(loaded_volume, loaded_mask)
        segmentation_labels = labels_for_mask(loaded_mask.data if loaded_mask is not None else None)
        mask = loaded_mask.data if loaded_mask is not None and alignment.shape_matches else None
        labels = labels_for_mask(mask)
        metadata = build_volume_metadata(
            source_type=source_type,
            volume=loaded_volume,
            segmentation=loaded_mask,
            labels=segmentation_labels,
            alignment=alignment,
        )

        volume = loaded_volume.data
        spacing = tuple(float(value) for value in loaded_volume.geometry.spacing[:3])
        cached = CachedSeries(
            key=cache_key,
            series_id=series_id,
            volume=volume,
            mask=mask,
            spacing=spacing,
            labels=labels,
            metadata=metadata,
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
            cached = self._get_cached_by_handle_locked(load_handle)
            return cached.volume, cached.mask, cached.spacing

    def get_record_by_handle(self, load_handle: str) -> CachedSeries:
        with self._lock:
            return self._get_cached_by_handle_locked(load_handle)

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

    def _get_cached_by_handle_locked(self, load_handle: str) -> CachedSeries:
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
        return cached

    @staticmethod
    def _volume_info(series_id: str, load_handle: str, cached: CachedSeries) -> VolumeInfo:
        return VolumeInfo(
            series_id=series_id,
            load_handle=load_handle,
            shape=list(cached.volume.shape),
            spacing=[float(value) for value in cached.spacing],
            has_mask=cached.mask is not None,
            labels=list(cached.labels),
            warnings=list(cached.metadata.warnings),
            metadata=cached.metadata,
        )


volume_cache = VolumeCache(max_bytes=get_settings().volume_cache_max_bytes)
