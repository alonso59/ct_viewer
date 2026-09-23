from fastapi.testclient import TestClient

from app.main import app


def test_health_ok() -> None:
    res = TestClient(app).get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["ui_config"]["viewer_max_loaded"] == 3
