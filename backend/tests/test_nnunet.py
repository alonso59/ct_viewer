"""TST-21: profile, official CLI partitioning, outputs, cancellation and registration."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from plugins.nnunet.profile import load_profile

from app.config import Settings
from app.main import create_app
from tests.test_api_ingest import ctx_of, do_import, wait
from tools.make_fixtures import DATASET

API = "/api/v1"
REPO = Path(__file__).resolve().parents[2]
RUN = REPO / "plugins" / "nnunet" / "run.py"
RUNNER = REPO / "scripts" / "rw-runner.py"
PROFILE_ID = "kits2023-dataset220"
DATASET_ID = "Dataset220_KiTS2023"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def make_model(tmp_path: Path) -> tuple[Path, Path]:
    results = tmp_path / "models"
    profiles = tmp_path / "profiles"
    profiles.mkdir(parents=True)
    dataset = results / DATASET_ID
    model = dataset / "nnUNetTrainer__Plans__3d_fullres"
    cv = model / "cv"
    (model / "fold_0").mkdir(parents=True)
    cv.mkdir()
    dataset_json = {
        "channel_names": {"0": "CT"},
        "labels": {"background": 0, "kidney": [1, 2, 3], "masses": [2, 3], "tumor": 2},
        "regions_class_order": [1, 3, 2],
        "file_ending": ".nii.gz",
    }
    files: dict[str, bytes] = {
        "nnUNetTrainer__Plans__3d_fullres/dataset.json": json.dumps(dataset_json).encode(),
        "nnUNetTrainer__Plans__3d_fullres/plans.json": b"{}",
        "nnUNetTrainer__Plans__3d_fullres/fold_0/checkpoint_final.pth": b"checkpoint",
        "nnUNetTrainer__Plans__3d_fullres/cv/postprocessing.pkl": b"postprocessing",
        "nnUNetTrainer__Plans__3d_fullres/cv/plans.json": b"{}",
        "nnUNetTrainer__Plans__3d_fullres/cv/dataset.json": json.dumps(dataset_json).encode(),
    }
    artifacts: list[dict[str, str]] = []
    manifest = hashlib.sha256()
    for relative, content in sorted(files.items()):
        path = dataset / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        digest = sha256(path)
        artifacts.append({"path": relative, "sha256": digest})
        manifest.update(f"{digest}  {relative}\n".encode())
    profile = {
        "profile": 1,
        "id": PROFILE_ID,
        "title": "test KiTS",
        "dataset": DATASET_ID,
        "channels": {"0": "CT"},
        "labels": {"1": "kidney", "2": "tumor", "3": "masses"},
        "regions_class_order": [1, 3, 2],
        "predictors": [
            {
                "configuration": "3d_fullres",
                "trainer": "nnUNetTrainer",
                "plans": "Plans",
                "folds": [0],
                "checkpoint": "checkpoint_final.pth",
            }
        ],
        "postprocessing": {
            "pickle": "nnUNetTrainer__Plans__3d_fullres/cv/postprocessing.pkl",
            "plans": "nnUNetTrainer__Plans__3d_fullres/cv/plans.json",
            "dataset": "nnUNetTrainer__Plans__3d_fullres/cv/dataset.json",
        },
        "processes": {"preprocessing_per_gpu": 2, "export_per_gpu": 2},
        "artifacts": artifacts,
        "artifacts_sha256": manifest.hexdigest(),
    }
    (profiles / f"{PROFILE_ID}.json").write_text(json.dumps(profile), encoding="utf-8")
    return results, profiles


def make_fake_cli(tmp_path: Path) -> tuple[Path, Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    log = tmp_path / "fake-cli.jsonl"
    script = bindir / "fake.py"
    script.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

import nibabel as nib
import numpy as np

name = Path(sys.argv[0]).name
args = sys.argv[1:]

def value(flag):
    return args[args.index(flag) + 1]

record = {
    "tool": name,
    "args": args,
    "cuda": os.environ.get("CUDA_VISIBLE_DEVICES"),
    "pid": os.getpid(),
}
with Path(os.environ["FAKE_NNUNET_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\n")
if os.environ.get("FAKE_NNUNET_SLEEP") and name == "nnUNetv2_predict":
    time.sleep(float(os.environ["FAKE_NNUNET_SLEEP"]))
if name == "nnUNetv2_predict":
    part = int(value("-part_id"))
    parts = int(value("-num_parts"))
    if os.environ.get("FAKE_NNUNET_FAIL_PART") == str(part):
        raise SystemExit(7)
    source, target = Path(value("-i")), Path(value("-o"))
    target.mkdir(parents=True, exist_ok=True)
    cases = sorted(source.glob("*_0000.nii.gz"))[part::parts]
    for case in cases:
        image = nib.load(case)
        mask = (np.asanyarray(image.dataobj) > 0).astype(np.uint8)
        affine = image.affine.copy()
        token = case.name.removesuffix("_0000.nii.gz")
        if os.environ.get("FAKE_NNUNET_BAD_GEOMETRY") == token:
            affine[0, 3] += 10
        nib.save(nib.Nifti1Image(mask, affine), target / f"{token}.nii.gz")
elif name == "nnUNetv2_apply_postprocessing":
    source, target = Path(value("-i")), Path(value("-o"))
    target.mkdir(parents=True, exist_ok=True)
    for path in source.glob("case_*.nii.gz"):
        shutil.copy2(path, target / path.name)
else:
    raise SystemExit(2)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    for command in ("nnUNetv2_predict", "nnUNetv2_apply_postprocessing"):
        (bindir / command).symlink_to(script)
    return bindir, log


def make_images(tmp_path: Path, n: int) -> list[dict[str, Any]]:
    source = tmp_path / "source"
    source.mkdir()
    items: list[dict[str, Any]] = []
    for index in range(n):
        path = source / f"image-{index}.nii.gz"
        data = np.zeros((8, 9, 10), dtype=np.int16)
        data[2:6, 2:7, 2:8] = index + 1
        affine = np.diag([1.1, 1.2, 1.3, 1.0])
        nib.save(nib.Nifti1Image(data, affine), path)
        items.append(
            {
                "item_id": f"item-{index}",
                "image": {"path": str(path), "format": "nifti"},
            }
        )
    return items


def write_job(
    job_dir: Path,
    items: list[dict[str, Any]],
    output: Path,
    skip: list[str] | None = None,
) -> None:
    job_dir.mkdir()
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "protocol": 1,
                "task": {"id": "segment.nnunet", "version": "0.1.0"},
                "settings": {"profile": PROFILE_ID, "gpu_cap": 2},
                "items": items,
                "output_dir": str(output),
                "resume": {"skip": skip or []},
            }
        ),
        encoding="utf-8",
    )


def plugin_env(tmp_path: Path, results: Path, profiles: Path, **extra: str) -> dict[str, str]:
    bindir, log = make_fake_cli(tmp_path)
    return {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE_NNUNET_LOG": str(log),
        "nnUNet_results": str(results),
        "RW_NNUNET_PROFILES_DIR": str(profiles),
        "CUDA_VISIBLE_DEVICES": "2,5",
        **extra,
    }


def run_plugin(job_dir: Path, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(RUN), str(job_dir)], env=env, timeout=30, check=False
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_profile_refuses_hash_and_label_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results, profiles = make_model(tmp_path)
    profile_path = profiles / f"{PROFILE_ID}.json"
    raw = json.loads(profile_path.read_text())
    monkeypatch.setenv("nnUNet_results", str(results))
    monkeypatch.setenv("RW_NNUNET_PROFILES_DIR", str(profiles))
    assert load_profile(PROFILE_ID).labels == {"1": "kidney", "3": "masses", "2": "tumor"}
    profile_path.write_text(json.dumps({**raw, "predictors": raw["predictors"] * 2}))
    with pytest.raises(ValueError, match="exactly one prediction"):
        load_profile(PROFILE_ID)
    artifacts = [
        artifact
        for artifact in raw["artifacts"]
        if not artifact["path"].endswith("checkpoint_final.pth")
    ]
    manifest = hashlib.sha256()
    for artifact in artifacts:
        manifest.update(f"{artifact['sha256']}  {artifact['path']}\n".encode())
    profile_path.write_text(
        json.dumps({**raw, "artifacts": artifacts, "artifacts_sha256": manifest.hexdigest()})
    )
    with pytest.raises(ValueError, match="not fingerprinted"):
        load_profile(PROFILE_ID)
    profile_path.write_text(json.dumps(raw))
    checkpoint = next(results.rglob("checkpoint_final.pth"))
    checkpoint.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_profile(PROFILE_ID)


def test_partition_postprocess_provenance_and_immutable_sources(tmp_path: Path) -> None:
    results, profiles = make_model(tmp_path)
    items = make_images(tmp_path, 3)
    source_before = tree_hashes(tmp_path / "source")
    job_dir, output = tmp_path / "job", tmp_path / "derived"
    write_job(job_dir, items, output)
    env = plugin_env(tmp_path / "fake", results, profiles)
    proc = run_plugin(job_dir, env)
    assert proc.returncode == 0
    result = json.loads((job_dir / "result.json").read_text())
    progress = read_jsonl(job_dir / "progress.jsonl")
    item_rows = [row for row in progress if row["t"] == "item"]
    assert result["status"] == "completed" and {row["status"] for row in item_rows} == {"ok"}
    calls = read_jsonl(Path(env["FAKE_NNUNET_LOG"]))
    predicts = [call for call in calls if call["tool"] == "nnUNetv2_predict"]
    assert {call["cuda"] for call in predicts} == {"2", "5"}
    assert all(call["args"][call["args"].index("-num_parts") + 1] == "2" for call in predicts)
    assert all("--continue_prediction" in call["args"] for call in predicts)
    assert len(list(output.glob("*.nii.gz"))) == 3
    assert tree_hashes(tmp_path / "source") == source_before
    provenance = result["provenance"]
    assert provenance["effective_gpus"] == ["2", "5"]
    assert provenance["part_assignments"] == {"0": ["item-0", "item-2"], "1": ["item-1"]}
    serialized = json.dumps(provenance)
    assert str(tmp_path / "source") not in serialized


def test_partial_failure_geometry_rejection_and_resume_skip(tmp_path: Path) -> None:
    results, profiles = make_model(tmp_path)
    items = make_images(tmp_path, 4)
    failed_job, failed_out = tmp_path / "failed-job", tmp_path / "failed-out"
    write_job(failed_job, items, failed_out)
    env = plugin_env(tmp_path / "failed-fake", results, profiles, FAKE_NNUNET_FAIL_PART="1")
    assert run_plugin(failed_job, env).returncode == 0
    result = json.loads((failed_job / "result.json").read_text())
    assert result["status"] == "completed_with_errors"
    rows = {
        row["item_id"]: row
        for row in read_jsonl(failed_job / "progress.jsonl")
        if row["t"] == "item"
    }
    assert {key for key, row in rows.items() if row["status"] == "ok"} == {"item-0", "item-2"}

    geometry_job, geometry_out = tmp_path / "geometry-job", tmp_path / "geometry-out"
    write_job(geometry_job, items[:2], geometry_out)
    env = plugin_env(
        tmp_path / "geometry-fake",
        results,
        profiles,
        FAKE_NNUNET_BAD_GEOMETRY="case_000000",
    )
    assert run_plugin(geometry_job, env).returncode == 0
    rows = [row for row in read_jsonl(geometry_job / "progress.jsonl") if row["t"] == "item"]
    assert [row["status"] for row in rows] == ["failed", "ok"]
    assert "affine" in rows[0]["message"]

    resume_job, resume_out = tmp_path / "resume-job", tmp_path / "resume-out"
    resume_out.mkdir()
    existing = resume_out / "case_000000.nii.gz"
    existing.write_bytes(b"registered")
    write_job(resume_job, items[:3], resume_out, skip=["item-0"])
    before = existing.read_bytes()
    env = plugin_env(tmp_path / "resume-fake", results, profiles)
    assert run_plugin(resume_job, env).returncode == 0
    rows = [row for row in read_jsonl(resume_job / "progress.jsonl") if row["t"] == "item"]
    assert {row["item_id"] for row in rows} == {"item-1", "item-2"}
    assert existing.read_bytes() == before
    assert {path.name for path in resume_out.glob("*.nii.gz")} == {
        "case_000000.nii.gz",
        "case_000001.nii.gz",
        "case_000002.nii.gz",
    }


def test_cancel_terminates_prediction_group(tmp_path: Path) -> None:
    results, profiles = make_model(tmp_path)
    items = make_images(tmp_path, 2)
    job_dir = tmp_path / "job"
    write_job(job_dir, items, tmp_path / "derived")
    env = plugin_env(tmp_path / "fake", results, profiles, FAKE_NNUNET_SLEEP="20")
    process = subprocess.Popen([sys.executable, str(RUN), str(job_dir)], env=env)
    log = Path(env["FAKE_NNUNET_LOG"])
    deadline = time.monotonic() + 10
    while not log.is_file() or len(log.read_text().splitlines()) < 2:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    child_pids = [row["pid"] for row in read_jsonl(log)]
    (job_dir / "cancel").touch()
    assert process.wait(15) == 0
    result = json.loads((job_dir / "result.json").read_text())
    assert result["status"] == "cancelled"
    for pid in child_pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, signal.SIGCONT)


@pytest.fixture
def external_env(
    tmp_path: Path, fixtures_copy: Path
) -> Iterator[tuple[TestClient, str, Path, dict[str, str], Path]]:
    derived = tmp_path / "derived"
    derived.mkdir()
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "nnunet").symlink_to(REPO / "plugins" / "nnunet")
    results, profiles = make_model(tmp_path / "runtime")
    env = plugin_env(tmp_path / "fake-runtime", results, profiles)
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str((fixtures_copy / DATASET).resolve()),
        allowed_derived_roots=str(derived.resolve()),
        plugins_root=plugins,
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        pid = str(
            client.post(f"{API}/projects", json={"name": "nnunet", "packs": ["ccrcc"]}).json()[
                "project_id"
            ]
        )
        do_import(client, pid, fixtures_copy / DATASET)
        response = client.put(
            f"{API}/projects/{pid}/roots/DERIVED",
            json={"path": str(derived), "role": "derived"},
        )
        assert response.status_code == 200
        yield client, pid, plugins, env, fixtures_copy / DATASET


def test_external_runner_registers_indexed_segmentation_set(
    external_env: tuple[TestClient, str, Path, dict[str, str], Path],
) -> None:
    client, pid, plugins, env, source = external_env
    before = tree_hashes(source)
    item_ids = [
        item.item_id
        for item in ctx_of(client).index.load(pid).items
        if item.image is not None and item.modality == "CT"
    ][:3]
    assert len(item_ids) == 3
    started = client.post(
        f"{API}/projects/{pid}/task-runs",
        json={
            "task_id": "segment.nnunet",
            "settings": {"profile": PROFILE_ID, "gpu_cap": 2, "seg_id": "kits-prediction"},
            "selection": {"item_ids": item_ids},
        },
    )
    assert started.status_code == 202, started.text
    runner = subprocess.Popen(
        [
            sys.executable,
            str(RUNNER),
            "--workspace",
            str(ctx_of(client).settings.workspace_root),
            "--plugins",
            str(plugins),
            "--tasks",
            "segment.nnunet",
            "--concurrency",
            "1",
            "--poll",
            "0.1",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        wait(client, started.json()["job_id"])
        run = client.get(f"{API}/projects/{pid}/task-runs/{started.json()['run_id']}").json()
        assert run["status"] == "completed", run
        assert run["counts"]["ok"] == 3 and run["provenance"]["effective_gpus"] == ["2", "5"]
        segmentations = {
            row["seg_id"]: row for row in client.get(f"{API}/projects/{pid}/segmentations").json()
        }
        assert segmentations["kits-prediction"]["n_items"] == 3
        for item_id in item_ids:
            item = client.get(f"{API}/projects/{pid}/items/{item_id}").json()
            assert "kits-prediction" in item["masks"] and item["mask"] == item["masks"]["imported"]
            mask = client.get(
                f"{API}/projects/{pid}/items/{item_id}/mask",
                params={"seg": "kits-prediction"},
            )
            assert mask.status_code == 200 and mask.content
        assert tree_hashes(source) == before
    finally:
        runner.terminate()
        runner.wait(10)
