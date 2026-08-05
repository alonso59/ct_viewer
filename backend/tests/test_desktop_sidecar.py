from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.desktop_sidecar import (
    LOOPBACK_HOST,
    _bind_loopback_socket,
    _process_is_alive,
    _write_runtime_file,
)
from app.main import create_app
from app.services.desktop_lifecycle import request_shutdown, set_shutdown_callback


def test_sidecar_binds_dynamic_loopback_port() -> None:
    server_socket = _bind_loopback_socket()
    try:
        host, port = server_socket.getsockname()
        assert host == LOOPBACK_HOST
        assert port > 0
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            assert client.connect_ex((host, port)) == 0
    finally:
        server_socket.close()


def test_sidecar_port_cannot_be_bound_twice() -> None:
    server_socket = _bind_loopback_socket()
    second_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError):
            second_socket.bind(server_socket.getsockname())
    finally:
        second_socket.close()
        server_socket.close()


def test_runtime_handshake_never_contains_token(tmp_path: Path) -> None:
    runtime_path = tmp_path / "backend-runtime.json"

    _write_runtime_file(runtime_path, 49152)

    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {
        "pid": os.getpid(),
        "port": 49152,
    }
    assert "token" not in runtime_path.read_text(encoding="utf-8").lower()


def test_parent_watchdog_recognizes_current_process() -> None:
    assert _process_is_alive(os.getpid()) is True


def test_desktop_shutdown_callback_is_optional() -> None:
    calls: list[str] = []
    set_shutdown_callback(None)
    assert request_shutdown() is False

    set_shutdown_callback(lambda: calls.append("stop"))
    try:
        assert request_shutdown() is True
    finally:
        set_shutdown_callback(None)

    assert calls == ["stop"]


def test_desktop_api_auth_cors_and_private_lifecycle(monkeypatch) -> None:
    monkeypatch.setenv("RADIOLOGY_DESKTOP_RUNTIME", "true")
    monkeypatch.setenv("RADIOLOGY_UI_TOKEN", "ephemeral-token")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://tauri.localhost,http://localhost:5173",
    )
    calls: list[str] = []
    set_shutdown_callback(lambda: calls.append("stop"))
    try:
        client = TestClient(create_app())
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/workspace").status_code == 401
        assert client.get("/api/desktop/ready").status_code == 401
        assert (
            client.get(
                "/api/desktop/ready",
                headers={"Authorization": "Bearer ephemeral-token"},
            ).json()
            == {"status": "ready"}
        )

        allowed_preflight = client.options(
            "/api/workspace",
            headers={
                "Origin": "http://tauri.localhost",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert allowed_preflight.status_code == 200
        assert (
            allowed_preflight.headers["access-control-allow-origin"]
            == "http://tauri.localhost"
        )

        rejected_preflight = client.options(
            "/api/workspace",
            headers={
                "Origin": "https://example.invalid",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert rejected_preflight.status_code == 400
        assert "access-control-allow-origin" not in rejected_preflight.headers

        assert client.post("/api/desktop/shutdown").status_code == 401
        response = client.post(
            "/api/desktop/shutdown",
            headers={"Authorization": "Bearer ephemeral-token"},
        )
        assert response.status_code == 200
        assert calls == ["stop"]
        schema_paths = client.get("/openapi.json").json()["paths"]
        assert "/api/desktop/ready" not in schema_paths
        assert "/api/desktop/shutdown" not in schema_paths
    finally:
        set_shutdown_callback(None)


def test_web_app_does_not_register_desktop_lifecycle(monkeypatch) -> None:
    monkeypatch.delenv("RADIOLOGY_DESKTOP_RUNTIME", raising=False)
    monkeypatch.delenv("RADIOLOGY_UI_TOKEN", raising=False)

    client = TestClient(create_app())

    assert client.get("/api/desktop/ready").status_code == 404
    assert client.post("/api/desktop/shutdown").status_code in {404, 405}
    assert "/api/desktop/ready" not in client.get("/openapi.json").json()["paths"]
    assert "/api/desktop/shutdown" not in client.get("/openapi.json").json()["paths"]
