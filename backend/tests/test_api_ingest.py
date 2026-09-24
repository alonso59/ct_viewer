"""TST-03: API-11..14, API-20..22 over the synthetic fixtures (preview → commit → index job)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.context import AppContext
from app.ingest.models import IndexStatus
from app.jobs.types import JobInfo

API = "/api/v1"


def ctx_of(c: TestClient) -> AppContext:
    ctx: AppContext = c.app.state.ctx  # type: ignore[attr-defined]
    return ctx


@pytest.fixture
def pid(client: TestClient) -> str:
    cfg = client.portal.call(ctx_of(client).workspace.create, "ingest")  # type: ignore[union-attr]
    return str(cfg.project_id)


def wait(c: TestClient, job_id: str) -> JobInfo:
    info: JobInfo = c.portal.call(ctx_of(c).jobs.wait, job_id, 60)  # type: ignore[union-attr]
    return info


def do_import(c: TestClient, pid: str, root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    r = c.post(f"{API}/projects/{pid}/imports/preview", json={"root": str(root)})
    assert r.status_code == 200, r.text
    pv = r.json()
    r = c.post(f"{API}/projects/{pid}/imports", json={"preview_id": pv["preview_id"]})
    assert r.status_code == 202, r.text
    commit = r.json()
    assert wait(c, commit["job_id"]).status == "succeeded"
    return pv, commit


def pages(c: TestClient, url: str, limit: int = 2000) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = ""
    while True:
        sep = "&" if "?" in url else "?"
        r = c.get(f"{url}{sep}limit={limit}&cursor={cursor}")
        assert r.status_code == 200, r.text
        out += r.json()["items"]
        cursor = r.json()["next_cursor"]
        if not cursor:
            return out


@pytest.fixture
def imported(
    client: TestClient, pid: str, data_root: Path
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    pv, commit = do_import(client, pid, data_root)
    return pid, pv, commit


def test_preview_detect(client: TestClient, pid: str, data_root: Path) -> None:
    r = client.post(f"{API}/projects/{pid}/imports/preview", json={"root": str(data_root)})
    assert r.status_code == 200, r.text
    pv = r.json()
    assert {f["kind"] for f in pv["files"]} == {"metadata", "phase", "voi_catalog"}
    assert all(f["source"] == "detected" and len(f["sha256"]) == 64 for f in pv["files"])
    assert pv["alias"] == "DATA" and pv["n_errors"] == 0 and pv["errors"] == []
    assert pv["counts"]["excluded_upstream"] == 1 and pv["counts"]["cases"] >= 16
    assert pv["field_mapping"]["image"] == "relative_path"
    assert pv["field_mapping"]["seg"] == "seg_path"  # case_00013 names a .mha seg (SRC-02 fixture)
    assert pv["field_mapping"]["phase"] == ["phase.json", "phase"]
    pdir = ctx_of(client).workspace.project_dir(pid)
    cached = pdir / "cache/previews" / pv["preview_id"]
    assert (cached / "preview.json").is_file() and (cached / "metadata.jsonl").is_file()


def test_preview_multipart_and_errors(client: TestClient, pid: str, data_root: Path) -> None:
    meta = (data_root / "metadata.jsonl").read_bytes() + b"{broken\n"
    r = client.post(
        f"{API}/projects/{pid}/imports/preview",
        data={"root": str(data_root), "alias": "SRC"},
        files={"metadata": ("my_meta.jsonl", meta, "application/jsonl")},
    )
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["alias"] == "SRC" and [f["name"] for f in pv["files"]] == ["my_meta.jsonl"]
    assert pv["files"][0]["source"] == "uploaded"
    assert pv["n_errors"] == 1 and pv["errors"][0]["file"] == "metadata.jsonl"
    assert pv["errors"][0]["line"] == meta.count(b"\n")
    assert pv["field_mapping"]["side"] is None  # metadata-only (IMP-11)
    r = client.post(
        f"{API}/projects/{pid}/imports/preview", data={"root": str(data_root)}, files={}
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("body", "status", "slug"),
    [
        ({"root": "/"}, 403, "path-outside-root"),
        ({"root": "relative/path"}, 422, "validation"),
        ({"root": "__FILE__"}, 415, "unsupported-format"),  # a file root must be NIfTI (SRC-05)
        ({"root": "__ROOT__", "detect": False}, 422, "validation"),
        ({"root": "__ROOT__", "alias": "bad alias"}, 422, "validation"),
        ({}, 422, "validation"),
    ],
)
def test_preview_rejects(
    client: TestClient, pid: str, data_root: Path, body: dict[str, Any], status: int, slug: str
) -> None:
    subs = {"__FILE__": str(data_root / "metadata.jsonl"), "__ROOT__": str(data_root)}
    body = {k: subs.get(v, v) if isinstance(v, str) else v for k, v in body.items()}
    r = client.post(f"{API}/projects/{pid}/imports/preview", json=body)
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == f"/problems/{slug}"


def test_preview_missing_metadata(client: TestClient, pid: str, data_root: Path) -> None:
    empty = data_root / "nifti"
    r = client.post(f"{API}/projects/{pid}/imports/preview", json={"root": str(empty)})
    assert r.status_code == 422


def test_commit_unknown_preview_and_project(client: TestClient, pid: str) -> None:
    for preview_id in ("01JABCDEFGHJKMNPQRSTVWXYZ0", "../../x"):
        r = client.post(f"{API}/projects/{pid}/imports", json={"preview_id": preview_id})
        assert r.status_code == 404 and r.json()["type"] == "/problems/not-found"
    r = client.get(f"{API}/projects/01JABCDEFGHJKMNPQRSTVWXYZ0/cases")
    assert r.status_code == 404


def test_commit_snapshots_and_history(
    client: TestClient, imported: tuple[str, dict[str, Any], dict[str, Any]], data_root: Path
) -> None:
    pid, pv, commit = imported
    pdir = ctx_of(client).workspace.project_dir(pid)
    snap = pdir / "sources" / commit["import_id"]
    assert (snap / "metadata.jsonl").read_bytes() == (data_root / "metadata.jsonl").read_bytes()
    assert (snap / "voi_catalog.jsonl").is_file() and (snap / "phase.json").is_file()
    cfg = ctx_of(client).workspace.get(pid)
    assert [(r.alias, r.path) for r in cfg.path_roots] == [("DATA", str(data_root))]
    for name in ("items.jsonl", "cases.jsonl", "qc_warnings.jsonl", "status.json"):
        assert (pdir / "index" / name).is_file()
    r = client.post(f"{API}/projects/{pid}/imports", json={"preview_id": pv["preview_id"]})
    second = r.json()
    assert wait(client, second["job_id"]).status == "succeeded"
    hist = client.get(f"{API}/projects/{pid}/imports").json()
    assert [h["import_id"] for h in hist["items"]] == [second["import_id"], commit["import_id"]]
    assert hist["total"] == 2 and hist["items"][0]["counts"] == pv["counts"]
    assert hist["index"]["state"] == "ready"
    assert hist["index"]["import_id"] == second["import_id"]
    assert hist["index"]["n_items"] > 0


def test_index_rebuilt_event(
    client: TestClient, imported: tuple[str, dict[str, Any], dict[str, Any]]
) -> None:
    pid, _, commit = imported
    bus = ctx_of(client).bus

    async def first_rebuilt() -> dict[str, Any]:
        async for ev in bus.subscribe(pid, 0):
            if ev.event == "index.rebuilt":
                return ev.data
        raise AssertionError("no index.rebuilt")

    data = client.portal.call(first_rebuilt)  # type: ignore[union-attr]
    assert data["import_id"] == commit["import_id"] and data["n_items"] > 0


def test_warnings_match_expected(
    client: TestClient, imported: tuple[str, dict[str, Any], dict[str, Any]], fixtures_copy: Path
) -> None:
    pid = imported[0]
    expected = json.loads((fixtures_copy / "expected.json").read_text())
    warnings = pages(client, f"{API}/projects/{pid}/warnings")
    got = {(w["case_id"], w["code"]) for w in warnings}
    for d in expected["defects"]:
        if d["code"] != "fingerprint_changed":
            assert (d["case_id"], d["code"]) in got, d
    assert not [w for w in warnings if w["case_id"] in expected["excluded_upstream"]]
    errs = pages(client, f"{API}/projects/{pid}/warnings?severity=error")
    assert errs and all(w["severity"] == "error" for w in errs)
    one = pages(client, f"{API}/projects/{pid}/warnings?code=shape_mismatch")
    assert [w["case_id"] for w in one] == ["case_00017"]
    by_item = pages(client, f"{API}/projects/{pid}/warnings?item_id=case_00014.01.voi.R")
    assert [w["code"] for w in by_item] == ["missing_voi_mask"]
    assert client.get(f"{API}/projects/{pid}/warnings?code=nope").status_code == 422


def test_paging(client: TestClient, imported: tuple[str, dict[str, Any], dict[str, Any]]) -> None:
    pid = imported[0]
    full = client.get(f"{API}/projects/{pid}/cases").json()
    assert full["next_cursor"] is None and full["total"] == len(full["items"])
    small = pages(client, f"{API}/projects/{pid}/cases", limit=3)
    assert small == full["items"]
    first = client.get(f"{API}/projects/{pid}/cases?limit=3").json()
    assert len(first["items"]) == 3 and first["next_cursor"] and first["total"] == full["total"]
    for bad in ("limit=0", "limit=2001", "cursor=abc"):
        r = client.get(f"{API}/projects/{pid}/cases?{bad}")
        assert r.status_code == 422, bad


def test_cases_filters(
    client: TestClient, imported: tuple[str, dict[str, Any], dict[str, Any]]
) -> None:
    pid = imported[0]
    url = f"{API}/projects/{pid}/cases"

    def ids(query: str = "") -> list[str]:
        return [c["case_id"] for c in pages(client, f"{url}?{query}")]

    default = ids()
    assert "case_00022" not in default and default == sorted(default)
    assert ids("status=excluded_upstream") == ["case_00022"]
    assert set(ids("status=missing")) >= {"case_00010", "case_00012", "case_00014"}
    assert ids("q=00017") == ["case_00017"] and ids("q=p017") == ["case_00017"]
    assert set(ids("phase=EP")) == {"case_00002", "case_00003"}
    assert ids("warning=affine_mismatch") == ["case_00016"]
    with_voi = set(ids("has_voi=true"))
    assert {"case_00001", "case_00014", "case_00023"} <= with_voi
    assert not with_voi & set(ids("has_voi=false"))
    # No hard-coded `group` (ADR-0011): an unknown query parameter filters nothing.
    assert set(ids("group=A")) == set(default)
    # VAR-10 variable filters: categorical value (repeatable = OR) and numeric ranges.
    cohort = {f"case_{n:05d}" for n in range(30, 62)}
    assert set(ids("var.patient_sex=F")) | set(ids("var.patient_sex=M")) >= cohort
    both = set(ids("var.patient_sex=F&var.patient_sex=M"))
    assert both == set(ids("var.patient_sex=F")) | set(ids("var.patient_sex=M"))
    low, high = set(ids("var.marker_a=..50")), set(ids("var.marker_a=50.01.."))
    assert low and high and not low & high and (low | high) < cohort | {"case_00062"}
    assert set(ids("var.marker_a=..50&var.score=0..")) == low
    assert client.get(f"{url}?var.nope=1").status_code == 422
    assert client.get(f"{url}?var.marker_a=abc").status_code == 422
    ranked = pages(client, f"{url}?sort=-n_warnings")
    counts = [c["n_warnings"] for c in ranked]
    assert counts == sorted(counts, reverse=True) and counts[0] > 0
    assert client.get(f"{url}?sort=bogus").status_code == 422
    assert client.get(f"{url}?phase=XX").status_code == 422


def test_case_detail(
    client: TestClient, imported: tuple[str, dict[str, Any], dict[str, Any]]
) -> None:
    pid = imported[0]
    r = client.get(f"{API}/projects/{pid}/cases/case_00001")
    assert r.status_code == 200
    d = r.json()
    assert d["case"]["phases"] == ["NC", "CMP", "NP"] and d["warnings"] == []
    assert {s["scan_idx"]: s["phase"]["canonical"] for s in d["scans"]} == {
        "01": "NC",
        "02": "CMP",
        "03": "NP",
    }
    last = d["scans"][-1]["items"]
    assert [i["item_id"] for i in last] == [
        "case_00001.03.complete.-",
        "case_00001.03.voi.L",
        "case_00001.03.voi.R",
    ]
    d = client.get(f"{API}/projects/{pid}/cases/case_00013").json()
    assert {w["code"] for w in d["warnings"]} == {"missing_seg", "unsupported_format"}
    assert client.get(f"{API}/projects/{pid}/cases/case_99999").status_code == 404


def test_item_detail(
    client: TestClient, imported: tuple[str, dict[str, Any], dict[str, Any]], data_root: Path
) -> None:
    pid = imported[0]
    r = client.get(f"{API}/projects/{pid}/items/case_00001.01.complete.-")
    assert r.status_code == 200
    it = r.json()
    assert it["image"]["ref"] == "DATA:nifti/01_case_00001_0000.nii.gz"
    img_abs = Path(it["advanced"]["image_path"])
    assert img_abs.samefile(data_root / "nifti/01_case_00001_0000.nii.gz")
    assert Path(it["advanced"]["mask_path"]).samefile(data_root / "seg/01_case_00001.nii.gz")
    assert it["warnings"] == [] and it["labels_present"] == [1, 2, 3]
    it = client.get(f"{API}/projects/{pid}/items/case_00012.01.complete.-").json()
    assert it["advanced"] == {"image_path": None, "mask_path": None}
    assert {w["code"] for w in it["warnings"]} >= {"outside_root"}
    assert client.get(f"{API}/projects/{pid}/items/case_00001.09.voi.L").status_code == 404


def test_commit_conflict_while_indexing(
    client: TestClient, pid: str, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = ctx_of(client).jobs
    r = client.post(f"{API}/projects/{pid}/imports/preview", json={"root": str(data_root)})
    busy = JobInfo(job_id="J", kind="index", project_id=pid, status="running", created_at="x")
    monkeypatch.setattr(jobs, "active", lambda p, k: busy if (p, k) == (pid, "index") else None)
    r = client.post(f"{API}/projects/{pid}/imports", json={"preview_id": r.json()["preview_id"]})
    assert r.status_code == 409 and r.json()["type"] == "/problems/job-conflict"


def test_stale_running_status_becomes_interrupted(client: TestClient, pid: str) -> None:
    store = ctx_of(client).index
    store.write_status(pid, IndexStatus(state="running", job_id="gone", import_id="i"))
    hist = client.get(f"{API}/projects/{pid}/imports").json()
    assert hist["index"]["state"] == "interrupted" and hist["items"] == []
    assert store.status(pid).state == "interrupted"


def test_failed_job_keeps_previous_index(
    client: TestClient,
    imported: tuple[str, dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid, pv, first = imported
    from app.ingest import indexer

    def boom(probes: Any) -> Any:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(indexer, "probe_batch", boom)
    r = client.post(f"{API}/projects/{pid}/imports", json={"preview_id": pv["preview_id"]})
    assert wait(client, r.json()["job_id"]).status == "failed"
    st = client.get(f"{API}/projects/{pid}/imports").json()["index"]
    assert st["state"] == "failed" and "disk on fire" in st["error"]
    it = client.get(f"{API}/projects/{pid}/items/case_00001.01.complete.-").json()
    assert it["import_id"] == first["import_id"]


def test_reimport_fingerprint_changed(
    client: TestClient, pid: str, data_root: Path, fixtures_copy: Path
) -> None:
    expected = json.loads((fixtures_copy / "expected.json").read_text())
    defect = next(d for d in expected["defects"] if d["code"] == "fingerprint_changed")
    _, first = do_import(client, pid, data_root)
    iid = f"{defect['case_id']}.{defect['scan_idx']}.complete.-"
    before = client.get(f"{API}/projects/{pid}/items/{iid}").json()
    target = data_root / defect["mutate_after_index"]
    img: Any = nib.load(target)
    nib.save(nib.Nifti1Image(np.asanyarray(img.dataobj) + 7, img.affine), target)  # the copy
    _, second = do_import(client, pid, data_root)
    after = client.get(f"{API}/projects/{pid}/items/{iid}").json()
    assert after["import_id"] == second["import_id"] != first["import_id"]
    assert after["image"]["fp"] != before["image"]["fp"]
    assert "fingerprint_changed" in after["warning_codes"]
    ws = pages(client, f"{API}/projects/{pid}/warnings?code=fingerprint_changed")
    assert [(w["case_id"], w["field"]) for w in ws] == [(defect["case_id"], "image")]
