"""API-10 folder browser limited to ALLOWED_DATA_ROOTS (IMP-01, OPS-04; TST-03)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.v1 import fs

API = "/api/v1/fs/list"


def assert_problem(res: Any, status: int, slug: str) -> None:
    assert res.status_code == status, res.text
    assert res.headers["content-type"].startswith("application/problem+json")
    assert res.json()["type"] == f"/problems/{slug}"


def test_roots_listing(client: TestClient, data_root: Path) -> None:
    body = client.post(API, json={}).json()
    assert body["path"] is None and body["parent"] is None
    [root] = body["entries"]
    assert root["path"] == str(data_root.resolve())
    assert root["kind"] == "dir" and root["has_metadata"] is True


def test_list_dir(client: TestClient, data_root: Path) -> None:
    real = data_root.resolve()
    (real / ".hidden").write_text("x")
    (real / "b_file.txt").write_text("abc")
    (real / "A_file.txt").write_text("a")
    body = client.post(API, json={"path": str(data_root)}).json()
    assert body["path"] == str(real) and body["parent"] is None and body["truncated"] is False
    names = [e["name"] for e in body["entries"]]
    kinds = [e["kind"] for e in body["entries"]]
    assert ".hidden" not in names
    assert kinds == sorted(kinds)  # dirs before files
    dirs = [e["name"] for e in body["entries"] if e["kind"] == "dir"]
    assert dirs == sorted(dirs, key=str.casefold) and {"nifti", "seg", "voi"} <= set(dirs)
    files = [e for e in body["entries"] if e["kind"] == "file"]
    assert [f["name"] for f in files] == sorted((f["name"] for f in files), key=str.casefold)
    b = next(f for f in files if f["name"] == "b_file.txt")
    assert b["size"] == 3 and b["has_metadata"] is False
    nifti = next(e for e in body["entries"] if e["name"] == "nifti")
    assert nifti["size"] is None
    sub = client.post(API, json={"path": nifti["path"]}).json()
    assert sub["parent"] == str(real)


def test_errors(client: TestClient, data_root: Path, fixtures_copy: Path) -> None:
    assert_problem(client.post(API, json={"path": "relative"}), 422, "validation")
    outside = str(fixtures_copy / "outside")
    assert_problem(client.post(API, json={"path": outside}), 403, "path-outside-root")
    escape = str(data_root / ".." / "outside")
    assert_problem(client.post(API, json={"path": escape}), 403, "path-outside-root")
    assert_problem(client.post(API, json={"path": str(data_root / "nope")}), 404, "not-found")
    meta = str(data_root / "metadata.jsonl")
    assert_problem(client.post(API, json={"path": meta}), 404, "not-found")


def test_symlink_escape_omitted(client: TestClient, data_root: Path, fixtures_copy: Path) -> None:
    os.symlink(fixtures_copy / "outside", data_root / "link_out")
    os.symlink(data_root / "nifti", data_root / "link_in")
    names = [e["name"] for e in client.post(API, json={"path": str(data_root)}).json()["entries"]]
    assert "link_out" not in names and "link_in" in names
    res = client.post(API, json={"path": str(data_root / "link_out")})
    assert_problem(res, 403, "path-outside-root")


def test_truncated(client: TestClient, data_root: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(fs, "MAX_ENTRIES", 2)
    body = client.post(API, json={"path": str(data_root)}).json()
    assert body["truncated"] is True and len(body["entries"]) == 2


def test_paths_travel_in_the_body_not_the_url(client: TestClient, data_root: Path) -> None:
    """AUD-A5-16, NFR-17: a browsed folder never lands in a URL (access logs, history)."""
    assert client.get(API, params={"path": str(data_root)}).status_code == 405
    assert client.post(API, json={"path": str(data_root)}).json()["path"] == str(
        data_root.resolve()
    )
