from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock


@dataclass
class BytesCacheEntry:
    payload: bytes
    byte_size: int


class BytesLRUCache:
    def __init__(self, max_bytes: int):
        self.max_bytes = max(0, int(max_bytes))
        self._entries: OrderedDict[str, BytesCacheEntry] = OrderedDict()
        self._current_bytes = 0
        self._lock = RLock()

    def get(self, key: str) -> bytes | None:
        with self._lock:
            entry = self._entries.pop(key, None)
            if entry is None:
                return None
            self._entries[key] = entry
            return entry.payload

    def set(self, key: str, payload: bytes) -> bytes:
        byte_size = len(payload)
        with self._lock:
            existing = self._entries.pop(key, None)
            if existing is not None:
                self._current_bytes -= existing.byte_size

            entry = BytesCacheEntry(payload=payload, byte_size=byte_size)
            self._entries[key] = entry
            self._current_bytes += byte_size
            self._trim(protected_key=key)
            return payload

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._current_bytes = 0

    def _trim(self, protected_key: str | None = None) -> None:
        while self._entries and self._current_bytes > self.max_bytes:
            stale_key = next(iter(self._entries.keys()))
            if protected_key is not None and stale_key == protected_key and len(self._entries) == 1:
                break
            stale_entry = self._entries.pop(stale_key)
            self._current_bytes -= stale_entry.byte_size
