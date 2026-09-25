"""P7b Wave 3: `dicom.convert` through the task API (DCM-01..10, TSK-09), TST-13 DICOM half,
sidecars + anonymize (DCM-04/05), incremental dataset (DCM-07), annotations + activation
(ANZ-04, API-48), CUR-15 (API-55), Open mode DICOM (SRC-13), Save as NIfTI (SRC-14, API-09),
Add to project (SRC-15), several sources per project (SOURCES §Imports)."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("SimpleITK")
pytest.importorskip("pydicom")

from app.config import Settings
from app.main import create_app
from tests.test_api_ingest import ctx_of, wait
from tests.test_contract import assert_problem
from tools.dicom_fixtures import MARKER, write_series

API = "/api/v1"


def tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def src(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    root = tmp_path / "src"
    info = write_series(root / "P001" / "ct")
    write_series(
        root / "P001" / "scout",
        description="SCOUT",
        shape=(12, 10, 3),
        study_uid=info["study_uid"],
        series_number=9,
    )
    write_series(root / "P002" / "ct", patient_id="P002", description="NON CONTRAST ABDOMEN")
    return root, info


@pytest.fixture
def dc(tmp_path: Path, src: tuple[Path, dict[str, Any]]) -> Iterator[TestClient]:
    (tmp_path / "derived").mkdir()
    s = Settings(
        workspace_root=tmp_path / "ws",
        allowed_data_roots=str(src[0].resolve()),
        allowed_derived_roots=str((tmp_path / "derived").resolve()),
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(s, inline_jobs=True)) as c:
        yield c


def project(c: TestClient, tmp_path: Path, preset: str = "ccrcc") -> str:
    packs = [] if preset == "none" else [preset]
    pid = str(c.post(f"{API}/projects", json={"name": "d", "packs": packs}).json()["project_id"])
    r = c.put(
        f"{API}/projects/{pid}/roots/DERIVED",
        json={"path": str(tmp_path / "derived"), "role": "derived"},
    )
    assert r.status_code == 200, r.text
    return pid


def convert(c: TestClient, pid: str, source: Path, **settings: Any) -> dict[str, Any]:
    body = {"task_id": "dicom.convert", "settings": settings, "selection": {"source": str(source)}}
    r = c.post(f"{API}/projects/{pid}/task-runs", json=body)
    assert r.status_code == 202, r.text
    wait(c, r.json()["job_id"])
    run = c.get(f"{API}/projects/{pid}/task-runs/{r.json()['run_id']}").json()
    imp = next((o for o in run["outputs"] if o["kind"] == "import"), None)
    if imp is not None:
        wait(c, imp["detail"])  # the index job of the import (TSK-09)
    return dict(run)


def items(c: TestClient, pid: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for case in c.get(f"{API}/projects/{pid}/cases", params={"status": "active"}).json()["items"]:
        for scan in c.get(f"{API}/projects/{pid}/cases/{case['case_id']}").json()["scans"]:
            for it in scan["items"]:
                if it["status"] != "excluded_upstream":
                    out[it["item_id"]] = it
    return out


def test_converter_task_end_to_end(
    dc: TestClient, src: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    root, info = src
    before = tree(root)
    pid = project(dc, tmp_path)
    run = convert(dc, pid, root)
    assert run["status"] == "completed", run
    assert run["versions"]["dicom.convert"] == "1.1.0" and run["versions"]["pydicom"]
    kinds = {o["kind"] for o in run["outputs"]}
    assert {"image", "sidecar", "annotations", "import"} <= kinds
    # DCM-01: derived writes only in dataset/ and runs/{run_id}/ (ADR-0014); sources untouched (R1)
    task_root = tmp_path / "derived" / pid / "dicom.convert"
    written = {str(p.relative_to(task_root)) for p in task_root.rglob("*") if p.is_file()}
    assert all(
        w.startswith(("dataset/nifti/", "dataset/sidecars/", f"runs/{run['run_id']}/"))
        for w in written
    )
    assert {
        f"runs/{run['run_id']}/{f}" for f in ("metadata.jsonl", "diagnostics.jsonl", "summary.json")
    } <= written
    assert tree(root) == before
    # imported rows (DCM-07 → IMP-06), alias DERIVED, cases from the identity registry (SRC-07)
    its = items(dc, pid)
    assert set(its) == {"case_00000.01.complete.-", "case_00001.01.complete.-"}
    it = its["case_00000.01.complete.-"]
    assert (
        it["image"]["ref"]
        == f"DERIVED:{pid}/dicom.convert/dataset/nifti/01_CT_case_00000_0000.nii.gz"
    )
    assert it["modality"] == "CT"
    assert it["phase"]["canonical"] == "NP" and it["phase"]["source"] == f"analyzer:{run['run_id']}"
    assert it["extra"]["target_match"] == "strong"  # ANZ: target becomes a study variable
    assert it["extra"]["output_role"] == "PRIMARY" and it["extra"]["readiness"].startswith("ready")
    assert its["case_00001.01.complete.-"]["phase"]["canonical"] == "NC"
    scout = dc.get(f"{API}/projects/{pid}/items/case_00000.02.complete.-").json()
    assert scout["status"] == "excluded_upstream"  # EXCLUDED series are not converted (IMP-07)
    ident = json.loads(
        (ctx_of(dc).workspace.project_dir(pid) / "sources" / "identity.json").read_text()
    )
    assert ident["cases"] == {"P001": 0, "P002": 1} and ident["strategy"] == "dicom_patient_id"
    # active annotations (ANZ-04) + DICOM tags on demand (DCM-04/05)
    proj = dc.get(f"{API}/projects/{pid}").json()
    assert proj["annotation_sources"]["phase"] == run["run_id"]
    tags = dc.get(f"{API}/projects/{pid}/items/case_00000.01.complete.-/dicom-tags").json()
    assert (
        tags["00100020"]["Value"] == ["P001"] and "7FE00010" not in tags and tags["_omitted"] == []
    )
    anns = dc.get(f"{API}/projects/{pid}/annotations", params={"field": "phase"}).json()
    assert {a["item_id"] for a in anns if a["active"]} >= set(its)
    # TST-13 (NFR-18): the marker lands at RAS = (-x, -y, z) of its DICOM LPS position
    img: Any = nib.load(task_root / "dataset" / "nifti" / "01_CT_case_00000_0000.nii.gz")
    ijk = np.argwhere(np.asanyarray(img.dataobj) == MARKER)[0]
    ras = img.affine @ np.array([*ijk, 1.0])
    x, y, z = info["marker_lps"]
    assert np.allclose(ras[:3], [-x, -y, z], atol=1e-3)


def test_incremental_run_keeps_files_and_identity(
    dc: TestClient, src: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    root, _ = src
    pid = project(dc, tmp_path)
    run1 = convert(dc, pid, root)
    nifti = tmp_path / "derived" / pid / "dicom.convert" / "dataset" / "nifti"
    first = {
        p.name: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in nifti.iterdir()
    }
    write_series(root / "P003" / "ct", patient_id="P003")  # a new patient arrives
    run2 = convert(dc, pid, root)
    assert run2["status"] == "completed"
    again = {
        p.name: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in nifti.iterdir()
    }
    assert {k: again[k] for k in first} == first  # never rewritten (DCM-07, ADR-0014)
    assert len(again) == len(first) + 1
    rows = [
        json.loads(x)
        for x in (Path(run2["output_dir"]) / "metadata.jsonl").read_text().splitlines()
    ]
    assert {r["case_id"] for r in rows} == {"case_00000", "case_00001", "case_00002"}  # full set
    assert {r["status"] for r in rows if r["patient_id"] == "P001" and r["planned_conversion"]} == {
        "already_converted"
    }
    assert set(items(dc, pid)) == {f"case_0000{n}.01.complete.-" for n in range(3)}
    assert run1["run_id"] != run2["run_id"]
    # the second run's annotations are not active (a run is active only where none was)
    assert dc.get(f"{API}/projects/{pid}").json()["annotation_sources"]["phase"] == run1["run_id"]


def test_anonymize_basic(dc: TestClient, src: tuple[Path, dict[str, Any]], tmp_path: Path) -> None:
    root, _ = src
    pid = project(dc, tmp_path)
    run = convert(dc, pid, root, anonymize="basic")
    assert run["status"] == "completed"
    side = next((tmp_path / "derived" / pid / "dicom.convert" / "dataset" / "sidecars").iterdir())
    tags = json.loads(side.read_text())
    for tag in (
        "00100010",
        "00100030",
        "00080080",
        "00080050",
    ):  # name, birth date, institution, accession
        assert tag not in tags or tags[tag].get("Value") in (
            None,
            [],
            [{"Alphabetic": "case_00000"}],
        )
    assert tags["00100020"]["Value"] == [side.name.split("_")[2] + "_" + side.name.split("_")[3]]
    assert tags["00120062"]["Value"] == ["YES"]
    rows = [
        json.loads(x) for x in (Path(run["output_dir"]) / "metadata.jsonl").read_text().splitlines()
    ]
    assert all(r["patient_id"] == r["case_id"] and not r.get("institution") for r in rows)
    assert all(r["series_uid"].startswith("2.25.") for r in rows)
    ident = json.loads(
        (ctx_of(dc).workspace.project_dir(pid) / "sources" / "identity.json").read_text()
    )
    assert all(k.startswith("sha256:") for k in ident["cases"])  # no PatientID in project state


def test_dry_run_estimate(dc: TestClient, src: tuple[Path, dict[str, Any]], tmp_path: Path) -> None:
    root, _ = src
    pid = project(dc, tmp_path)
    r = dc.post(
        f"{API}/projects/{pid}/tasks/dicom.convert/estimate",
        json={"selection": {"source": str(root)}, "settings": {}},
    )
    assert r.status_code == 200, r.text
    est = r.json()
    assert est["n_units"] == 2 and est["n_skipped"] == 1 and est["output_bytes"]
    assert est["detail"]["series"] == 3 and est["detail"]["source_bytes"] > 0
    assert not (tmp_path / "derived" / pid).exists()  # a dry run writes nothing (DCM-06)
    r = dc.post(
        f"{API}/projects/{pid}/task-runs", json={"task_id": "dicom.convert", "selection": {}}
    )
    assert_problem(r, "validation")
    assert r.json()["actions"] == ["choose_source"]


def test_activation_reindex_and_standalone_analyzer(
    dc: TestClient, src: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    root, _ = src
    pid = project(dc, tmp_path)
    run = convert(dc, pid, root)
    # ANZ-04: deactivate → phase falls back (no explicit fields, no phase_guess → UNK)
    r = dc.put(f"{API}/projects/{pid}/annotation-sources/phase", json={"run_id": None})
    assert r.status_code == 200 and r.json()["job_id"]
    wait(dc, r.json()["job_id"])
    it = dc.get(f"{API}/projects/{pid}/items/case_00000.01.complete.-").json()
    assert it["phase"]["canonical"] == "UNK" and it["phase"]["source"] == "none"
    r = dc.put(f"{API}/projects/{pid}/annotation-sources/phase", json={"run_id": run["run_id"]})
    wait(dc, r.json()["job_id"])
    assert (
        dc.get(f"{API}/projects/{pid}/items/case_00000.01.complete.-").json()["phase"]["canonical"]
        == "NP"
    )
    assert_problem(
        dc.put(
            f"{API}/projects/{pid}/annotation-sources/phase",
            json={"run_id": "01JAAAAAAAAAAAAAAAAAAAAAAA"},
        ),
        "not-found",
    )
    # a standalone analyzer on the imported rows (ANZ-02) reuses the same code
    r = dc.post(
        f"{API}/projects/{pid}/task-runs",
        json={"task_id": "analyzer.target", "settings": {"target_profile": "brain"}},
    )
    assert r.status_code == 202, r.text
    wait(dc, r.json()["job_id"])
    t = dc.get(f"{API}/projects/{pid}/task-runs/{r.json()['run_id']}").json()
    assert t["status"] == "completed" and t["counts"]["ok"] == 2
    anns = dc.get(f"{API}/projects/{pid}/annotations", params={"run": t["run_id"]}).json()
    assert {a["value"] for a in anns} == {"excluded"}  # abdomen rows vs the brain profile
    assert not any(a["active"] for a in anns)  # target_match already had an active run


def test_curation_import_converter(
    dc: TestClient, src: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    root, _ = src
    pid = project(dc, tmp_path)
    convert(dc, pid, root)
    csv = (
        b"case_id,scan_idx,curated_keep,curated_phase,curated_quality,notes\n"
        b"case_00000,01,,CMP,,looks arterial\n"
        b"case_00001,01,false,,,motion\n"
        b"case_00001,01,,,,\n"
        b"case_09999,01,true,,,\n"
    )
    files = {"file": ("curation.csv", io.BytesIO(csv), "text/csv")}
    r = dc.post(
        f"{API}/projects/{pid}/curation/import-converter", files=files, headers={"X-Reviewer": "AP"}
    )
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["imported"] == 1 and rep["phase_events"] == 1
    assert [s["reason"] for s in rep["skipped"]] == ["item not in index"]
    evs = dc.get(f"{API}/projects/{pid}/curation/events").json()["items"]
    got = [(e["target"], e["status"], e["comment"]) for e in evs]
    assert got == [("seg", "rejected", "motion")]
    assert {e["source"] for e in evs} == {"converter_import"}
    # PHS-08: `curated_phase` is a native phase event, and it is the effective phase at once
    phases = dc.get(f"{API}/projects/{pid}/phase/events").json()["items"]
    assert [(p["case_id"], p["scan_idx"], p["value"], p["source"]) for p in phases] == [
        ("case_00000", "01", "CMP", "converter_import")
    ]
    item = dc.get(f"{API}/projects/{pid}/items/case_00000.01.complete.-").json()
    assert item["phase"]["canonical"] == "CMP" and item["phase"]["source"] == "manual"
    files = {"file": ("curation.csv", io.BytesIO(csv), "text/csv")}
    again = dc.post(
        f"{API}/projects/{pid}/curation/import-converter", files=files, headers={"X-Reviewer": "AP"}
    ).json()
    assert again["imported"] == 0 and again["phase_events"] == 0  # once (CUR-15, PHS-08)


# -- Open mode DICOM (SRC-13, DCM-10) + Save as NIfTI (SRC-14) + Add to project (SRC-15) -----


def test_open_dicom_folder_and_single_file(
    dc: TestClient, src: tuple[Path, dict[str, Any]]
) -> None:
    root, _ = src
    s = dc.post(f"{API}/open", json={"path": str(root / "P001")}).json()
    dcm = [i for i in s["items"] if i["format"] == "dicom"]
    assert len(dcm) == 2 and {i["modality"] for i in dcm} == {"CT"}  # one item per series
    assert len({i["name"] for i in dcm}) == 2  # series named by description/folder, not IM0000
    ct = next(i for i in dcm if len(i["files"]) == 14)
    r = dc.get(f"{API}/open/{s['sid']}/items/{ct['n']}/image")
    assert r.status_code == 200
    out = root.parent / "o.nii.gz"
    out.write_bytes(r.content)
    img: Any = nib.load(out)
    assert img.shape == (12, 10, 14) and (np.asanyarray(img.dataobj) == MARKER).sum() == 1
    # a single classic slice → a 1-slice volume (DCM-10)
    one = dc.post(f"{API}/open", json={"path": str(root / "P001" / "ct" / "IM0009.dcm")}).json()
    it = one["items"][0]
    assert it["format"] == "dicom" and it["n_slices"] == 1
    r = dc.get(f"{API}/open/{one['sid']}/items/0/image")
    out.write_bytes(r.content)
    single: Any = nib.load(out)
    assert single.shape[:2] == (12, 10) and (single.shape[2:] or (1,))[0] == 1
    assert (np.asanyarray(single.dataobj) == MARKER).sum() == 1


def test_save_as_nifti(dc: TestClient, src: tuple[Path, dict[str, Any]], tmp_path: Path) -> None:
    root, _ = src
    before = tree(root)
    s = dc.post(f"{API}/open", json={"path": str(root / "P001" / "ct")}).json()
    r = dc.post(f"{API}/open/{s['sid']}/items/0/save", json={"anonymize": "basic"})
    assert r.status_code == 201, r.text
    saved = r.json()
    dest = (tmp_path / "derived").resolve() / "_open" / date.today().isoformat()
    assert Path(saved["path"]).parent == dest and saved["path"].endswith("ct.nii.gz")
    side = json.loads(Path(saved["sidecar_path"]).read_text())
    assert "00100030" not in side and side["00100020"]["Value"] == ["ct"]  # anonymized (DCM-05)
    again = dc.post(f"{API}/open/{s['sid']}/items/0/save", json={}).json()
    assert again["path"].endswith("ct-1.nii.gz")  # never overwrites
    assert tree(root) == before  # R1
    assert_problem(
        dc.post(f"{API}/open/{s['sid']}/items/0/save", json={"dest_dir": str(root)}),
        "path-outside-root",
    )


def test_save_needs_derived_roots(tmp_path: Path, src: tuple[Path, dict[str, Any]]) -> None:
    s = Settings(
        workspace_root=tmp_path / "ws2",
        allowed_data_roots=str(src[0].resolve()),
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(s, inline_jobs=True)) as c:
        sess = c.post(f"{API}/open", json={"path": str(src[0] / "P001" / "ct")}).json()
        r = c.post(f"{API}/open/{sess['sid']}/items/0/save", json={})
        assert_problem(r, "derived-root-required")


def test_add_to_project_keeps_other_sources(
    dc: TestClient, src: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    """SRC-15 + SOURCES §Imports: a converter import and an added NIfTI file coexist."""
    root, _ = src
    pid = project(dc, tmp_path)
    convert(dc, pid, root / "P002")
    extra = root / "loose" / "extra_scan.nii.gz"
    extra.parent.mkdir()
    nib.save(nib.Nifti1Image(np.zeros((4, 4, 4), np.float32), np.eye(4)), extra)
    r = dc.post(
        f"{API}/projects/{pid}/imports/preview",
        json={"root": str(extra), "add": True},
    )
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["source_key"].startswith("add:") and pv["alias"] == "DATA"
    c = dc.post(f"{API}/projects/{pid}/imports", json={"preview_id": pv["preview_id"]}).json()
    wait(dc, c["job_id"])
    assert set(items(dc, pid)) == {"case_00000.01.complete.-", "extra_scan.01.complete.-"}
    roots = {r["alias"]: r["role"] for r in dc.get(f"{API}/projects/{pid}/roots").json()}
    assert roots == {"DATA": "source", "DERIVED": "derived"}
