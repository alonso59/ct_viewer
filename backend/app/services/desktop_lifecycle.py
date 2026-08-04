from __future__ import annotations

from collections.abc import Callable
from threading import Lock


_lock = Lock()
_shutdown_callback: Callable[[], None] | None = None


def set_shutdown_callback(callback: Callable[[], None] | None) -> None:
    global _shutdown_callback
    with _lock:
        _shutdown_callback = callback


def request_shutdown() -> bool:
    with _lock:
        callback = _shutdown_callback
    if callback is None:
        return False
    callback()
    return True
