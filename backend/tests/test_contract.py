"""TST-03: API contract — OpenAPI snapshot diff (BE-10) and problem+json errors (BE-08)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.core.errors import SLUGS
from tools.openapi_snapshot import SNAPSHOT, current, render

STREAMING = {"image", "mask", "thumbnail", "events"}
# Binary bodies identified by the segment before a path parameter (API-25 mesh: .../mesh/{label})
BINARY_PARENTS = {"mesh"}


def test_openapi_matches_reviewed_snapshot() -> None:
    assert SNAPSHOT.exists(), "run: python -m tools.openapi_snapshot"
    assert render(current()) == SNAPSHOT.read_text(encoding="utf-8"), (
        "OpenAPI contract changed: review, then `python -m tools.openapi_snapshot` "
        "and `make gen-api`"
    )


def test_every_operation_is_versioned_and_typed() -> None:
    spec = current()
    for path, ops in spec["paths"].items():
        assert path.startswith("/api/v1/"), path
        for method, op in ops.items():
            ok = [c for c in op["responses"] if c.startswith("2")]
            assert ok, f"{method} {path}: no 2xx response"
            segments = path.rsplit("/", 2)
            if segments[-1] in STREAMING or segments[-2] in BINARY_PARENTS:
                continue
            content: dict[str, Any] = op["responses"][ok[0]].get("content", {})
            schema = content.get("application/json", {}).get("schema", {})
            assert schema, f"{method} {path}: untyped 2xx response"


def assert_problem(r: Any, slug: str) -> None:
    assert r.status_code == SLUGS[slug][0], r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["type"] == f"/problems/{slug}"
    assert {"title", "status", "detail", "instance"} <= set(body)


def test_problem_slugs_on_real_endpoints(client: TestClient) -> None:
    api = "/api/v1"
    assert_problem(client.get(f"{api}/projects/01JAAAAAAAAAAAAAAAAAAAAAAA"), "not-found")
    assert_problem(client.get(f"{api}/projects/not-a-ulid"), "not-found")
    assert_problem(client.post(f"{api}/projects", json={"name": ""}), "validation")
    assert_problem(client.get(f"{api}/fs/list", params={"path": "/"}), "path-outside-root")
    assert_problem(client.get(f"{api}/jobs/01JAAAAAAAAAAAAAAAAAAAAAAA"), "not-found")
    pid = client.post(f"{api}/projects", json={"name": "c"}).json()["project_id"]
    assert_problem(client.get(f"{api}/projects/{pid}/cases/case_99999"), "not-found")
    assert_problem(client.get(f"{api}/projects/{pid}/items/case_99999.01.complete.-"), "not-found")
    assert_problem(
        client.post(f"{api}/projects/{pid}/imports/preview", json={"root": "/", "detect": True}),
        "path-outside-root",
    )
