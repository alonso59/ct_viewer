"""TST-20 (DCM-13, ADR-0020/0021): converter output (app + CLI) has no study fields; legacy files
with them still import; the dataset table joins active layers; workspace datasets (TSK-13)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from fastapi.testclient import TestClient
from plugins.dicom import cli
from plugins.dicom.pipeline import STUDY_FIELDS, STUDY_PREFIXES

from app.tasks.workspace_runs import default_dataset_name
from tests.test_api_ingest import ctx_of, do_import, wait
from tests.test_contract import assert_problem
from tests.test_dicom import convert, dc, project, src  # noqa: F401  (fixtures)
from tests.test_projects_v3 import neutral

API = "/api/v1"
HDR = {"X-Reviewer": "Dr. AP"}


def study_keys(rows: list[dict[str, Any]]) -> set[str]:
    return {k for r in rows for k in r if k in STUDY_FIELDS or k.startswith(STUDY_PREFIXES)}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_app_converter_rows_are_clean(
    dc: TestClient,  # noqa: F811
    src: tuple[Path, dict[str, Any]],  # noqa: F811
    tmp_path: Path,
) -> None:
    pid = project(dc, tmp_path)
    run = convert(dc, pid, src[0])
    rows = read_jsonl(tmp_path / "derived" / pid / "dicom.convert" / "runs" / run["run_id"]
                      / "metadata.jsonl")  # fmt: skip
    assert rows and study_keys(rows) == set()
    assert {"case_id", "scan_idx", "relative_path", "series_uid", "modality"} <= set(rows[0])
    # the analyzers' results are layers instead (ANZ-04)
    layers = {x["field"]: x for x in dc.get(f"{API}/projects/{pid}/layers").json()}
    assert {"phase", "target_match", "output_role", "readiness"} <= set(layers)
    assert layers["phase"]["plugin"] == "dicom" and layers["phase"]["n_values"] >= 2


def test_cli_writes_the_same_clean_rows_and_no_curation_csv(
    src: tuple[Path, dict[str, Any]],  # noqa: F811
    tmp_path: Path,
) -> None:
    out = tmp_path / "cli-out"
    (out).mkdir()
    (out / "curation.csv").write_text("case_id,curated_phase\ncase_00000,NP\n")  # an old run
    cfg = tmp_path / "converter.yaml"
    cfg.write_text(f"dataset_root: {src[0]}\noutput_root: {out}\n")
    assert cli.main([str(cfg)]) == 0
    rows = read_jsonl(out / "metadata.jsonl")
    assert rows and study_keys(rows) == set()
    assert all(r["relative_path"].startswith("nifti/") for r in rows)
    assert (out / "curation.csv").read_text().startswith("case_id,curated_phase")  # untouched


def test_legacy_fields_still_import(client: TestClient, data_root: Path) -> None:
    """INPUT_METADATA: `phase_guess*`, `curated_*` and `group` from old files are still read."""
    meta = data_root / "metadata.jsonl"
    rows = read_jsonl(meta)
    rows[0].pop("phase", None)
    rows[0].update(curated_phase="ART", group="A", include_guess="include")
    rows[1].pop("phase", None)
    rows[1].update(phase_guess="VEN", phase_guess_confidence="high", group="B")
    meta.write_text("".join(json.dumps(r) + "\n" for r in rows))
    pid = neutral(client, packs=["ccrcc"])
    do_import(client, pid, data_root)
    by_id = {i.item_id: i for i in ctx_of(client).index.load(pid).items}

    def complete(row: dict[str, Any]) -> Any:
        sidx = str(row["scan_idx"]).zfill(2)
        return next(
            i for i in by_id.values()
            if i.case_id == row["case_id"] and i.scan_idx == sidx and i.scope == "complete"
        )  # fmt: skip

    first = complete(rows[0])
    assert first.phase.canonical == "CMP" and first.phase.source == "curated_phase"
    second = complete(rows[1])
    assert second.phase.canonical == "NP" and second.phase.source == "phase_guess"
    names = {v["name"] for v in client.get(f"{API}/projects/{pid}/variables").json()["variables"]}
    assert "group" in names  # an ordinary study variable (ADR-0011)


def test_dataset_table_joins_active_layers(
    dc: TestClient,  # noqa: F811
    src: tuple[Path, dict[str, Any]],  # noqa: F811
    tmp_path: Path,
) -> None:
    pid = project(dc, tmp_path)
    run = convert(dc, pid, src[0])
    item = "case_00000.01.complete.-"
    ev = {"item_id": item, "target": "side", "status": "accepted"}
    assert dc.post(f"{API}/projects/{pid}/curation/events", json=ev, headers=HDR).is_success
    r = dc.get(f"{API}/projects/{pid}/exports/dataset-table")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "dataset_table.csv" in r.headers["content-disposition"]
    table = list(csv.DictReader(io.StringIO(r.text)))
    header = list(table[0])
    phase_col = f"phase@dicom.convert:{run['run_id']}"
    assert phase_col in header and "curation_status@curation" in header
    row = next(x for x in table if x["item_id"] == item)
    assert row[phase_col] == "NP" and row["curation_status@curation"] == "accepted"
    assert "target_match" not in header  # the active layer column replaces the joined extra
    pq_r = dc.get(f"{API}/projects/{pid}/exports/dataset-table", params={"format": "parquet"})
    t = pq.read_table(io.BytesIO(pq_r.content))
    layers = json.loads(t.schema.metadata[b"layers"])
    assert {x["column"] for x in layers} >= {phase_col, "curation_status@curation"}
    # the converter artifact is never rewritten with plugin columns (ADR-0020 §4)
    rows = read_jsonl(tmp_path / "derived" / pid / "dicom.convert" / "runs" / run["run_id"]
                      / "metadata.jsonl")  # fmt: skip
    assert study_keys(rows) == set() and all("curation_status" not in x for x in rows)


def test_workspace_dataset_then_project(
    dc: TestClient,  # noqa: F811
    src: tuple[Path, dict[str, Any]],  # noqa: F811
    tmp_path: Path,
) -> None:
    """TSK-13: convert without a project into `_datasets/`, then import it into a neutral
    project, which receives the phase layer; the dataset is never modified (write-once)."""
    body = {"settings": {}, "selection": {"source": str(src[0])}}
    est = dc.post(f"{API}/tasks/dicom.convert/estimate", json=body).json()
    assert est["n_units"] == 2 and est["detail"]["series"] == 3
    # DCM-06 (AUD-A2-13): one row per series, the skipped one with its reason, bytes per series
    plan = {(r["description"], r["action"]): r for r in est["series"]}
    scout = plan[("SCOUT", "skip")]
    assert scout["reason"] and scout["bytes"] == 0 and scout["n_files"] > 0
    assert sum(r["bytes"] for r in est["series"]) == est["output_bytes"]
    assert all(r["patient"] for r in est["series"])  # not anonymized
    started = dc.post(f"{API}/task-runs", json={**body, "task_id": "dicom.convert",
                                                "name": "study A"})  # fmt: skip
    assert started.status_code == 202, started.text
    wait(dc, started.json()["job_id"])
    run = dc.get(f"{API}/task-runs/{started.json()['run_id']}").json()
    assert run["status"] == "completed", run
    ds = Path(run["dataset_dir"])
    assert ds == (tmp_path / "derived" / "_datasets" / "study-A").resolve()
    assert {p.name for p in ds.iterdir()} >= {"metadata.jsonl", "nifti", "sidecars",
                                              "annotations.jsonl", "dataset.json"}  # fmt: skip
    assert study_keys(read_jsonl(ds / "metadata.jsonl")) == set()
    assert (ctx_of(dc).settings.workspace_root / "plugins" / "dicom" / "runs" / run["run_id"]
            / "run.json").is_file()  # fmt: skip
    assert [r["run_id"] for r in dc.get(f"{API}/task-runs").json()] == [run["run_id"]]
    # a second run with the same name gets a new folder (write-once)
    again = dc.post(
        f"{API}/task-runs", json={**body, "task_id": "dicom.convert", "name": "study A"}
    )
    wait(dc, again.json()["job_id"])
    assert (
        dc.get(f"{API}/task-runs/{again.json()['run_id']}")
        .json()["dataset_dir"]
        .endswith("study-A-1")
    )
    before = {str(p): p.stat().st_mtime_ns for p in ds.rglob("*")}
    # SRC-16: the dataset opens in Open mode (a readable root) without a project
    opened = dc.post(f"{API}/open", json={"path": str(ds)})
    assert opened.status_code == 201, opened.text
    assert {i["format"] for i in opened.json()["items"]} == {"nifti"}
    # VW-05 / SRC-16 (AUD-A2-10): the dataset's rows name the modality, so it is not assumed
    assert {i["modality"] for i in opened.json()["items"]} == {"CT"}
    # a neutral project from the dataset: it imports like any root and brings the phase layer
    pid = neutral(dc)
    pv = dc.post(f"{API}/projects/{pid}/imports/preview", json={"root": str(ds), "alias": "DATA"})
    assert pv.status_code == 200, pv.text
    commit = dc.post(f"{API}/projects/{pid}/imports", json={"preview_id": pv.json()["preview_id"]})
    assert commit.status_code == 202, commit.text
    wait(dc, commit.json()["job_id"])
    p = dc.get(f"{API}/projects/{pid}").json()
    assert p["annotation_sources"].get("phase")
    item = dc.get(f"{API}/projects/{pid}/items/case_00000.01.complete.-").json()
    assert item["phase"]["canonical"] == "NP" and item["phase"]["source"].startswith("analyzer:")
    assert dc.get(f"{API}/projects/{pid}/items/case_00000.01.complete.-/image").status_code == 200
    # DCM-04 / VW-22 (AUD-A2-04): the dataset's relative `sidecars/…` ref resolves in the project
    assert item["extra"]["dicom_sidecar"].startswith("DATA:sidecars/")
    tags = dc.get(f"{API}/projects/{pid}/items/case_00000.01.complete.-/dicom-tags")
    assert tags.status_code == 200, tags.text
    assert "7FE00010" not in tags.json()  # never PixelData
    assert {str(p): p.stat().st_mtime_ns for p in ds.rglob("*")} == before
    # without the chained phase analyzer the dataset has no phase layer
    no_phase = {**body, "task_id": "dicom.convert", "name": "nophase"}
    no_phase["settings"] = {"phase_analyzer": False}
    off = dc.post(f"{API}/task-runs", json=no_phase)
    wait(dc, off.json()["job_id"])
    ds2 = Path(dc.get(f"{API}/task-runs/{off.json()['run_id']}").json()["dataset_dir"])
    assert "phase" not in {a["field"] for a in read_jsonl(ds2 / "annotations.jsonl")}
    # AUD-A5-16 (NFR-17): without a name, never the source folder's (often a patient) name
    unnamed = dc.post(f"{API}/task-runs", json={**no_phase, "name": None})
    wait(dc, unnamed.json()["job_id"])
    ds3 = Path(dc.get(f"{API}/task-runs/{unnamed.json()['run_id']}").json()["dataset_dir"])
    assert ds3.name == default_dataset_name() and src[0].name not in ds3.name


def test_workspace_task_errors(dc: TestClient, src: tuple[Path, dict[str, Any]]) -> None:  # noqa: F811
    body = {"task_id": "analyzer.phase", "selection": {"source": str(src[0])}}
    assert_problem(dc.post(f"{API}/task-runs", json=body), "validation")  # scope: project
    no_src = {"task_id": "dicom.convert", "selection": {}}
    assert_problem(dc.post(f"{API}/task-runs", json=no_src), "validation")
    outside = {"task_id": "dicom.convert", "selection": {"source": "/etc"}}
    assert_problem(dc.post(f"{API}/task-runs", json=outside), "path-outside-root")
    # SRC-11 / UI-18 (AUD-A2-07): a folder without DICOM is refused with the cause and next
    # steps, for the dry run and the run; no empty dataset is "completed"
    nifti_only = src[0] / "NIFTI"
    nifti_only.mkdir()
    (nifti_only / "a.nii.gz").write_bytes(b"x")
    none = {"settings": {}, "selection": {"source": str(nifti_only)}}
    r = dc.post(f"{API}/tasks/dicom.convert/estimate", json=none)
    assert_problem(r, "unsupported-format")
    assert r.json()["detail"] == "No DICOM files in NIFTI; 1 NIfTI files found"
    assert r.json()["actions"] == ["open", "import_as:nifti-files", "choose_another_path"]
    r = dc.post(f"{API}/task-runs", json={**none, "task_id": "dicom.convert", "name": "empty"})
    assert_problem(r, "unsupported-format")
    derived = ctx_of(dc).settings.derived_roots[0]
    assert not (derived / "_datasets" / "empty").exists()
    assert_problem(dc.get(f"{API}/task-runs/01JAAAAAAAAAAAAAAAAAAAAAAA"), "not-found")
