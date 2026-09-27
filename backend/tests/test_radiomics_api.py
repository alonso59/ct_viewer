"""Radiomics over the synthetic fixtures (RAD-01..11, BE-03/06, NFR-15). Inline jobs.

API-30/32/36 are the radiomics routes; validate, estimate and runs go through the task routes
API-43..47 for `radiomics.pyradiomics` (RAD-13, AUD-A4-09), which attach the RAD-* record."""

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
from httpx import Response

from app.core.ids import new_ulid
from tests.test_api_ingest import ctx_of, do_import, wait
from tests.test_contract import assert_problem

pytest.importorskip("radiomics")

API = "/api/v1"
ITEMS = [f"case_{n:05d}.01.complete.-" for n in (30, 31, 32)]
WHO = {"X-Reviewer": "Dr. T"}
TASK = "radiomics.pyradiomics"
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def proj(client: TestClient, data_root: Path) -> str:
    cfg = client.portal.call(ctx_of(client).workspace.create, "rad", "", "CT", ["ccrcc"])  # type: ignore[union-attr]
    pid = str(cfg.project_id)
    do_import(client, pid, data_root)
    return pid


def run_dir(c: TestClient, pid: str, rid: str) -> Path:
    return ctx_of(c).workspace.project_dir(pid) / "radiomics" / "runs" / rid


def task_body(body: dict[str, Any]) -> dict[str, Any]:
    """A radiomics run / estimate body → the task body (`profile_hash` inside `settings`)."""
    settings = dict(body.get("settings") or {})
    if "profile_hash" in body:
        settings["profile_hash"] = body["profile_hash"]
    out = {"settings": settings, "selection": body.get("selection", {})}
    return {**out, "name": body["name"]} if "name" in body else out


def post_run(
    c: TestClient, pid: str, body: dict[str, Any], headers: dict[str, str] | None = WHO
) -> Response:
    """API-45 start of a radiomics run."""
    body = {"task_id": TASK, **task_body(body)}
    return c.post(f"{API}/projects/{pid}/task-runs", json=body, headers=headers)


def post_estimate(c: TestClient, pid: str, body: dict[str, Any]) -> Response:
    """API-44 estimate; the RAD-11 result is `.json()["radiomics"]`."""
    return c.post(f"{API}/projects/{pid}/tasks/{TASK}/estimate", json=task_body(body))


def post_validate(c: TestClient, body: dict[str, Any]) -> Response:
    """API-43 validate; the RAD-04 result is `.json()["radiomics"]`."""
    return c.post(f"{API}/tasks/{TASK}/validate", json=body)


def runs_url(pid: str, rid: str = "") -> str:
    return f"{API}/projects/{pid}/task-runs" + (f"/{rid}" if rid else "")


def features_url(pid: str, rid: str) -> str:
    return f"{API}/projects/{pid}/radiomics/runs/{rid}/features"  # API-36


def get_run(c: TestClient, pid: str, rid: str) -> dict[str, Any]:
    """API-45 detail → the RAD-09 run record."""
    r = c.get(runs_url(pid, rid))
    assert r.status_code == 200, r.text
    return dict(r.json()["radiomics"])


def run_errors(c: TestClient, pid: str, rid: str) -> list[dict[str, Any]]:
    """API-47 errors → the RAD-07 rows."""
    return [e["radiomics"] for e in c.get(f"{runs_url(pid, rid)}/errors").json()]


def start(c: TestClient, pid: str, body: dict[str, Any], *, finish: bool = True) -> dict[str, Any]:
    r = post_run(c, pid, body)
    assert r.status_code == 202, r.text
    started = r.json()
    assert started["status"] in ("queued", "running", "completed", "completed_with_errors")
    if finish:
        wait(c, started["job_id"])
    return get_run(c, pid, started["run_id"])


def sel(items: list[str] = ITEMS, labels: list[int] | None = None) -> dict[str, Any]:
    return {"item_ids": items, "labels": labels or [2]}


# -- API-30 / API-43 ----------------------------------------------------------------------


def test_schema_and_validate_endpoints(client: TestClient) -> None:
    r = client.get(f"{API}/radiomics/schema")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["engine"]["name"] == "pyradiomics" and s["ibsi_map_version"] == "1"
    assert {o["name"] for o in s["options"]} >= {"binWidth", "binCount", "force2D", "distances"}
    assert s["defaults"]["settings"]["binWidth"] == 25.0
    r = post_validate(client, {})
    body = r.json()["radiomics"]
    assert r.status_code == 200 and body["ok"] and body["issues"] == []
    assert body["profile_hash"].startswith("sha256:")
    r = post_validate(
        client, {"settings": {"settings": {"binCount": 8}}, "labels": [], "n_items": 0}
    )
    body = r.json()["radiomics"]
    assert not body["ok"] and body["profile_hash"] is None
    rules = {(i["rule"], tuple(i["loc"])) for i in body["issues"]}
    assert ("bin_xor", ("settings", "binWidth")) in rules
    assert ("nothing", ("labels",)) in rules and ("nothing", ("n_items",)) in rules
    r = post_validate(
        client, {"settings": {"settings": {"normalize": True, "resegmentRange": [-100, 200]}}}
    )
    body = r.json()["radiomics"]
    assert body["ok"] and [i["severity"] for i in body["issues"]] == ["warning"]


def test_retired_aliases_are_gone(client: TestClient, proj: str) -> None:
    """AUD-A4-09: API-31/33/34/35/37 (aliases of API-43..47, RAD-13) are removed; API-30/32/36
    stay the radiomics routes."""
    rid = new_ulid()
    base = f"{API}/projects/{proj}/radiomics"
    for method, url in (
        ("POST", f"{API}/radiomics/validate"),
        ("POST", f"{base}/estimate"),
        ("POST", f"{base}/runs"),
        ("GET", f"{base}/runs"),
        ("GET", f"{base}/runs/{rid}"),
        ("POST", f"{base}/runs/{rid}/cancel"),
        ("POST", f"{base}/runs/{rid}/resume"),
        ("GET", f"{base}/runs/{rid}/errors"),
    ):
        assert client.request(method, url, json={}).status_code in (404, 405), (method, url)
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {p for p in paths if "/radiomics/" in p and "/views/" not in p} == {
        "/api/v1/radiomics/schema",
        "/api/v1/projects/{pid}/radiomics/profiles",
        "/api/v1/projects/{pid}/radiomics/profiles/{phash}",
        "/api/v1/projects/{pid}/radiomics/runs/{rid}/features",
    }


def test_engine_missing_is_server_busy(
    client: TestClient, proj: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.radiomics import engine

    monkeypatch.setattr(engine, "_ENGINES", {})
    monkeypatch.setitem(sys.modules, "app.radiomics.pyradiomics_engine", None)
    assert_problem(client.get(f"{API}/radiomics/schema"), "server-busy")
    assert_problem(post_validate(client, {}), "server-busy")
    assert_problem(post_run(client, proj, {"selection": sel()}), "server-busy")
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


# -- API-44 estimate ----------------------------------------------------------------------


def test_estimate(client: TestClient, proj: str) -> None:
    body = {"selection": {"filter": {"phase": ["NP"]}, "scope": "complete", "labels": [2, 3]}}
    r = post_estimate(client, proj, body)
    assert r.status_code == 200, r.text
    e = r.json()["radiomics"]
    assert e["n_items"] >= 30 and e["n_labels"] == 2
    assert e["n_units"] + e["n_skipped"] == e["n_items"] * 2
    assert len(e["sample_item_ids"]) == 3
    assert e["time_per_item_s"] > 0 and e["estimated_total_s"] > 0 and e["workers"] >= 1
    var = {"filter": {"var": {"grade": ["1"]}}, "scope": "complete", "labels": [2]}
    r = post_estimate(client, proj, {"selection": var})
    assert r.status_code == 200, r.text
    assert 0 < r.json()["radiomics"]["n_items"] < e["n_items"]
    r = post_estimate(
        client, proj, {"selection": {"filter": {"var": {"nope": ["1"]}}, "labels": [2]}}
    )
    assert_problem(r, "validation")
    assert_problem(post_estimate(client, proj, {"selection": {"labels": []}}), "validation")
    r = post_estimate(
        client, proj, {"selection": {"item_ids": ["case_99999.01.complete.-"], "labels": [2]}}
    )
    assert_problem(r, "validation")
    assert r.json()["errors"][0]["loc"] == ["body", "selection", "item_ids", 0]


# -- API-45..47 runs, API-36 exports ------------------------------------------------------


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
    url = runs_url(proj)
    r = post_run(client, proj, {"selection": sel()}, headers=None)
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
    furl = features_url(proj, rid)
    j = client.get(furl).json()
    assert j["shape"] == "long" and j["total"] == 321 and "value" in j["columns"]
    j = client.get(furl, params={"item_id": ITEMS[1]}).json()
    assert j["total"] == 107 and {r["item_id"] for r in j["rows"]} == {ITEMS[1]}
    w = client.get(furl, params={"shape": "wide"}).json()
    assert w["total"] == 3 and "original_firstorder_Mean" in w["columns"]
    assert w["columns"][:9] == [
        "run_id",
        "item_id",
        "case_id",
        "scan_idx",
        "scope",
        "side",
        "phase",
        "phase_at_run",  # PHS-03 join at read time (AUD-A5-04)
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
    assert wt.num_rows == 3 and wt.num_columns == 9 + 107
    r = client.get(furl, params={"format": "parquet"})
    assert pq.read_table(io.BytesIO(r.content)).num_rows == 321
    assert_problem(client.get(furl, params={"format": "xlsx"}), "validation")
    # list / errors / not found
    lst = client.get(url, params={"task": TASK}).json()
    assert len(lst) == 1 and lst[0]["run_id"] == rid and lst[0]["radiomics"]["run_id"] == rid
    assert run_errors(client, proj, rid) == []
    assert_problem(client.get(f"{url}/{new_ulid()}"), "not-found")
    assert_problem(client.get(features_url(proj, "not-a-run")), "not-found")
    # cancel of a finished run is a no-op
    assert client.post(f"{url}/{rid}/cancel").json()["radiomics"]["status"] == "completed"
    assert_problem(client.post(f"{url}/{rid}/resume"), "job-conflict")


def test_per_item_failures_and_skips(client: TestClient, proj: str, data_root: Path) -> None:
    (data_root / "seg" / "01_case_00031.nii.gz").write_bytes(b"not a nifti")  # engine failure
    (data_root / "nifti" / "01_case_00032_0000.nii.gz").unlink()  # input failure
    run = start(client, proj, {"selection": sel(labels=[2, 4])})
    assert run["status"] == "completed_with_errors", run
    assert run["counts"] == {"items": 3, "ok": 1, "failed": 2, "features": 107, "skipped": 3}
    errs = run_errors(client, proj, run["run_id"])
    by = {(e["item_id"], e["label"], e["kind"]): e for e in errs}
    assert len(errs) == 5
    assert all(by[(i, 4, "skipped")]["code"] == "label_absent" for i in ITEMS)
    missing = by[(ITEMS[2], 2, "failed")]
    assert missing["code"] == "input_missing" and missing["error"].endswith(".")
    engine = by[(ITEMS[1], 2, "failed")]  # RAD-07: a plain cause, the engine text in `detail`
    assert engine["code"] != "input_missing" and engine["detail"]
    feats = client.get(features_url(proj, run["run_id"])).json()
    assert {r["item_id"] for r in feats["rows"]} == {ITEMS[0]}
    r = post_run(client, proj, {"selection": sel(labels=[4])})
    assert_problem(r, "validation")  # every selected label absent → nothing to extract


def test_invalid_settings_rejected_at_run_start(client: TestClient, proj: str) -> None:
    body = {"settings": {"image_types": {"LoG": {}}}, "selection": sel()}
    r = post_run(client, proj, body)
    assert_problem(r, "validation")
    assert r.json()["errors"][0]["loc"] == ["body", "settings", "image_types", "LoG", "sigma"]
    # settings and a profile together are refused
    body = {"settings": {"settings": {}}, "profile_hash": "sha256:" + "0" * 64, "selection": sel()}
    r = post_run(client, proj, body)
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
    url = runs_url(proj, run["run_id"])
    try:
        r = client.post(f"{url}/cancel")
        assert r.status_code == 200, r.text
        assert r.json()["radiomics"]["status"] == "cancelled"
        assert not (run_dir(client, proj, run["run_id"]) / "features.parquet").exists()
    finally:
        gate.set()
    r = client.post(f"{url}/resume")
    assert r.status_code == 202, r.text
    wait(client, r.json()["job_id"])
    done = get_run(client, proj, run["run_id"])
    assert done["status"] == "completed" and done["counts"]["ok"] == 3
    assert client.get(features_url(proj, run["run_id"])).json()["total"] == 321


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
    url = runs_url(proj, rid)
    got = get_run(client, proj, rid)
    assert got["status"] == "interrupted" and got["finished_at"]
    assert json.loads((d / "run.json").read_text())["status"] == "interrupted"
    # partial features are readable before compaction
    assert client.get(features_url(proj, rid)).json()["total"] == 214
    r = client.post(f"{url}/resume")
    assert r.status_code == 202, r.text
    info = wait(client, r.json()["job_id"])
    assert info.total == 1  # only the missing part is recomputed (RAD-08)
    done = get_run(client, proj, rid)
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


def test_items_known_not_ready_are_skipped_in_plain_words(client: TestClient, proj: str) -> None:
    """TSK-04 / RAD-07 (AUD-A2-05): no mask or a blocking IMP-08 code → skipped, never failed;
    geometry defects are said in plain words and never suggest raising `geometryTolerance`."""
    bad = {f"case_{n:05d}.01.complete.-": code for n, code in (
        (13, "missing_seg"), (16, "affine_mismatch"), (17, "shape_mismatch"),
    )}  # fmt: skip
    items = [ITEMS[0], *bad]
    est = post_estimate(client, proj, {"selection": sel(items)}).json()["radiomics"]
    assert est["n_units"] == 1 and est["n_skipped"] == 3
    assert est["skipped_by"] == {"missing_seg": 1, "affine_mismatch": 1, "shape_mismatch": 1}
    run = start(client, proj, {"selection": sel(items)})
    assert run["status"] == "completed", run
    assert run["counts"] == {"items": 4, "ok": 1, "failed": 0, "features": 107, "skipped": 3}
    errs = run_errors(client, proj, run["run_id"])
    got = {e["item_id"]: e for e in errs}
    assert {i: (e["kind"], e["code"]) for i, e in got.items()} == {
        i: ("skipped", c) for i, c in bad.items()
    }
    assert "line up" in got[f"case_{16:05d}.01.complete.-"]["error"]
    assert all("geometryTolerance" not in json.dumps(e) for e in errs)
    # the dashboard overview counts them as skipped, not failed (DB, AUD-A2-05)
    r = client.post(
        f"{API}/projects/{proj}/radiomics/runs/{run['run_id']}/views/run-overview", json={}
    )
    ov = r.json()
    assert r.status_code == 200, r.text
    assert ov["n_items_failed"] == 0 and ov["n_items_skipped"] == 3 and ov["n_items_ok"] == 1
    assert {e["kind"] for e in ov["errors"]} == {"skipped"}


def test_engine_errors_map_to_plain_causes() -> None:
    """AUD-A2-05: the PyRadiomics / SimpleITK texts seen on the fixtures map to cause codes."""
    from app.radiomics import causes

    geo = "ValueError: Image/Mask geometry mismatch. Potential fix: increase tolerance using "
    geo += "geometryTolerance, see Documentation:Usage:Customizing the Extraction"
    assert causes.explain(geo) == "affine_mismatch"
    size = "RuntimeError: Exception thrown in SimpleITK LabelStatisticsImageFilter_Execute: "
    size += "sitkImageFilter.cxx:71: Image1 for LabelStatisticsImageFilter doesn't match size "
    size += "[64, 64, 48] vs [64, 64, 40]"
    assert causes.explain(size) == "shape_mismatch"
    assert causes.explain("ValueError: Label (1) not present in mask. Choose from [2]") == (
        "label_absent"
    )
    assert causes.explain("KeyError: 'x'") == "engine"
    assert all("geometryTolerance" not in t for t in causes.TEXT.values())


def test_resume_refuses_changed_inputs(client: TestClient, proj: str, data_root: Path) -> None:
    """RAD-08 / NFR-15 (AUD-A5-14): a unit whose input changed since the run started fails
    with `input_changed` on resume; unchanged units still resume."""
    run = start(client, proj, {"selection": sel()})
    rid = run["run_id"]
    d = run_dir(client, proj, rid)
    rec = json.loads((d / "run.json").read_text())
    rec.update(status="interrupted", finished_at=None)
    (d / "run.json").write_text(json.dumps(rec))
    for iid in ITEMS[1:]:
        (d / "parts" / f"{iid}__2.parquet").unlink()
    (d / "features.parquet").unlink()
    img = data_root / "nifti" / "01_case_00031_0000.nii.gz"
    img.write_bytes(img.read_bytes() + b"\0")  # the image changed after the run started
    url = runs_url(proj, rid)
    r = client.post(f"{url}/resume")
    assert r.status_code == 202, r.text
    wait(client, r.json()["job_id"])
    done = get_run(client, proj, rid)
    assert done["status"] == "completed_with_errors" and done["counts"]["ok"] == 2
    errs = run_errors(client, proj, rid)
    assert [(e["item_id"], e["kind"], e["code"]) for e in errs] == [
        (ITEMS[1], "failed", "input_changed")
    ]
    assert {r["item_id"] for r in client.get(features_url(proj, rid)).json()["rows"]} == {
        ITEMS[0], ITEMS[2]
    }  # fmt: skip


def test_exports_join_the_effective_phase(client: TestClient, proj: str) -> None:
    """PHS-03 at read time (AUD-A5-04): a phase selected after the run shows in the feature
    exports and dashboards; the run's own value stays as `phase_at_run`."""
    run = start(client, proj, {"selection": sel()})
    rid = run["run_id"]
    body = {"case_id": "case_00030", "scan_idx": "01", "value": "CMP"}
    r = client.post(f"{API}/projects/{proj}/phase/events", json=body, headers=WHO)
    assert r.status_code in (200, 201), r.text
    rows = client.get(
        f"{API}/projects/{proj}/radiomics/runs/{rid}/features", params={"shape": "wide"}
    ).json()["rows"]
    by = {r["item_id"]: (r["phase"], r["phase_at_run"]) for r in rows}
    assert by == {ITEMS[0]: ("CMP", "NP"), ITEMS[1]: ("NP", "NP"), ITEMS[2]: ("NP", "NP")}
    dash = f"{API}/projects/{proj}/radiomics/runs/{rid}/views/run-overview"
    ov = client.post(dash, json={}).json()
    assert {p["level"]: p["n"] for p in ov["per_phase"]} == {"CMP": 1, "NP": 2}
    assert ov["phase_changed"] == [
        {"item_id": ITEMS[0], "case_id": "case_00030", "phase": "CMP", "phase_at_run": "NP"}
    ]
    ov = client.post(dash, json={"filters": {"phase": ["CMP"]}}).json()
    assert ov["n_items_ok"] == 1 and ov["n_items_selected"] == 1
