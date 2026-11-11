"""ADR-0055 §4: a session credential gates every request; without one nothing changes."""

from __future__ import annotations

import importlib.util
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import session
from app.main import create_app
from tests.conftest import make_settings

CREDENTIAL = "c" * 43


@pytest.fixture
def gated(tmp_path: Path) -> Iterator[TestClient]:
    secret = tmp_path / "credential"
    secret.write_text(CREDENTIAL + "\n")
    settings = make_settings(tmp_path).model_copy(update={"session_credential_file": secret})
    with TestClient(create_app(settings, inline_jobs=True), follow_redirects=False) as client:
        yield client


def sign_in(client: TestClient, credential: str = CREDENTIAL) -> int:
    return client.post("/sign-in", data={"credential": credential}).status_code


def test_no_credential_file_means_no_gate(client: TestClient) -> None:
    assert client.get("/api/v1/projects").status_code == 200
    assert client.get("/sign-in").status_code == 404


def test_only_health_and_sign_in_are_open(gated: TestClient) -> None:
    assert gated.get("/api/v1/health").status_code == 200
    assert gated.get("/sign-in").status_code == 200
    refused = gated.get("/api/v1/projects")
    assert refused.status_code == 401
    assert refused.json()["type"] == "/problems/session-required"
    assert gated.post("/api/v1/projects", json={}).status_code == 401
    page = gated.get("/")
    assert (page.status_code, page.headers["location"]) == (303, "/sign-in")


def test_sign_in_sets_a_protected_cookie_and_opens_the_api(gated: TestClient) -> None:
    response = gated.post("/sign-in", data={"credential": CREDENTIAL})
    assert (response.status_code, response.headers["location"]) == (303, "/")
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" not in cookie
    assert CREDENTIAL not in response.headers["set-cookie"]
    assert gated.get("/api/v1/projects").status_code == 200


def test_cookie_is_secure_over_https(tmp_path: Path) -> None:
    secret = tmp_path / "credential"
    secret.write_text(CREDENTIAL)
    settings = make_settings(tmp_path).model_copy(update={"session_credential_file": secret})
    app = create_app(settings, inline_jobs=True)
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
        response = client.post("/sign-in", data={"credential": CREDENTIAL})
    assert "secure" in response.headers["set-cookie"].lower()


def test_scripts_send_the_credential_as_a_bearer_token(gated: TestClient) -> None:
    ok = gated.get("/api/v1/projects", headers={"Authorization": f"Bearer {CREDENTIAL}"})
    assert ok.status_code == 200
    wrong = gated.get("/api/v1/projects", headers={"Authorization": "Bearer " + "x" * 43})
    assert wrong.status_code == 401


def test_a_forged_cookie_is_refused(gated: TestClient) -> None:
    gated.cookies.set(session.COOKIE, "forged")
    assert gated.get("/api/v1/projects").status_code == 401


def test_cross_origin_state_change_is_refused_even_with_a_session(gated: TestClient) -> None:
    assert sign_in(gated) == 303
    foreign = gated.post("/api/v1/projects", json={}, headers={"Origin": "http://evil.example"})
    assert foreign.status_code == 403
    assert foreign.json()["type"] == "/problems/cross-origin"
    own = gated.post("/api/v1/projects", json={}, headers={"Origin": "http://testserver"})
    assert own.status_code not in (401, 403)
    assert (
        gated.get("/api/v1/projects", headers={"Origin": "http://evil.example"}).status_code == 200
    )


def test_wrong_codes_are_throttled(gated: TestClient) -> None:
    for _ in range(session.MAX_FAILURES):
        assert sign_in(gated, "wrong") == 401
    assert sign_in(gated) == 429
    assert gated.get("/api/v1/projects").status_code == 401


def test_a_short_credential_refuses_to_start(tmp_path: Path) -> None:
    secret = tmp_path / "credential"
    secret.write_text("short")
    settings = make_settings(tmp_path).model_copy(update={"session_credential_file": secret})
    with pytest.raises(ValueError, match="at least"):
        create_app(settings, inline_jobs=True)


def test_ctflow_sends_the_session_code_of_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str | None] = []

    class Api(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())

        def log_message(self, *args: object) -> None:
            pass

    secret = tmp_path / "credential"
    secret.write_text(CREDENTIAL + "\n")
    monkeypatch.setenv("RW_CREDENTIAL_FILE", str(secret))
    path = Path(__file__).resolve().parents[2] / "scripts" / "ctflow.py"
    spec = importlib.util.spec_from_file_location("ctflow_session", path)
    assert spec is not None and spec.loader is not None
    ctflow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ctflow)
    server = HTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=server.handle_request, daemon=True).start()
    client = ctflow.Client(f"http://127.0.0.1:{server.server_port}", None, None)
    assert client.call("GET", "/health") == {"status": "ok"}
    server.server_close()
    assert seen == [f"Bearer {CREDENTIAL}"]
