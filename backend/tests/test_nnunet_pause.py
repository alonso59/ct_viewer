"""SEG-15: incremental native batches preserve complete cases when dispatch pauses."""

from __future__ import annotations

import json
import signal
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from plugins.nnunet import run

from tests.test_nnunet import make_images, make_model, plugin_env, read_jsonl, write_job


@pytest.fixture(autouse=True)
def restore_signal_handlers() -> Iterator[None]:
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    yield
    for number, handler in previous.items():
        signal.signal(number, handler)


def test_pause_after_first_commit_does_not_dispatch_remaining_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results, profiles = make_model(tmp_path)
    job, output = tmp_path / "job", tmp_path / "derived"
    write_job(job, make_images(tmp_path, 3), output)
    env = plugin_env(tmp_path / "fake", results, profiles, CUDA_VISIBLE_DEVICES="0")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    publish = run._publish

    def pause_after_commit(*args: Any, **kwargs: Any) -> Any:
        published = publish(*args, **kwargs)
        (job / "pause").touch()
        return published

    monkeypatch.setattr(run, "_publish", pause_after_commit)
    assert run.run(str(job)) == 0
    result = json.loads((job / "result.json").read_text())
    assert result["status"] == "paused"
    assert result["counts"]["ok"] == 1
    assert len(list(output.glob("*.nii.gz"))) == 1
    calls = read_jsonl(Path(env["FAKE_NNUNET_LOG"]))
    assert [call["tool"] for call in calls] == ["nnUNetv2_predict", "nnUNetv2_apply_postprocessing"]


def test_unregistered_orphan_is_retained_without_blocking_retry(tmp_path: Path) -> None:
    from tests.test_nnunet import run_plugin

    results, profiles = make_model(tmp_path)
    job, output = tmp_path / "job", tmp_path / "derived"
    output.mkdir()
    orphan = output / "case_000000.nii.gz"
    orphan.write_bytes(b"unregistered output from an interrupted attempt")
    write_job(job, make_images(tmp_path, 1), output)
    env = plugin_env(tmp_path / "fake", results, profiles, CUDA_VISIBLE_DEVICES="0")
    assert run_plugin(job, env).returncode == 0
    result = json.loads((job / "result.json").read_text())
    assert result["counts"]["ok"] == 1
    assert orphan.read_bytes() == b"unregistered output from an interrupted attempt"
    assert len(list(output.glob("*.nii.gz"))) == 2


def test_publication_never_overwrites_a_file_created_during_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nibabel as nib
    import numpy as np
    from plugins.protocol import Job

    items = make_images(tmp_path, 1)
    image = Path(items[0]["image"]["path"])
    reference: Any = nib.load(image)
    mask = tmp_path / "mask.nii.gz"
    nib.save(nib.Nifti1Image(np.ones(reference.shape, dtype=np.uint8), reference.affine), mask)
    job_dir, output = tmp_path / "job", tmp_path / "derived"
    write_job(job_dir, items, output)
    job = Job(job_dir)
    target = output / "case_000000.nii.gz"
    copy = run.shutil.copyfile

    def competing_copy(source: Any, destination: Any) -> Any:
        value = copy(source, destination)
        target.write_bytes(b"immutable competing output")
        return value

    monkeypatch.setattr(run.shutil, "copyfile", competing_copy)
    try:
        with pytest.raises(FileExistsError):
            run._publish(job, run.Staged("case_000000", "one", image), mask, {"1": "foreground"})
        assert target.read_bytes() == b"immutable competing output"
    finally:
        job.finish(status="failed")
