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
from plugins.dicom import cli, commits, convert, pipeline, task

from app.config import Settings
from app.main import create_app
from app.tasks import protocol
from app.tasks.registry import manifest_hash
from tests.test_api_ingest import do_import, wait
from tests.test_dicom import convert as convert_in_project
from tests.test_dicom import project
from tests.test_dicom_resume import run_conversion
from tests.test_projects_v3 import neutral
from tools.dicom_fixtures import write_series

API = "/api/v1"
GOLDEN = Path(__file__).parent / "data" / "dicom" / "p7i_s1_golden.json"
SERIES = {"seed": "p7i-s1", "shape": (6, 5, 12), "marker": (2, 1, 3)}
# Pinned by task-run resume (C11); a change re-plans unfinished runs, see ADR-0042 §1.
TASK_JSON_HASH = "sha256:92ddcbc1605593aa1f2c66e1d338e66a51d456a652c6c9b1eb9c6d516d7d4572"


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


def test_c02_cli_matches_workspace_images_but_writes_fewer_artifacts(
    client: TestClient, tmp_path: Path
) -> None:
    """C02, DCM-09/14: same images, sidecars and rows; the CLI lacks four dataset files and
    silently ignores `anonymize` and `sidecars` (keys it does not map)."""
    source = seeded(tmp_path / "src")
    run = workspace_run(client, source, "parity")
    dataset = Path(run["dataset_dir"])
    out = tmp_path / "cli"
    config = cli_config(tmp_path, source, out, "anonymize: basic\nsidecars: false\n")
    assert cli.main([str(config)]) == 0
    workspace, standalone = (
        semantics(dataset, dataset / "metadata.jsonl"),
        semantics(out, out / "metadata.jsonl"),
    )
    assert standalone["images"] == workspace["images"]
    assert standalone["sidecars"] == workspace["sidecars"]  # sidecars written, not anonymized
    assert standalone["rows"] == workspace["rows"]
    for name in sorted((dataset / "nifti").glob("*.nii.gz")):
        assert (out / "nifti" / name.name).read_bytes() == name.read_bytes()
    assert {r["patient_id"] for r in jsonl(out / "metadata.jsonl")} == {"P001", "P002"}
    top = {p.name for p in dataset.iterdir()} - {p.name for p in out.iterdir()}
    assert top == {"annotations.jsonl", "dataset.json", "diagnostics.jsonl", "summary.json",
                   "conversion-pin.json"}  # fmt: skip
    assert {p.name for p in out.iterdir()} - {p.name for p in dataset.iterdir()} == {
        ".rw_identity.json",
        ".rw_active.json",
        ".rw-runs",
        ".rw-cli.lock",
    }


@pytest.mark.parametrize("change", ["selection_setting", "reader_version"])
def test_c03_c04_later_run_reports_committed_series_as_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """C03/C04, DCM-07/17: the commit identity pins every setting and the reader versions, so a
    later incremental run after a selection-setting or reader change cannot reuse any series."""
    source, out = seeded(tmp_path / "src"), tmp_path / "out"
    config = cli_config(tmp_path, source, out)
    assert cli.main([str(config)]) == 0
    images = {p.name: p.read_bytes() for p in (out / "nifti").glob("*.nii.gz")}
    if change == "selection_setting":  # selects the same series; no series has unsafe geometry
        config.write_text(config.read_text() + "conversion:\n  skip_unsafe_geometry: true\n")
    else:
        original = commits.reader_versions
        monkeypatch.setattr(
            commits, "reader_versions", lambda v: {**original(v), "SimpleITK": "0.0.0"}
        )
    assert cli.main([str(config)]) == 1
    rows = [r for r in jsonl(out / "metadata.jsonl") if r["planned_conversion"]]
    assert {r["status"] for r in rows} == {"failed"} and len(rows) == 2
    assert all("pinned inputs, settings or reader changed" in r["raw_metadata_error"] for r in rows)
    assert {p.name: p.read_bytes() for p in (out / "nifti").glob("*.nii.gz")} == images


def test_c05_workspace_manifests_can_be_torn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C05, DCM-14: `summary.json` and `dataset.json` are written in place without fsync, so a
    failure during the write leaves a partial file."""
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
    original = Path.write_text

    def torn(self: Path, data: str, *args: Any, **kwargs: Any) -> int:
        if self.name == "dataset.json":
            original(self, data[: len(data) // 2], *args, **kwargs)
            raise OSError("synthetic failure during write")
        return original(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", torn)
    with pytest.raises(OSError, match="synthetic"):
        task.run(str(job))
    manifest = tmp_path / "dataset" / "dataset.json"
    assert manifest.is_file()
    with pytest.raises(json.JSONDecodeError):
        json.loads(manifest.read_text())


def test_c06_incomplete_results_import_as_missing_items_or_not_at_all(
    client: TestClient, tmp_path: Path
) -> None:
    """C06, DCM-07/14, IMP-07: a partial workspace dataset has no `dataset.json` or annotations;
    importing it turns the failed series into a `missing` item with `missing_path` and brings no
    layers. A project conversion with a failed series is not registered."""
    source = seeded(tmp_path / "src", broken=True)
    run = workspace_run(client, source, "partial")
    assert run["status"] == "completed_with_errors", run
    dataset = Path(run["dataset_dir"])
    names = {p.name for p in dataset.iterdir()}
    assert "dataset.json" not in names and "annotations.jsonl" not in names
    assert {"metadata.jsonl", "diagnostics.jsonl", "summary.json"} <= names
    statuses = {(r["case_id"], r["status"]) for r in jsonl(dataset / "metadata.jsonl")}
    assert ("case_00001", "failed") in statuses and ("case_00000", "converted") in statuses
    pid = neutral(client)
    do_import(client, pid, dataset)
    failed = client.get(f"{API}/projects/{pid}/items/case_00001.01.complete.-").json()
    assert failed["status"] == "missing"
    assert "missing_path" in {w["code"] for w in failed["warnings"]}
    converted = client.get(f"{API}/projects/{pid}/items/case_00000.01.complete.-").json()
    assert converted["status"] == "active"
    assert not client.get(f"{API}/projects/{pid}").json()["annotation_sources"]
    in_project = project(client, tmp_path, preset="none")
    project_run = convert_in_project(client, in_project, source)
    assert project_run["status"] == "completed_with_errors", project_run
    assert not [o for o in project_run["outputs"] if o["kind"] == "import"]
    cases = client.get(f"{API}/projects/{in_project}/cases").json()["items"]
    assert cases == []


def test_c07_strict_verification_reads_every_input_twice_per_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C07, DCM-17: per run, each selected input is hashed twice (whole-run pin, then after decode
    or on reuse); reuse hashes each output and decompresses each image again."""
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
    assert calls == {"input": 2 * inputs, "decompress": 2, "output": 4}


def test_c11_task_manifest_hash_is_unchanged() -> None:
    """C11, DCM-27: the raw `task.json` bytes are hashed into task-run resume pins."""
    manifest = Path(__file__).parents[2] / "plugins" / "dicom" / "task.json"
    assert manifest_hash(manifest.read_bytes()) == TASK_JSON_HASH


@pytest.mark.parametrize(
    ("sig", "exit_code", "journal"),
    [
        (signal.SIGINT, -signal.SIGINT, "interrupted"),
        (signal.SIGTERM, -signal.SIGTERM, "running"),
        (signal.SIGHUP, -signal.SIGHUP, "running"),
    ],
)
def test_c12_cli_signal_leaves_a_resumable_run(
    tmp_path: Path, sig: signal.Signals, exit_code: int, journal: str
) -> None:
    """C12, DCM-09/17: SIGINT records `interrupted`; SIGTERM and SIGHUP end the process with the
    journal still `running`. Running the command again resumes and keeps committed images."""
    source, out = tmp_path / "src", tmp_path / "out"
    for n in range(4):
        write_series(source / f"P{n:03d}", patient_id=f"P{n:03d}", **SERIES)  # type: ignore[arg-type]
    config = cli_config(tmp_path, source, out)
    slowed = """
import sys, time
from plugins.dicom import cli, convert
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
