from __future__ import annotations


def reset_runtime_caches() -> None:
    from app.services.discovery import reset_discovery_index
    from app.services.mesh_cache import mesh_cache
    from app.services.slice_cache import slice_cache
    from app.services.volume_cache import volume_cache

    volume_cache.reset()
    slice_cache.reset()
    mesh_cache.reset()
    reset_discovery_index()
