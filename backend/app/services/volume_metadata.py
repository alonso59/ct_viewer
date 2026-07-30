from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from app.models.dataset import (
    GeometryValidation,
    SegmentationMetadata,
    VolumeGeometry,
    VolumeMetadata,
    VolumeWarning,
)


# Geometry comparisons use millimetres because NIfTI affines map voxel indices
# into physical patient/world coordinates. This tolerance is strict enough to
# catch CT-mask misregistration while allowing harmless float serialization noise.
GEOMETRY_ALIGNMENT_TOLERANCE_MM = 1e-3


@dataclass(frozen=True)
class LoadedVolume:
    data: np.ndarray
    geometry: VolumeGeometry
    source_fingerprint: str
    source_path: str
    source_format: str
    has_affine: bool


def loaded_volume_from_array(
    *,
    data: np.ndarray,
    source_path: Path,
    source_format: str,
    affine: np.ndarray | None,
) -> LoadedVolume:
    canonical_affine = np.asarray(affine, dtype=np.float64) if affine is not None else _identity_affine()
    geometry = build_geometry(data, canonical_affine)
    return LoadedVolume(
        data=data,
        geometry=geometry,
        source_fingerprint=file_fingerprint(source_path),
        source_path=str(source_path.resolve()),
        source_format=source_format,
        has_affine=affine is not None,
    )


def build_geometry(data: np.ndarray, index_to_world: np.ndarray) -> VolumeGeometry:
    affine = np.asarray(index_to_world, dtype=np.float64)
    if affine.shape != (4, 4):
        raise ValueError(f"index-to-world matrix must be 4x4; got {affine.shape}")

    spacing, direction = _spacing_and_direction(affine)
    return VolumeGeometry(
        dimensions=[int(value) for value in data.shape[:3]],
        spacing=[float(value) for value in spacing],
        origin=[float(value) for value in affine[:3, 3]],
        direction=_matrix_to_list(direction),
        index_to_world=_matrix_to_list(affine),
        dtype=np.dtype(data.dtype).name,
        byte_order=_byte_order_name(np.dtype(data.dtype)),
        scalar_range=_scalar_range(data),
    )


def build_volume_metadata(
    *,
    source_type: str,
    volume: LoadedVolume,
    segmentation: LoadedVolume | None,
    labels: list[int],
    alignment: GeometryValidation,
) -> VolumeMetadata:
    segmentation_metadata = (
        SegmentationMetadata(
            source_format=segmentation.source_format,
            source_path=segmentation.source_path,
            source_fingerprint=segmentation.source_fingerprint,
            geometry=segmentation.geometry,
            labels=labels,
        )
        if segmentation is not None
        else None
    )
    geometry_fingerprint = stable_fingerprint({"volume_geometry": volume.geometry.model_dump()})
    segmentation_geometry_fingerprint = stable_fingerprint(
        {
            "segmentation_geometry": (
                segmentation.geometry.model_dump() if segmentation is not None else None
            ),
            "labels": labels,
        }
    )
    fingerprint = stable_fingerprint(
        {
            "source_type": source_type,
            "volume_source": volume.source_fingerprint,
            "segmentation_source": (
                segmentation.source_fingerprint if segmentation is not None else None
            ),
            "volume_geometry": geometry_fingerprint,
            "segmentation_geometry": segmentation_geometry_fingerprint,
        }
    )
    warnings = list(alignment.warnings)
    return VolumeMetadata(
        source_type=source_type,
        source_format=volume.source_format,
        source_path=volume.source_path,
        source_fingerprint=volume.source_fingerprint,
        geometry_fingerprint=geometry_fingerprint,
        fingerprint=fingerprint,
        geometry=volume.geometry,
        segmentation=segmentation_metadata,
        alignment=alignment,
        warnings=warnings,
    )


def validate_volume_alignment(
    volume: LoadedVolume,
    segmentation: LoadedVolume | None,
    *,
    tolerance_mm: float = GEOMETRY_ALIGNMENT_TOLERANCE_MM,
) -> GeometryValidation:
    if segmentation is None:
        return GeometryValidation(
            status="not_applicable",
            tolerance_mm=float(tolerance_mm),
            shape_matches=True,
            affine_matches=None,
            cornerstone_compatible=True,
            warnings=[],
        )

    warnings: list[VolumeWarning] = []
    shape_matches = volume.geometry.dimensions == segmentation.geometry.dimensions
    affine_matches: bool | None = None

    if not shape_matches:
        warnings.append(
            VolumeWarning(
                code="shape_mismatch",
                message=(
                    "CT volume shape "
                    f"{volume.geometry.dimensions} does not match segmentation shape "
                    f"{segmentation.geometry.dimensions}; segmentation overlays are disabled."
                ),
                severity="warning",
            )
        )

    if volume.has_affine and segmentation.has_affine:
        affine_matches = bool(
            np.allclose(
                np.asarray(volume.geometry.index_to_world, dtype=np.float64),
                np.asarray(segmentation.geometry.index_to_world, dtype=np.float64),
                atol=float(tolerance_mm),
                rtol=0.0,
            )
        )
        if not affine_matches:
            warnings.append(
                VolumeWarning(
                    code="affine_mismatch",
                    message=(
                        "CT and segmentation NIfTI geometry differ beyond "
                        f"{tolerance_mm:g} mm; Cornerstone rendering must use fallback to PNG."
                    ),
                    severity="warning",
                )
            )
    elif volume.has_affine != segmentation.has_affine:
        affine_matches = False
        warnings.append(
            VolumeWarning(
                code="missing_affine",
                message=(
                    "CT and segmentation geometry cannot be compared because only one "
                    "source provides an affine; Cornerstone rendering must fall back to PNG."
                ),
                severity="warning",
            )
        )

    cornerstone_compatible = shape_matches and (affine_matches is not False)
    return GeometryValidation(
        status="aligned" if cornerstone_compatible else "mismatch",
        tolerance_mm=float(tolerance_mm),
        shape_matches=shape_matches,
        affine_matches=affine_matches,
        cornerstone_compatible=cornerstone_compatible,
        warnings=warnings,
    )


def labels_for_mask(mask: np.ndarray | None) -> list[int]:
    if mask is None:
        return []
    return sorted(int(value) for value in np.unique(mask) if value > 0)


def file_fingerprint(path: Path) -> str:
    stat = path.stat()
    return stable_fingerprint(
        {
            "path": str(path.resolve()),
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }
    )


def stable_fingerprint(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _identity_affine() -> np.ndarray:
    return np.eye(4, dtype=np.float64)


def _spacing_and_direction(affine: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    axes = np.asarray(affine[:3, :3], dtype=np.float64)
    spacing = np.linalg.norm(axes, axis=0)
    direction = np.eye(3, dtype=np.float64)
    for axis_index, axis_spacing in enumerate(spacing):
        if axis_spacing > 0:
            direction[:, axis_index] = axes[:, axis_index] / axis_spacing
    return spacing, direction


def _byte_order_name(dtype: np.dtype) -> str:
    if dtype.byteorder == "<":
        return "little"
    if dtype.byteorder == ">":
        return "big"
    if dtype.byteorder == "=":
        return sys.byteorder
    return "not_applicable"


def _scalar_range(data: np.ndarray) -> list[float]:
    if data.size == 0:
        return [0.0, 0.0]
    try:
        minimum = float(np.nanmin(data))
        maximum = float(np.nanmax(data))
    except (TypeError, ValueError):
        return [0.0, 0.0]
    if not np.isfinite(minimum) or not np.isfinite(maximum):
        return [0.0, 0.0]
    return [minimum, maximum]


def _matrix_to_list(matrix: np.ndarray) -> list[list[float]]:
    return [[float(value) for value in row] for row in np.asarray(matrix).tolist()]
