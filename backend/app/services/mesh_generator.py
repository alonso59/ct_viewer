from __future__ import annotations

import numpy as np
import trimesh
from skimage.measure import marching_cubes
from trimesh.smoothing import filter_laplacian


MIN_COMPONENT_FACES = 96
MIN_COMPONENT_AREA_RATIO = 0.025


def generate_mesh(
    mask: np.ndarray | None,
    label: int,
    spacing: tuple[float, float, float],
    smooth: bool = True,
) -> bytes | None:
    if mask is None:
        return None
    if label <= 0:
        raise ValueError("Label must be a positive integer")

    binary = np.asarray(mask == label, dtype=np.uint8)
    if not np.any(binary):
        return None

    # Padding closes surfaces that would otherwise be clipped at the volume edge.
    padded = np.pad(binary, pad_width=1, mode="constant", constant_values=0)
    vertices, faces, normals, _ = marching_cubes(
        padded,
        level=0.5,
        spacing=spacing,
        allow_degenerate=False,
    )
    offset = np.asarray(spacing, dtype=np.float32)
    vertices = vertices - offset

    mesh = trimesh.Trimesh(
        vertices=vertices,
        faces=faces,
        vertex_normals=normals,
        process=False,
    )
    _cleanup_mesh(mesh)

    cleaned_mesh = _filter_components(mesh)
    if cleaned_mesh is None:
        return None

    if smooth:
        filter_laplacian(cleaned_mesh, lamb=0.18, iterations=2)
        _cleanup_mesh(cleaned_mesh)

    return cleaned_mesh.export(file_type="glb")


def _filter_components(mesh: trimesh.Trimesh) -> trimesh.Trimesh | None:
    components = [component for component in mesh.split(only_watertight=False) if len(component.faces) > 0]
    if not components:
        return None

    max_area = max(float(component.area) for component in components)
    kept = [
        component
        for component in components
        if len(component.faces) >= MIN_COMPONENT_FACES
        and float(component.area) >= max_area * MIN_COMPONENT_AREA_RATIO
    ]
    if not kept:
        largest = max(components, key=lambda component: (float(component.area), len(component.faces)))
        kept = [largest]

    combined = trimesh.util.concatenate(kept)
    combined.process(validate=True)
    if len(combined.faces) == 0 or len(combined.vertices) == 0:
        return None
    return combined


def _cleanup_mesh(mesh: trimesh.Trimesh) -> None:
    nondegenerate = mesh.nondegenerate_faces()
    if nondegenerate is not None:
        mesh.update_faces(nondegenerate)
    mesh.remove_unreferenced_vertices()
