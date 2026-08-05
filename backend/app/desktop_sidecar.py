from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uvicorn


LOOPBACK_HOST = "127.0.0.1"
PARENT_CHECK_INTERVAL_SECONDS = 1.0


def _required_path(name: str) -> Path:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for the desktop sidecar")
    return Path(value).expanduser().resolve()


def _configure_logging(log_path: Path) -> None:
    from app.config import get_settings

    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(get_settings().log_level.upper())


def _bind_loopback_socket() -> socket.socket:
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((LOOPBACK_HOST, 0))
    server_socket.listen(2048)
    server_socket.setblocking(False)
    return server_socket


def _runtime_process_id(
    *, frozen: bool | None = None, platform_name: str | None = None
) -> int:
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    current_platform = os.name if platform_name is None else platform_name
    if current_platform == "nt" and is_frozen:
        return os.getppid()
    return os.getpid()


def _write_runtime_file(runtime_path: Path, port: int) -> None:
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = runtime_path.with_name(f".{runtime_path.name}.{os.getpid()}.tmp")
    payload = {"pid": _runtime_process_id(), "port": port}
    temporary_path.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary_path, runtime_path)


def _windows_process_is_alive(process_id: int) -> bool:
    synchronize = 0x00100000
    wait_timeout = 0x00000102
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [
        ctypes.wintypes.DWORD,
        ctypes.wintypes.BOOL,
        ctypes.wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = ctypes.wintypes.DWORD
    kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
    handle = kernel32.OpenProcess(synchronize, False, process_id)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
        kernel32.CloseHandle(handle)


def _process_is_alive(process_id: int) -> bool:
    if process_id <= 0:
        return False
    if os.name == "nt":
        return _windows_process_is_alive(process_id)
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def _watch_parent(server: uvicorn.Server, parent_process_id: int) -> None:
    while not server.should_exit:
        if not _process_is_alive(parent_process_id):
            logging.getLogger(__name__).warning("Desktop parent process exited")
            server.should_exit = True
            return
        time.sleep(PARENT_CHECK_INTERVAL_SECONDS)


def run() -> None:
    import uvicorn

    from app.config import get_settings
    from app.main import app
    from app.services.desktop_lifecycle import set_shutdown_callback

    runtime_path = _required_path("RADIOLOGY_RUNTIME_FILE")
    log_path = _required_path("RADIOLOGY_LOG_FILE")
    parent_process_id = int(os.environ.get("RADIOLOGY_PARENT_PID", "0"))
    _configure_logging(log_path)

    server_socket = _bind_loopback_socket()
    port = int(server_socket.getsockname()[1])
    config = uvicorn.Config(
        app,
        host=LOOPBACK_HOST,
        port=port,
        log_config=None,
        log_level=get_settings().log_level,
    )
    server = uvicorn.Server(config)
    set_shutdown_callback(lambda: setattr(server, "should_exit", True))
    _write_runtime_file(runtime_path, port)

    if parent_process_id > 0:
        threading.Thread(
            target=_watch_parent,
            args=(server, parent_process_id),
            daemon=True,
            name="desktop-parent-watchdog",
        ).start()

    try:
        server.run(sockets=[server_socket])
    finally:
        set_shutdown_callback(None)
        server_socket.close()
        runtime_path.unlink(missing_ok=True)


def main() -> None:
    try:
        run()
    except Exception:
        log_value = os.environ.get("RADIOLOGY_LOG_FILE", "").strip()
        if log_value:
            log_path = Path(log_value).expanduser().resolve()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as stream:
                traceback.print_exc(file=stream)
        raise


if __name__ == "__main__":
    main()
