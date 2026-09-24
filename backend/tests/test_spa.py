"""SPA static serving from STATIC_ROOT (BE ARCHITECTURE `main.py`, OPS-01)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import make_settings

INDEX = '<!doctype html><div id="root"></div>'


def _spa_settings(tmp_path: Path) -> Settings:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(INDEX)
    (static / "assets" / "app-abc123.js").write_text("console.log(1)")
    (static / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside")
    return make_settings(tmp_path).model_copy(update={"static_root": static})


def test_spa_index_assets_and_client_route_fallback(tmp_path: Path) -> None:
    with TestClient(create_app(_spa_settings(tmp_path), inline_jobs=True)) as c:
        r = c.get("/")
        assert r.status_code == 200 and r.text == INDEX
        assert r.headers["cache-control"] == "no-cache"
        assert c.get("/assets/app-abc123.js").text == "console.log(1)"
        assert c.get("/favicon.svg").text == "<svg/>"
        r = c.get("/p/01JAAAAAAAAAAAAAAAAAAAAAAA/case/case_00001?item=x")
        assert r.status_code == 200 and r.text == INDEX
        assert r.headers["cache-control"] == "no-cache"
        assert c.get("/%2E%2E/secret.txt").text == INDEX  # never escapes STATIC_ROOT
        assert c.get("/assets/missing.js").status_code == 404
        # API routes win over the catch-all, which is registered last
        assert c.get("/api/v1/health").json()["status"] == "ok"


def test_api_paths_never_fall_back_to_the_spa(tmp_path: Path) -> None:
    with TestClient(create_app(_spa_settings(tmp_path), inline_jobs=True)) as c:
        for path in ("/api", "/api/", "/api/v1/no-such-endpoint", "/api/v2/x"):
            r = c.get(path)
            assert r.status_code == 404, path
            assert r.headers["content-type"].startswith("application/problem+json"), path
            assert "root" not in r.text


def test_no_spa_without_index_html(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"static_root": tmp_path / "none"})
    app = create_app(settings, inline_jobs=True)
    assert not any(getattr(r, "path", "") == "/{path:path}" for r in app.routes)
    with TestClient(app) as c:
        assert c.get("/").status_code == 404
        assert c.get("/p/x").status_code == 404
