"""API-30..37 over the synthetic fixtures (RAD-01..11, BE-03/06, NFR-15). Inline jobs."""

from __future__ import annotations

import builtins
import io
import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from app.core.ids import new_ulid
from tests.test_api_ingest import ctx_of, do_import, wait
from tests.test_contract import assert_problem

pytest.importorskip("radiomics")

API = "/api/v1"
ITEMS = [f"case_{n:05d}.01.complete.-" for n in (30, 31, 32)]
WHO = {"X-Reviewer": "Dr. T"}
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def proj(client: TestClient, data_root: Path) -> str:
    cfg = client.portal.call(ctx_of(client).workspace.create, "rad")  # type: ignore[union-attr]
    pid = str(cfg.project_id)
    do_import(client, pid, data_root)
    return pid


def run_dir(c: TestClient, pid: str, rid: str) -> Path:
    return ctx_of(c).workspace.project_dir(pid) / "radiomics" / "runs" / rid


def start(c: TestClient, pid: str, body: dict[str, Any], *, finish: bool = True) -> dict[str, Any]:
    r = c.post(f"{API}/projects/{pid}/radiomics/runs", json=body, headers=WHO)
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] in ("queued", "running", "completed", "completed_with_errors")
    if finish:
        wait(c, run["job_id"])
        run = c.get(f"{API}/projects/{pid}/radiomics/runs/{run['run_id']}").json()
    return run


def sel(items: list[str] = ITEMS, labels: list[int] | None = None) -> dict[str, Any]:
    return {"item_ids": items, "labels": labels or [2]}


# -- API-30/31 ----------------------------------------------------------------------------


def test_schema_and_validate_endpoints(client: TestClient) -> None:
    r = client.get(f"{API}/radiomics/schema")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["engine"]["name"] == "pyradiomics" and s["ibsi_map_version"] == "1"
    assert {o["name"] for o in s["options"]} >= {"binWidth", "binCount", "force2D", "distances"}
    assert s["defaults"]["settings"]["binWidth"] == 25.0
    r = client.post(f"{API}/radiomics/validate", json={})
    body = r.json()
    assert r.status_code == 200 and body["ok"] and body["issues"] == []
    assert body["profile_hash"].startswith("sha256:")
    r = client.post(
        f"{API}/radiomics/validate",
        json={"settings": {"settings": {"binCount": 8}}, "labels": [], "n_items": 0},
    )
    body = r.json()
    assert not body["ok"] and body["profile_hash"] is None
    rules = {(i["rule"], tuple(i["loc"])) for i in body["issues"]}
    assert ("bin_xor", ("settings", "binWidth")) in rules
    assert ("nothing", ("labels",)) in rules and ("nothing", ("n_items",)) in rules
    r = client.post(
        f"{API}/radiomics/validate",
        json={"settings": {"settings": {"normalize": True, "resegmentRange": [-100, 200]}}},
    )
    body = r.json()
    assert body["ok"] and [i["severity"] for i in body["issues"]] == ["warning"]


def test_engine_missing_is_server_busy(
    client: TestClient, proj: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.radiomics import engine

    monkeypatch.setattr(engine, "_ENGINES", {})
    monkeypatch.setitem(sys.modules, "app.radiomics.pyradiomics_engine", None)
    assert_problem(client.get(f"{API}/radiomics/schema"), "server-busy")
    assert_problem(client.post(f"{API}/radiomics/validate", json={}), "server-busy")
    r = client.post(f"{API}/projects/{proj}/radiomics/runs", json={"selection": sel()}, headers=WHO)
    assert_problem(r, "server-busy")
    assert client.get(f"{API}/projects/{proj}/radiomics/profiles").status_code == 200


def test_app_imports_without_engine() -> None:
    code = (
        "import sys; sys.modules['radiomics'] = None; sys.modules['SimpleITK'] = None\n"
        "import app.main, app.api.v1.radiomics, app.radiomics.service, app.radiomics.worker\n"
        "assert 'radiomics' not in [m for m, v in sys.modules.items() if v is not None]\n"
    )
    subprocess.run([sys.executable, "-c", code], cwd=BACKEND, check=True)


# -- API-32 profiles ----------------------------------------------------------------------


def test_profiles_crud(client: TestClient, proj: str) -> None:
    url = f"{API}/projects/{proj}/radiomics/profiles"
    body = {"name": "Tumor bw10", "settings": {"settings": {"binWidth": 10}}}
    r = client.post(url, json=body)
    assert r.status_code == 201, r.text
    prof = r.json()
    h = prof["profile_hash"]
    assert h.startswith("sha256:") and prof["engine"]["major"] == "3"
    assert prof["settings"]["settings"]["binWidth"] == 10.0  # normalized snapshot
    pdir = ctx_of(client).workspace.project_dir(proj) / "radiomics" / "profiles"
    assert (pdir / f"{h.split(':')[1]}.json").is_file()
    # identical settings (even written differently) → the same profile (content-addressed)
    same = {"name": "other name", "settings": {"settings": {"binWidth": 10.0, "padDistance": 5}}}
    r = client.post(url, json=same)
    assert r.status_code == 200 and r.json()["profile_hash"] == h
    assert r.json()["name"] == "Tumor bw10"
    r = client.post(url, json={"name": "defaults"})
    assert r.status_code == 201 and r.json()["profile_hash"] != h
    r = client.get(url)
    assert [p["name"] for p in r.json()["items"]] == ["defaults", "Tumor bw10"]
    r = client.patch(f"{url}/{h}", json={"name": "Renamed"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
    hexonly = h.split(":")[1]
    assert client.patch(f"{url}/{hexonly}", json={"name": "Again"}).json()["name"] == "Again"
    r = client.delete(f"{url}/{h}")
    assert r.status_code == 200 and [p["name"] for p in r.json()["items"]] == ["defaults"]
    assert_problem(client.delete(f"{url}/{h}"), "not-found")
    assert_problem(client.patch(f"{url}/sha256:zz", json={"name": "x"}), "not-found")
    r = client.post(url, json={"name": "bad", "settings": {"settings": {"binWidth": -1}}})
    assert_problem(r, "validation")
    assert r.json()["errors"][0]["loc"] == ["body", "settings", "settings", "binWidth"]


# -- API-33 estimate ----------------------------------------------------------------------


def test_estimate(client: TestClient, proj: str) -> None:
    url = f"{API}/projects/{proj}/radiomics/estimate"
    body = {"selection": {"filter": {"phase": ["NP"]}, "scope": "complete", "labels": [2, 3]}}
    r = client.post(url, json=body)
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["n_items"] >= 30 and e["n_labels"] == 2
    assert e["n_units"] + e["n_skipped"] == e["n_items"] * 2
    assert len(e["sample_item_ids"]) == 3
    assert e["time_per_item_s"] > 0 and e["estimated_total_s"] > 0 and e["workers"] >= 1
    r = client.post(
        url,
        json={
            "selection": {"filter": {"var": {"grade": ["1"]}}, "scope": "complete", "labels": [2]}
        },
    )
    assert r.status_code == 200, r.text
    assert 0 < r.json()["n_items"] < e["n_items"]
    r = client.post(url, json={"selection": {"filter": {"var": {"nope": ["1"]}}, "labels": [2]}})
    assert_problem(r, "validation")
    assert_problem(client.post(url, json={"selection": {"labels": []}}), "validation")
    r = client.post(
        url, json={"selection": {"item_ids": ["case_99999.01.complete.-"], "labels": [2]}}
    )
    assert_problem(r, "validation")
    assert r.json()["errors"][0]["loc"] == ["body", "selection", "item_ids", 0]


# -- API-34..37 runs ----------------------------------------------------------------------


def _write_guard(root: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail any write-mode open under the data root (BE-03, R1)."""
    bad: list[str] = []
    real = builtins.open
    root_s = str(root.resolve())

    def guarded(file: Any, mode: str = "r", *a: Any, **k: Any) -> Any:
        writing = isinstance(file, str | os.PathLike) and any(ch in mode for ch in "wax+")
        if writing and os.path.realpath(os.fspath(file)).startswith(root_s):
            bad.append(os.fspath(file))
        return real(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded)
    monkeypatch.setattr(io, "open", guarded)
    return bad


def test_run_end_to_end_outputs(
    client: TestClient, proj: str, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"{API}/projects/{proj}/radiomics/runs"
    r = client.post(url, json={"selection": sel()})
    assert_problem(r, "reviewer-required")
    bad = _write_guard(data_root, monkeypatch)
    run = start(client, proj, {"name": "baseline", "selection": sel()})
    assert bad == []
    rid = run["run_id"]
    assert run["status"] == "completed", run
    d = run_dir(client, proj, rid)
    rec = json.loads((d / "run.json").read_text())
    assert not (d / "run.json.tmp").exists()
    assert rec["reviewer"] == "Dr. T" and rec["name"] == "baseline"
    assert rec["ibsi_map_version"] == "1" and rec["profile_hash"].startswith("sha256:")
    assert rec["engine"]["name"] == "pyradiomics" and set(rec["engine"]["deps"]) >= {
        "SimpleITK", "numpy", "PyWavelets",
    }  # fmt: skip
    assert rec["selection"] == {
        "scope": None, "labels": [2], "filter": None, "item_ids": ITEMS, "seg_id": "imported"
    }  # fmt: skip
    assert [i["item_id"] for i in rec["inputs"]] == ITEMS and rec["inputs"][0]["image_fp"]
    assert all(not str(v).startswith("/") for i in rec["inputs"] for v in i.values())
    assert rec["counts"] == {"items": 3, "ok": 3, "failed": 0, "features": 107, "skipped": 0}
    assert rec["created_at"] and rec["started_at"] and rec["finished_at"]
    assert rec["settings"]["settings"]["binWidth"] == 25.0
    # long parquet on disk
    t = pq.read_table(d / "features.parquet")
    assert t.column_names == [
        "run_id", "item_id", "case_id", "scan_idx", "scope", "side", "phase", "label",
        "image_type", "feature_class", "feature", "value", "ibsi_code", "ibsi_status",
    ]  # fmt: skip
    assert t.schema.field("value").type == pa.float64() and t.num_rows == 3 * 107
    rows = t.to_pylist()
    assert {r["run_id"] for r in rows} == {rid} and {r["phase"] for r in rows} == {"NP"}
    contrast = next(r for r in rows if r["feature"] == "Contrast" and r["feature_class"] == "glcm")
    assert contrast["ibsi_code"] == "ACUI" and contrast["ibsi_status"] == "compliant"
    assert "grade" not in t.column_names and "score" not in t.column_names  # no study vars
    diag = pq.read_table(d / "diagnostics.parquet").to_pylist()
    assert len(diag) == 3 and all(x["voxel_count"] > 0 and x["image_hash"] for x in diag)
    assert {"bbox", "spacing", "mask_hash"} <= set(diag[0])
    # exports (API-36)
    furl = f"{url}/{rid}/features"
    j = client.get(furl).json()
    assert j["shape"] == "long" and j["total"] == 321 and "value" in j["columns"]
    j = client.get(furl, params={"item_id": ITEMS[1]}).json()
    assert j["total"] == 107 and {r["item_id"] for r in j["rows"]} == {ITEMS[1]}
    w = client.get(furl, params={"shape": "wide"}).json()
    assert w["total"] == 3 and "original_firstorder_Mean" in w["columns"]
    assert w["columns"][:8] == [
        "run_id",
        "item_id",
        "case_id",
        "scan_idx",
        "scope",
        "side",
        "phase",
        "label",
    ]
    r = client.get(furl, params={"format": "csv", "shape": "wide"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text.count("\n") == 4 and "original_glcm_Contrast" in r.text.splitlines()[0]
    r = client.get(furl, params={"format": "csv"})
    assert r.text.count("\n") == 322
    r = client.get(furl, params={"format": "parquet", "shape": "wide"})
    assert r.headers["content-type"] == "application/vnd.apache.parquet"
    wt = pq.read_table(io.BytesIO(r.content))
    assert wt.num_rows == 3 and wt.num_columns == 8 + 107
    r = client.get(furl, params={"format": "parquet"})
    assert pq.read_table(io.BytesIO(r.content)).num_rows == 321
    assert_problem(client.get(furl, params={"format": "xlsx"}), "validation")
    # list / errors / not found
    lst = client.get(url).json()
    assert lst["total"] == 1 and lst["items"][0]["run_id"] == rid
    assert client.get(f"{url}/{rid}/errors").json()["total"] == 0
    assert_problem(client.get(f"{url}/{new_ulid()}"), "not-found")
    assert_problem(client.get(f"{url}/not-a-run/features"), "not-found")
    # cancel of a finished run is a no-op
    assert client.post(f"{url}/{rid}/cancel").json()["status"] == "completed"
    assert_problem(client.post(f"{url}/{rid}/resume"), "job-conflict")


def test_per_item_failures_and_skips(client: TestClient, proj: str, data_root: Path) -> None:
    (data_root / "seg" / "01_case_00031.nii.gz").write_bytes(b"not a nifti")  # engine failure
    (data_root / "nifti" / "01_case_00032_0000.nii.gz").unlink()  # input failure
    run = start(client, proj, {"selection": sel(labels=[2, 4])})
    assert run["status"] == "completed_with_errors", run
    assert run["counts"] == {"items": 3, "ok": 1, "failed": 2, "features": 107, "skipped": 3}
    errs = client.get(f"{API}/projects/{proj}/radiomics/runs/{run['run_id']}/errors").json()
    by = {(e["item_id"], e["label"], e["kind"]): e["error"] for e in errs["items"]}
    assert errs["total"] == 5
    assert all((i, 4, "skipped") in by for i in ITEMS)
    assert "input:" in by[(ITEMS[2], 2, "failed")]
    assert (ITEMS[1], 2, "failed") in by and "input:" not in by[(ITEMS[1], 2, "failed")]
    feats = client.get(f"{API}/projects/{proj}/radiomics/runs/{run['run_id']}/features").json()
    assert {r["item_id"] for r in feats["rows"]} == {ITEMS[0]}
    r = client.post(
        f"{API}/projects/{proj}/radiomics/runs", json={"selection": sel(labels=[4])}, headers=WHO
    )
    assert_problem(r, "validation")  # every selected label absent → nothing to extract


def test_invalid_settings_rejected_at_run_start(client: TestClient, proj: str) -> None:
    body = {"settings": {"image_types": {"LoG": {}}}, "selection": sel()}
    r = client.post(f"{API}/projects/{proj}/radiomics/runs", json=body, headers=WHO)
    assert_problem(r, "validation")
    assert r.json()["errors"][0]["loc"] == ["body", "settings", "image_types", "LoG", "sigma"]
    body = {"settings": {}, "profile_hash": "sha256:" + "0" * 64, "selection": sel()}
    r = client.post(f"{API}/projects/{proj}/radiomics/runs", json=body, headers=WHO)
    assert_problem(r, "validation")


def _gate(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    from app.radiomics import worker

    gate = threading.Event()
    real: Callable[[dict[str, Any]], dict[str, Any]] = worker.extract_unit

    def gated(task: dict[str, Any]) -> dict[str, Any]:
        gate.wait(20)
        return real(task)

    monkeypatch.setattr(worker, "extract_unit", gated)
    return gate


def test_cancel_then_resume(client: TestClient, proj: str, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _gate(monkeypatch)
    run = start(client, proj, {"selection": sel()}, finish=False)
    url = f"{API}/projects/{proj}/radiomics/runs/{run['run_id']}"
    try:
        r = client.post(f"{url}/cancel")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "cancelled"
        assert not (run_dir(client, proj, run["run_id"]) / "features.parquet").exists()
    finally:
        gate.set()
    r = client.post(f"{url}/resume")
    assert r.status_code == 202, r.text
    wait(client, r.json()["job_id"])
    done = client.get(url).json()
    assert done["status"] == "completed" and done["counts"]["ok"] == 3
    assert client.get(f"{url}/features").json()["total"] == 321


def test_interrupted_detection_and_resume_skips_parts(client: TestClient, proj: str) -> None:
    run = start(client, proj, {"selection": sel()})
    rid = run["run_id"]
    d = run_dir(client, proj, rid)
    parts = sorted((d / "parts").glob("*.parquet"))
    assert [p.name for p in parts] == [f"{i}__2.parquet" for i in ITEMS]
    # simulate a server restart mid-run: status running, job unknown to this process
    rec = json.loads((d / "run.json").read_text())
    rec.update(status="running", job_id=new_ulid(), finished_at=None)
    (d / "run.json").write_text(json.dumps(rec))
    parts[1].unlink()
    (d / "features.parquet").unlink()
    kept = {p.name: p.stat().st_mtime_ns for p in (parts[0], parts[2])}
    url = f"{API}/projects/{proj}/radiomics/runs/{rid}"
    got = client.get(url).json()
    assert got["status"] == "interrupted" and got["finished_at"]
    assert json.loads((d / "run.json").read_text())["status"] == "interrupted"
    # partial features are readable before compaction
    assert client.get(f"{url}/features").json()["total"] == 214
    r = client.post(f"{url}/resume")
    assert r.status_code == 202, r.text
    info = wait(client, r.json()["job_id"])
    assert info.total == 1  # only the missing part is recomputed (RAD-08)
    done = client.get(url).json()
    assert done["status"] == "completed" and done["counts"]["ok"] == 3
    assert {p.name: p.stat().st_mtime_ns for p in (parts[0], parts[2])} == kept
    assert parts[1].is_file() and (d / "features.parquet").is_file()


def test_reproducibility_same_profile(client: TestClient, proj: str) -> None:
    """NFR-15: the same profile on unchanged inputs gives identical features (bitwise)."""
    r = client.post(f"{API}/projects/{proj}/radiomics/profiles", json={"name": "default"})
    h = r.json()["profile_hash"]
    body = {"profile_hash": h, "selection": sel(labels=[2, 3])}
    a = start(client, proj, body)
    b = start(client, proj, body)
    assert a["profile_hash"] == b["profile_hash"] == h and a["name"] == "default"
    ta = pq.read_table(run_dir(client, proj, a["run_id"]) / "features.parquet")
    tb = pq.read_table(run_dir(client, proj, b["run_id"]) / "features.parquet")
    assert ta.num_rows == tb.num_rows == 3 * 2 * 107
    assert ta.drop(["run_id"]).equals(tb.drop(["run_id"]))
    va = ta["value"].to_numpy()
    vb = tb["value"].to_numpy()
    assert np.array_equal(va.view(np.uint64), vb.view(np.uint64))  # bitwise
