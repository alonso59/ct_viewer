from __future__ import annotations

from app.config import get_settings
from app.services.byte_lru import BytesLRUCache


class SliceCache(BytesLRUCache):
    @staticmethod
    def build_key(
        load_handle: str,
        axis: str,
        index: int,
        ww: float,
        wl: float,
        layers: list[int],
        opacity_signature: tuple[tuple[int, float], ...],
    ) -> str:
        return (
            f"{load_handle}|{axis.lower()}|{index}|{ww:.4f}|{wl:.4f}|"
            f"{','.join(str(layer) for layer in layers)}|{opacity_signature!r}"
        )

    def reset(self) -> None:
        self.clear()


slice_cache = SliceCache(max_bytes=get_settings().slice_cache_max_bytes)
