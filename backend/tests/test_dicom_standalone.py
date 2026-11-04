"""P7i acceptance of the standalone converter (DICOM_STANDALONE_TEST_PLAN A08, A10-A11, A22,
A30-A35; DCM-26..33): workers, crashes, memory admission, versions, batches, API and CLI."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from rw_dicom import api, cli, commits, pipeline
from rw_dicom.identity import Identity

from tools.dicom_fixtures import write_series

SERIES: dict[str, Any] = {"shape": (6, 5, 12), "marker": (2, 1, 3)}
REPO = Path(__file__).resolve().parents[2]


def source_tree(root: Path, patients: int = 4) -> Path:
    for n in range(patients):
        pid = f"P{n:03d}"
        write_series(root / pid / "a", patient_id=pid, seed=f"standalone-{pid}", **SERIES)
        write_series(
            root / pid / "b",
            patient_id=pid,
            description="NON CONTRAST ABDOMEN",
            series_number=5,
            seed=f"standalone-{pid}",
            **SERIES,
        )
    return root


def digests(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.suffix in {".gz", ".json"} and ".checkpoints" not in p.parts
    }


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def convert(source: Path, output: Path, **kwargs: Any) -> pipeline.Result:
    return pipeline.run(
        source,
        kwargs.pop("settings", pipeline.Settings()),
        Identity(),
        nifti_dir=output / "nifti",
        sidecar_dir=output / "sidecars",
        ref_rel="",
        ref_alias="DATA",
        salt="",
        previous=[],
        dry_run=False,
        checkpoint=output / "pin.json",
        **kwargs,
    )


def env_with(tmp_path: Path, sitecustomize: str) -> dict[str, str]:
    """Child processes import `sitecustomize` first: a way to inject faults into real workers."""
    hooks = tmp_path / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "sitecustomize.py").write_text(sitecustomize)
    return {**os.environ, "PYTHONPATH": os.pathsep.join([str(hooks), *sys.path])}


def test_a30_worker_count_never_changes_outputs_or_row_order(tmp_path: Path) -> None:
    """A30, DCM-32: 1 and 3 workers give identical bytes, rows and annotations."""
    source = source_tree(tmp_path / "src")
    serial = convert(source, tmp_path / "one", workers=1)
    pooled = convert(source, tmp_path / "three", workers=3, memory_mb=1_000_000)
    assert serial.counts == pooled.counts and pooled.counts["converted"] == 8
    assert digests(tmp_path / "one") == digests(tmp_path / "three")
    assert serial.rows == pooled.rows
    assert serial.annotations == pooled.annotations


def test_a31_a32_crashing_worker_fails_only_its_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A31, DCM-32: a native crash is retried once, then `worker_crashed`; others complete."""
    source = source_tree(tmp_path / "src", patients=3)
    monkeypatch.setenv(
        "PYTHONPATH",
        env_with(
            tmp_path,
            "import os\n"
            "from rw_dicom import pipeline\n"
            "original = pipeline.convert_unit\n"
            "def crash(job):\n"
            "    folder = job['series'].dicom_dir\n"
            "    if (folder.parent.name, folder.name) == ('P001', 'a'):\n"
            "        os._exit(70)\n"
            "    return original(job)\n"
            "pipeline.convert_unit = crash\n",
        )["PYTHONPATH"],
    )
    result = convert(source, tmp_path / "out", workers=2, memory_mb=1_000_000)
    assert result.counts["converted"] == 5 and result.counts["failed"] == 1
    [failed] = [r for r in result.rows if r["status"] == "failed"]
    assert (
        failed["failure_category"] == "worker_crashed" and "twice" in failed["raw_metadata_error"]
    )
    assert len(list((tmp_path / "out" / "nifti").glob("*.nii.gz"))) == 5


def _workers_of(parent: int) -> list[int]:
    found = []
    for proc in Path("/proc").iterdir():
        if proc.name.isdigit():
            try:
                fields = (proc / "stat").read_text().rpartition(") ")[2].split()
                cmd = (proc / "cmdline").read_bytes()
            except OSError:
                continue
            if int(fields[1]) == parent and b"rw_dicom.workers" in cmd:
                found.append(int(proc.name))
    return found


def test_a32_killed_coordinator_leaves_no_worker_and_resumes(tmp_path: Path) -> None:
    """A32, DCM-32/33: SIGKILL of `rw-dicom` kills its workers; running again completes."""
    source, out = source_tree(tmp_path / "src"), tmp_path / "out"
    env = env_with(
        tmp_path,
        "import time\nfrom rw_dicom import pipeline\noriginal = pipeline.convert_unit\n"
        "def slow(job):\n    time.sleep(0.4)\n    return original(job)\n"
        "pipeline.convert_unit = slow\n",
    )
    run = subprocess.Popen(
        [sys.executable, "-m", "rw_dicom.cli", "convert", str(source), str(out), "--workers", "2"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 60
    while not any(p.stat().st_size for p in out.glob(".rw-runs/*/outcomes.jsonl")):
        assert time.monotonic() < deadline and run.poll() is None
        time.sleep(0.05)
    workers = _workers_of(run.pid)
    assert workers
    run.send_signal(signal.SIGKILL)
    run.wait(timeout=10)
    deadline = time.monotonic() + 10
    while any(Path(f"/proc/{pid}").exists() and _alive(pid) for pid in workers):
        assert time.monotonic() < deadline, "workers outlived their coordinator"
        time.sleep(0.05)
    assert cli.main(["convert", str(source), str(out), "--workers", "2"]) == 0
    assert len(list((out / "nifti").glob("*.nii.gz"))) == 8


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rpartition(") ")[2].split()[0]
    except OSError:
        return False
    return state not in {"Z", "X"}


def test_a33_total_memory_budget_holds_back_series_that_do_not_fit(tmp_path: Path) -> None:
    """A33, DCM-32: a series above the total budget waits with its remedy; the run is resumable."""
    source = source_tree(tmp_path / "src", patients=2)
    waiting = convert(source, tmp_path / "out", workers=2, memory_mb=1)
    assert waiting.counts["converted"] == 0 and waiting.counts["pending"] == 4
    assert (
        waiting.resource_wait is not None
        and waiting.resource_wait["remedy"] == "configure:DICOM_MEMORY_MB"
    )
    resumed = convert(source, tmp_path / "out", workers=2, memory_mb=1_000_000)
    assert resumed.counts["converted"] == 4


def test_a22_new_series_from_other_readers_need_an_acknowledgment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A22, DCM-31: reuse keeps old provenance; adding new series with other readers is refused
    unless acknowledged, and the dataset then records both version sets."""
    source, out = source_tree(tmp_path / "src", patients=1), tmp_path / "out"
    assert cli.main(["convert", str(source), str(out), "--workers", "1"]) == 0
    original = commits.reader_versions
    monkeypatch.setattr(commits, "reader_versions", lambda v: {**original(v), "SimpleITK": "9.9.9"})
    write_series(source / "P900" / "a", patient_id="P900", seed="standalone-new", **SERIES)
    assert cli.main(["convert", str(source), str(out), "--workers", "1"]) == 1  # refused first
    assert len(list((out / "nifti").glob("*.nii.gz"))) == 2
    assert (
        cli.main(["convert", str(source), str(out), "--workers", "1", "--allow-mixed-versions"])
        == 0
    )
    versions = json.loads((out / "dataset.json").read_text())["units_by_versions"]
    assert sorted(v["count"] for v in versions.values()) == [1, 2]


def test_batches_make_one_dataset_per_group_of_patients(tmp_path: Path) -> None:
    """DCM-33/34, ADR-0040 pattern: frozen batches of patient folders, each a complete dataset."""
    source, out = source_tree(tmp_path / "src", patients=5), tmp_path / "out"
    assert cli.main(["convert", str(source), str(out), "--batch-size", "2"]) == 0
    batches = sorted(p.name for p in out.iterdir() if p.is_dir())
    assert batches == ["b01", "b02", "b03"]
    for name, cases in zip(batches, (2, 2, 1), strict=True):
        manifest = json.loads((out / name / "dataset.json").read_text())
        assert manifest["counts"]["converted"] == 2 * cases
        assert {r["case_id"] for r in jsonl(out / name / "metadata.jsonl")} == {
            f"case_{i:05d}" for i in range(cases)
        }
    assert (out / ".rw-batches.json").stat().st_mode & 0o077 == 0
    write_series(source / "P999" / "a", patient_id="P999", seed="late", **SERIES)
    summary = api.convert_batches(source, out, batch_size=2)
    assert summary["complete"] and summary["new_folders"] == 1
    assert all(item["status"] == "completed" for item in summary["batches"])
    status = api.status(out)
    assert [b["complete"] for b in status["batches"]] == [True, True, True]


def test_python_api_plans_without_writing_and_converts(tmp_path: Path) -> None:
    """A10, DCM-26: `api.convert` plans (no output state, no pixels) and converts."""
    source, out = source_tree(tmp_path / "src", patients=1), tmp_path / "out"
    plan = api.convert(source, out, mode="dry_run")
    assert plan["status"] == "planned" and len(plan["plan"]) == 2 and not out.exists()
    done = api.convert(source, out, settings={"anonymize": "basic"}, workers=2, memory_mb=1_000_000)
    assert done["complete"] and done["counts"]["converted"] == 2
    assert {r["patient_id"] for r in jsonl(out / "metadata.jsonl")} == {"case_00000"}
    with pytest.raises(ValueError, match="Unknown setting"):
        api.convert(source, tmp_path / "other", settings={"anonymise": "basic"})


def test_a11_cli_runs_without_ct_viewer_and_reports_versions(tmp_path: Path) -> None:
    """A11/A08, DCM-26: no `app`, `plugins` or FastAPI needed; the console script and the legacy
    `python -m plugins.dicom.cli config.yaml` both work."""
    source, out = source_tree(tmp_path / "src", patients=1), tmp_path / "out"
    blocked = (
        "import sys\n"
        "for name in ('app', 'plugins', 'fastapi', 'pydantic'):\n"
        "    sys.modules[name] = None\n"
        "from rw_dicom import cli\n"
        "raise SystemExit(cli.main(sys.argv[1:]))\n"
    )
    isolated = subprocess.run(
        [sys.executable, "-c", blocked, "convert", str(source), str(out)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert isolated.returncode == 0, isolated.stderr
    assert json.loads(isolated.stdout)["complete"] is True
    script = Path(sys.executable).with_name("rw-dicom")
    if script.exists():
        version = subprocess.run(
            [str(script), "--version"], capture_output=True, text=True, timeout=60
        )
        assert version.returncode == 0 and "SimpleITK" in json.loads(version.stdout)
    config = tmp_path / "legacy.yaml"
    config.write_text(f"dataset_root: {source}\noutput_root: {tmp_path / 'legacy'}\n")
    legacy = subprocess.run(
        [sys.executable, "-m", "plugins.dicom.cli", str(config)],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert legacy.returncode == 0, legacy.stderr
    assert digests(out / "nifti") == digests(tmp_path / "legacy" / "nifti")


def test_a16_parallel_header_parsing_builds_the_same_inventory(tmp_path: Path) -> None:
    """A16, DCM-15/32: discovery with parse processes writes exactly the serial inventory."""
    import sqlite3

    from rw_dicom.inventory import SourceInventory

    source = source_tree(tmp_path / "src", patients=3)
    (source / "P000" / "a" / "notes.txt").write_text("not dicom")
    (source / "P001" / "b" / "IM9999.dcm").write_bytes(b"\0" * 300)  # rejected candidate
    tables = []
    for processes in (1, 4):
        path = tmp_path / f"inv{processes}.sqlite"
        with SourceInventory(path, source) as inventory:
            summary = inventory.scan(processes=processes)
            assert summary["complete"] is False or summary["dicom"] == 72
        db = sqlite3.connect(path)
        tables.append(
            (
                db.execute("SELECT d.rel, f.name, f.kind, f.size, f.delta, f.error FROM files f "
                           "JOIN directories d ON d.id=f.directory_id ORDER BY 1, 2").fetchall(),
                db.execute("SELECT key, uid, header FROM series ORDER BY key").fetchall(),
            )
        )  # fmt: skip
        db.close()
    assert tables[0] == tables[1] and len(tables[0][1]) == 6
