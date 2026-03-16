from __future__ import annotations

from app.config import get_settings
from app.services.byte_lru import BytesLRUCache


class MeshCache(BytesLRUCache):
    @staticmethod
    def build_key(load_handle: str, label: int, smooth: bool) -> str:
        return f"{load_handle}|{label}|{int(bool(smooth))}"

    def reset(self) -> None:
        self.clear()


mesh_cache = MeshCache(max_bytes=get_settings().mesh_cache_max_bytes)
