"""P7i S1: characterization of today's DICOM conversion (ADR-0042; test plan C01-C12).

These tests pin current behavior, known gaps included (DCM-02/04/05/07/09/13/14/17, IMP-07).
A P7i phase that changes one of them changes the test in the same commit and cites the new
requirement. Covered elsewhere: C08/C09 by `tools/dicom_bench.py`; C10 (restored-mtime edits of
converted and unconverted units) by `test_dicom_resume.py`; the SIGKILL part of C12 by
`test_dicom_cli_resume.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator
from importlib import metadata
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from plugins.dicom import task
from rw_dicom import cli, commits, convert, pipeline

from app.config import Settings
from app.main import create_app
from app.tasks import protocol
from app.tasks.registry import manifest_hash
from tests.test_api_ingest import wait
from tests.test_dicom import convert as convert_in_project
from tests.test_dicom import project
from tests.test_dicom_resume import run_conversion
from tests.test_projects_v3 import neutral
from tools.dicom_fixtures import write_series

API = "/api/v1"
GOLDEN = Path(__file__).parent / "data" / "dicom" / "p7i_s1_golden.json"
SERIES = {"seed": "p7i-s1", "shape": (6, 5, 12), "marker": (2, 1, 3)}
# Pinned by task-run resume (C11); a change re-plans unfinished runs, see ADR-0042 §1.
TASK_JSON_HASH = "sha256:ebbb0cfd688ceb6d95fe2b4dcd5ced004b76a383a883b9608c4c7199a87f3d66"


def seeded(root: Path, *, broken: bool = False) -> Path:
    """P001: CT and a 3-slice scout (skipped); P002: CT. `broken` truncates one P002 slice."""
    write_series(root / "P001" / "ct", patient_id="P001", **SERIES)  # type: ignore[arg-type]
    write_series(
        root / "P001" / "scout",
        patient_id="P001",
        description="SCOUT",
        series_number=9,
        seed="p7i-s1",
        shape=(6, 5, 3),
        marker=(2, 1, 1),
    )
    write_series(
        root / "P002" / "ct",
        patient_id="P002",
        description="NON CONTRAST ABDOMEN",
        **SERIES,  # type: ignore[arg-type]
    )
    if broken:  # header discovery still accepts it; GDCM cannot read the pixels
        damaged = sorted((root / "P002" / "ct").glob("*.dcm"))[3]
        damaged.write_bytes(damaged.read_bytes()[:-20])
    return root


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def semantics(dataset: Path, rows_file: Path) -> dict[str, Any]:
    """Decoded voxels, affine and dtype per image; canonical sidecars, rows and annotations."""
    images = {}
    for path in sorted((dataset / "nifti").glob("*.nii.gz")):
        image: Any = nib.load(path)
        voxels = np.asarray(image.dataobj)
        images[path.name] = {
            "shape": list(voxels.shape),
            "dtype": str(voxels.dtype),
            "affine": np.round(image.affine, 6).tolist(),
            "voxels": sha(voxels.tobytes()),
        }
    sidecars = {
        p.name: sha(canonical(json.loads(p.read_text())))
        for p in sorted((dataset / "sidecars").glob("*.json"))
    }
    rows = sorted(jsonl(rows_file), key=lambda r: (r["case_id"], r["scan_idx"]))
    annotations = dataset / "annotations.jsonl"
    return {
        "images": images,
        "sidecars": sidecars,
        "rows": sha(canonical(rows)),
        "annotations": sha(canonical(sorted(jsonl(annotations), key=canonical)))
        if annotations.exists()
        else None,
    }


def versions() -> dict[str, str]:
    return {name: metadata.version(name) for name in ("pydicom", "SimpleITK", "isal", "nibabel")}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    (tmp_path / "derived").mkdir()
    (tmp_path / "src").mkdir()
    settings = Settings(
        dicom_memory_mb=1024,
        workspace_root=tmp_path / "ws",
        allowed_data_roots=str((tmp_path / "src").resolve()),
        allowed_derived_roots=str((tmp_path / "derived").resolve()),
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(settings, inline_jobs=True)) as c:
        yield c


def workspace_run(c: TestClient, source: Path, name: str, **settings: Any) -> dict[str, Any]:
    body = {
        "task_id": "dicom.convert",
        "name": name,
        "settings": settings,
        "selection": {"source": str(source)},
    }
    started = c.post(f"{API}/task-runs", json=body)
    assert started.status_code == 202, started.text
    wait(c, started.json()["job_id"])
    return dict(c.get(f"{API}/task-runs/{started.json()['run_id']}").json())


def cli_config(tmp_path: Path, source: Path, out: Path, extra: str = "") -> Path:
    config = tmp_path / "converter.yaml"
    config.write_text(f"dataset_root: {source}\noutput_root: {out}\n{extra}")
    return config


def test_c01_workspace_conversion_matches_the_golden_semantics(
    client: TestClient, tmp_path: Path
) -> None:
    """C01, DCM-02/04/05/13/14: decoded voxels, geometry, sidecars, rows and annotations.

    Record with `RW_RECORD_GOLDEN=1` only when the lock (versions below) changes."""
    source = seeded(tmp_path / "src")
    observed: dict[str, Any] = {"versions": versions()}
    for label, settings in (("plain", {}), ("anonymized", {"anonymize": "basic"})):
        run = workspace_run(client, source, label, **settings)
        assert run["status"] == "completed", run
        dataset = Path(run["dataset_dir"])
        observed[label] = semantics(dataset, dataset / "metadata.jsonl")
    if os.environ.get("RW_RECORD_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(observed, indent=2, sort_keys=True) + "\n")
    golden = json.loads(GOLDEN.read_text())
    assert observed["versions"] == golden["versions"], "lock changed: re-record C01"
    assert observed == golden


def test_c02_a02_cli_writes_the_workspace_dataset(client: TestClient, tmp_path: Path) -> None:
    """C02 → A02/A05/A06, DCM-28: the CLI writes the same dataset as a workspace run (images,
    sidecars, rows, annotations), honors `anonymize`, and keeps run state private."""
    source = seeded(tmp_path / "src")
    for label, extra, settings in (
        ("plain", "", {}),
        ("anon", "anonymize: basic\n", {"anonymize": "basic"}),
    ):
        run = workspace_run(client, source, label, **settings)
        dataset = Path(run["dataset_dir"])
        out = tmp_path / f"cli-{label}"
        assert cli.main([str(cli_config(tmp_path, source, out, extra))]) == 0
        workspace = semantics(dataset, dataset / "metadata.jsonl")
        standalone = semantics(out, out / "metadata.jsonl")
        assert standalone == workspace
        for name in sorted((dataset / "nifti").glob("*.nii.gz")):
            assert (out / "nifti" / name.name).read_bytes() == name.read_bytes()
        shared = {"metadata.jsonl", "nifti", "sidecars", "annotations.jsonl", "dataset.json",
                  "diagnostics.jsonl", "summary.json"}  # fmt: skip
        assert shared <= {p.name for p in out.iterdir()} and shared <= {
            p.name for p in dataset.iterdir()
        }
        manifest = json.loads((out / "dataset.json").read_text())
        assert manifest["settings_hash"].startswith("sha256:") and manifest["units_by_versions"]
        assert (out / ".rw-runs").stat().st_mode & 0o077 == 0
    assert {r["patient_id"] for r in jsonl(tmp_path / "cli-anon" / "metadata.jsonl")} == {
        "case_00000",
        "case_00001",
    }


@pytest.mark.parametrize("change", ["selection_setting", "reader_version"])
def test_c03_c04_a22_a23_later_run_reuses_verified_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """C03/C04 → A22/A23, DCM-31: selection settings and reader versions no longer block reuse;
    reused series keep the versions that produced them."""
    source, out = seeded(tmp_path / "src"), tmp_path / "out"
    config = cli_config(tmp_path, source, out)
    assert cli.main([str(config)]) == 0
    images = {p.name: p.read_bytes() for p in (out / "nifti").glob("*.nii.gz")}
    if change == "selection_setting":
        config.write_text(config.read_text() + "conversion:\n  skip_unsafe_geometry: true\n")
    else:
        original = commits.reader_versions
        monkeypatch.setattr(
            commits, "reader_versions", lambda v: {**original(v), "SimpleITK": "0.0.0"}
        )
    assert cli.main([str(config)]) == 0
    rows = [r for r in jsonl(out / "metadata.jsonl") if r["planned_conversion"]]
    assert {r["status"] for r in rows} == {"already_converted"} and len(rows) == 2
    assert {p.name: p.read_bytes() for p in (out / "nifti").glob("*.nii.gz")} == images
    versions = json.loads((out / "dataset.json").read_text())["units_by_versions"]
    assert [v["versions"]["SimpleITK"] for v in versions.values()] == [
        metadata.version("SimpleITK")
    ]


def test_c05_a04_dataset_manifests_are_written_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C05 → A04, DCM-28: a failure while writing a manifest leaves no torn file."""
    from rw_dicom import durable

    source = seeded(tmp_path / "src")
    job = tmp_path / "attempt"
    protocol.write_job(
        job,
        {
            "source": {"path": str(source)},
            "output_dir": str(tmp_path / "dataset"),
            "dataset_dir": str(tmp_path / "dataset"),
            "settings": {"phase_analyzer": False},
            "run_id": "characterization",
            "workspace": True,
            "dataset_ref": "DATA:",
            "project_id": "",
            "context": {"phase_vocabulary": [], "target_profile": "generic"},
        },
    )
    original = durable.os.replace

    def torn(src: str, dst: Any) -> None:
        if Path(dst).name == "dataset.json":
            raise OSError("synthetic failure during publication")
        original(src, dst)

    monkeypatch.setattr(durable.os, "replace", torn)
    with pytest.raises(OSError, match="synthetic"):
        task.run(str(job))
    assert not (tmp_path / "dataset" / "dataset.json").exists()
    assert not list((tmp_path / "dataset").glob(".dataset.json.*"))


def test_c06_a25_a26_incomplete_dataset_imports_only_when_acknowledged(
    client: TestClient, tmp_path: Path
) -> None:
    """C06 → A25/A26, DCM-34, IMP-07: an incomplete workspace dataset says so, imports only on
    acknowledgment, keeps failed rows as excluded items with their reason, and brings layers."""
    source = seeded(tmp_path / "src", broken=True)
    run = workspace_run(client, source, "partial")
    assert run["status"] == "completed_with_errors", run
    dataset = Path(run["dataset_dir"])
    names = {p.name for p in dataset.iterdir()}
    assert "dataset.json" not in names
    assert {"dataset.incomplete.json", "annotations.jsonl", "diagnostics.jsonl"} <= names
    pid = neutral(client)
    pv = client.post(
        f"{API}/projects/{pid}/imports/preview", json={"root": str(dataset), "detect": True}
    )
    assert pv.status_code == 200, pv.text
    assert pv.json()["incomplete"] == {"converted": 1, "failed": 1, "pending": 0}
    refused = client.post(
        f"{API}/projects/{pid}/imports", json={"preview_id": pv.json()["preview_id"]}
    )
    assert (
        refused.status_code == 409 and "acknowledge:incomplete_dataset" in refused.json()["actions"]
    )
    commit = client.post(
        f"{API}/projects/{pid}/imports",
        json={"preview_id": pv.json()["preview_id"], "allow_incomplete": True},
    )
    assert commit.status_code == 202, commit.text
    wait(client, commit.json()["job_id"])
    failed = client.get(f"{API}/projects/{pid}/items/case_00001.01.complete.-").json()
    assert failed["status"] == "excluded_upstream"
    [warning] = [w for w in failed["warnings"] if w["code"] == "conversion_failed"]
    assert "RuntimeError" in warning["message"]
    converted = client.get(f"{API}/projects/{pid}/items/case_00000.01.complete.-").json()
    assert converted["status"] == "active"
    assert client.get(f"{API}/projects/{pid}").json()["annotation_sources"]


def test_c06_a28_project_run_registers_converted_series_only_on_request(
    client: TestClient, tmp_path: Path
) -> None:
    """C06 → A28, DCM-34: a project conversion with failures registers nothing until asked."""
    source = seeded(tmp_path / "src", broken=True)
    pid = project(client, tmp_path, preset="none")
    run = convert_in_project(client, pid, source)
    assert run["status"] == "completed_with_errors", run
    assert client.get(f"{API}/projects/{pid}/cases").json()["items"] == []
    detail = client.post(f"{API}/projects/{pid}/task-runs/{run['run_id']}/register-converted")
    assert detail.status_code == 200, detail.text
    deadline = time.monotonic() + 60
    while not client.get(f"{API}/projects/{pid}/cases").json()["items"]:
        assert time.monotonic() < deadline
        time.sleep(0.2)
        client.get(f"{API}/projects/{pid}/task-runs/{run['run_id']}")
    assert client.get(f"{API}/projects/{pid}/task-runs/{run['run_id']}").json()["status"] == (
        "completed_with_errors"
    )


def test_c07_a24_reuse_rehashes_inputs_and_outputs_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C07 → A18/A24, DCM-29/30: a fresh run hashes each input twice inside its unit (no
    whole-run pass); reuse hashes each input and output once and reads geometry without
    decompressing the image again."""
    source, output = seeded(tmp_path / "src"), tmp_path / "derived"
    calls: Counter[str] = Counter()
    digest, image_digest = commits.file_digest, commits._image_digest
    read_image = convert.read_image

    def counted_digest(path: Path, root: Path | None = None) -> dict[str, Any]:
        calls["input" if Path(path).is_relative_to(source) else "output"] += 1
        return digest(path, root)

    def counted_image(path: Path, geometry: dict[str, Any]) -> dict[str, Any]:
        calls["decompress"] += 1
        return image_digest(path, geometry)

    def counted_read(series: Any) -> Any:
        calls["decode"] += 1
        return read_image(series)

    monkeypatch.setattr(commits, "file_digest", counted_digest)
    monkeypatch.setattr(commits, "_image_digest", counted_image)
    monkeypatch.setattr(convert, "read_image", counted_read)
    inputs = 24  # two selected 12-slice series; the scout is skipped
    plain = pipeline.Settings()
    fresh = run_conversion(source, output, settings=plain, checkpoint=tmp_path / "1" / "pin.json")
    assert fresh.counts["converted"] == 2
    assert calls == {"input": 2 * inputs, "decode": 2, "decompress": 2, "output": 6}
    calls.clear()
    reused = run_conversion(source, output, settings=plain, checkpoint=tmp_path / "2" / "pin.json")
    assert reused.counts["already_converted"] == 2
    assert calls == {"input": inputs, "output": 4}


def test_c11_task_manifest_hash_is_unchanged() -> None:
    """C11, DCM-27: the raw `task.json` bytes are hashed into task-run resume pins."""
    manifest = Path(__file__).parents[2] / "plugins" / "dicom" / "task.json"
    assert manifest_hash(manifest.read_bytes()) == TASK_JSON_HASH


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_c12_a35_cli_signal_stops_gracefully_and_resumes(
    tmp_path: Path, sig: signal.Signals
) -> None:
    """C12 → A35, DCM-33: the first signal stops dispatch, lets the running series finish and
    records `interrupted`; running the command again resumes and keeps committed images."""
    exit_code, journal = 1, "interrupted"
    source, out = tmp_path / "src", tmp_path / "out"
    for n in range(4):
        write_series(source / f"P{n:03d}", patient_id=f"P{n:03d}", **SERIES)  # type: ignore[arg-type]
    config = cli_config(tmp_path, source, out)
    slowed = """
import sys, time
from rw_dicom import cli, convert
original = convert.write_nifti
def slow(series, path):
    time.sleep(0.5)
    return original(series, path)
convert.write_nifti = slow
raise SystemExit(cli.main([sys.argv[1]]))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", slowed, str(config)],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 30
    while not list(out.glob(".rw-runs/*/outcomes.jsonl")) or not any(
        p.read_text() for p in out.glob(".rw-runs/*/outcomes.jsonl")
    ):
        assert time.monotonic() < deadline and process.poll() is None
        time.sleep(0.05)
    process.send_signal(sig)
    process.wait(timeout=30)
    assert process.returncode == exit_code
    assert json.loads((out / ".rw_active.json").read_text())["status"] == journal
    committed = {p.name: p.read_bytes() for p in (out / "nifti").glob("*.nii.gz")}
    assert 1 <= len(committed) < 4
    assert cli.main([str(config)]) == 0
    assert len(list((out / "nifti").glob("*.nii.gz"))) == 4
    assert all((out / "nifti" / name).read_bytes() == data for name, data in committed.items())
