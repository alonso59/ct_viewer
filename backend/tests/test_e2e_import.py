"""P1 exit: import the synthetic dataset via the API; warnings match the fixture defects.

TST-07 (R1): SHA-256 of every file under `.fixtures/synthetic` is identical before and after
the full flow (import, re-import, streaming, thumbnails), and no source path is ever opened
for writing (BE-03).
"""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import SYNTHETIC, make_settings
from tools.make_fixtures import DATASET, generate

API = "/api/v1"


def sha_tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def synthetic() -> Path:
    """The repo fixture dir (`make fixtures`); generated if absent."""
    if not (SYNTHETIC / "expected.json").exists():
        generate(SYNTHETIC)
    return SYNTHETIC


@pytest.fixture
def write_guard(synthetic: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Record any write-mode open of a path under the fixture tree (BE-03)."""
    root = str(synthetic.resolve())
    violations: list[str] = []
    real_open, real_os_open = builtins.open, os.open

    def under(p: Any) -> bool:
        try:
            return os.path.realpath(os.fspath(p)).startswith(root)
        except TypeError:
            return False

    def guarded_open(file: Any, mode: str = "r", *a: Any, **k: Any) -> Any:
        if under(file) and any(c in mode for c in "wax+"):
            violations.append(f"open({file}, {mode})")
        return real_open(file, mode, *a, **k)

    def guarded_os_open(path: Any, flags: int, *a: Any, **k: Any) -> int:
        wr = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
        if under(path) and flags & wr:
            violations.append(f"os.open({path}, {flags})")
        return real_os_open(path, flags, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    yield violations


def wait_job(c: TestClient, job_id: str, timeout: float = 60) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job: dict[str, Any] = c.get(f"{API}/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


def import_root(c: TestClient, pid: str, root: Path) -> dict[str, Any]:
    r = c.post(f"{API}/projects/{pid}/imports/preview", json={"root": str(root), "detect": True})
    assert r.status_code == 200, r.text
    preview = r.json()
    r = c.post(f"{API}/projects/{pid}/imports", json={"preview_id": preview["preview_id"]})
    assert r.status_code == 202, r.text
    job = wait_job(c, r.json()["job_id"])
    assert job["status"] == "succeeded", job
    return preview


def all_pages(c: TestClient, url: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = ""
    while True:
        sep = "&" if "?" in url else "?"
        page = c.get(f"{url}{sep}limit=2000&cursor={cursor}").json()
        out += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            return out


def test_import_synthetic_matches_expected(
    synthetic: Path, tmp_path: Path, write_guard: list[str]
) -> None:
    before = sha_tree(synthetic)
    expected = json.loads((synthetic / "expected.json").read_text())
    root = synthetic / DATASET
    app = create_app(make_settings(tmp_path, [root]), inline_jobs=True)
    with TestClient(app) as c:
        pid = c.post(f"{API}/projects", json={"name": "synthetic", "packs": ["ccrcc"]}).json()[
            "project_id"
        ]
        preview = import_root(c, pid, root)
        assert preview["counts"]["cases"] >= 16

        warnings = all_pages(c, f"{API}/projects/{pid}/warnings")
        got = {(w["case_id"], w["code"]) for w in warnings}
        for d in expected["defects"]:
            if d["code"] == "fingerprint_changed":
                continue  # needs a mutation; covered on a copy below
            assert (d["case_id"], d["code"]) in got, d

        # Healthy cases carry no errors; phases are normalized (ART->CMP, VEN->NP, DELAY->EP).
        for case_id in ("case_00001", "case_00002", "case_00003"):
            assert not [w for w in warnings if w["case_id"] == case_id and w["severity"] == "error"]
        case1 = c.get(f"{API}/projects/{pid}/cases/case_00001").json()
        phases = {s["scan_idx"]: s["phase"]["canonical"] for s in case1["scans"]}
        assert phases == {"01": "NC", "02": "CMP", "03": "NP"}

        # IMP-07: upstream exclusion hidden by default.
        cases = all_pages(c, f"{API}/projects/{pid}/cases")
        ids = {x["case_id"] for x in cases}
        assert "case_00022" not in ids and {"case_00001", "case_00023"} <= ids
        excluded = all_pages(c, f"{API}/projects/{pid}/cases?status=excluded_upstream")
        assert "case_00022" in {x["case_id"] for x in excluded}

        # Streaming (BE-04): original bytes, Range, ETag; legacy .npy via NIfTI cache (IMP-10).
        iid = "case_00001.01.complete.-"
        r = c.get(f"{API}/projects/{pid}/items/{iid}/image")
        assert r.status_code == 200
        assert r.content == (root / "nifti/01_case_00001_0000.nii.gz").read_bytes()
        etag = r.headers["etag"]
        assert (
            c.get(
                f"{API}/projects/{pid}/items/{iid}/image", headers={"If-None-Match": etag}
            ).status_code
            == 304
        )
        r = c.get(f"{API}/projects/{pid}/items/{iid}/mask", headers={"Range": "bytes=0-99"})
        assert r.status_code == 206 and len(r.content) == 100
        r = c.get(f"{API}/projects/{pid}/items/case_00023.01.voi.L/image")
        assert r.status_code == 200 and r.content[:2] == b"\x1f\x8b"
        r = c.get(f"{API}/projects/{pid}/items/case_00010.01.complete.-/image")
        assert r.status_code in (404, 409) and r.headers["content-type"].startswith(
            "application/problem+json"
        )

        # IMP-12: thumbnails generated after indexing for complete, active items.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            r = c.get(f"{API}/projects/{pid}/items/{iid}/thumbnail")
            if r.status_code == 200:
                break
            time.sleep(0.1)
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp"

        # IMP-06: re-import keeps item_ids stable.
        import_root(c, pid, root)
        cases2 = all_pages(c, f"{API}/projects/{pid}/cases")
        assert {x["case_id"] for x in cases2} == ids
        assert c.get(f"{API}/projects/{pid}/items/{iid}").status_code == 200

    assert write_guard == []
    assert sha_tree(synthetic) == before


def test_fingerprint_changed_after_mutation(
    data_root: Path, fixtures_copy: Path, tmp_path: Path
) -> None:
    expected = json.loads((fixtures_copy / "expected.json").read_text())
    defect = next(d for d in expected["defects"] if d["code"] == "fingerprint_changed")
    app = create_app(make_settings(tmp_path, [data_root]), inline_jobs=True)
    with TestClient(app) as c:
        pid = c.post(f"{API}/projects", json={"name": "fp", "packs": ["ccrcc"]}).json()[
            "project_id"
        ]
        import_root(c, pid, data_root)
        target = data_root / defect["mutate_after_index"]
        data = bytearray(target.read_bytes())
        data[-8:] = b"MUTATED!"
        target.write_bytes(bytes(data))  # test-only mutation of a *copy*
        import_root(c, pid, data_root)
        codes = {
            w["code"]
            for w in all_pages(c, f"{API}/projects/{pid}/warnings?case_id={defect['case_id']}")
        }
        assert "fingerprint_changed" in codes
