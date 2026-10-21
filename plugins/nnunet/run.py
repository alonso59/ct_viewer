"""Run official nnU-Net v2 inference in GPU-partitioned external task jobs (SEG-*)."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from plugins.nnunet.profile import Predictor, Profile, load_profile
    from plugins.protocol import Job
except ImportError:  # runner cwd is plugins/nnunet
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from plugins.nnunet.profile import Predictor, Profile, load_profile
    from plugins.protocol import Job

VERSION = "0.1.0"
PREDICT = "nnUNetv2_predict"
POSTPROCESS = "nnUNetv2_apply_postprocessing"
POLL_S = 0.2
TERM_GRACE_S = 10.0
_cancelled = threading.Event()


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Staged:
    token: str
    item_id: str
    image: Path


@dataclass
class Child:
    name: str
    process: subprocess.Popen[bytes]


def _on_signal(_signum: int, _frame: Any) -> None:
    _cancelled.set()


def _gpu_ids() -> list[str]:
    raw = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    values = [value.strip() for value in raw.split(",") if value.strip()]
    if not 2 <= len(values) <= 4 or len(set(values)) != len(values) or "-1" in values:
        raise ValueError("CUDA_VISIBLE_DEVICES must expose 2 to 4 distinct GPUs")
    return values


def _command_exists(name: str) -> None:
    if shutil.which(name) is None:
        raise ValueError(f"required nnU-Net command is unavailable: {name}")


def _stage(job: Job, scratch: Path) -> list[Staged]:
    input_dir = scratch / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    staged: list[Staged] = []
    ordered = sorted(job.items, key=lambda item: str(item.get("item_id")))
    pending = [item for item in ordered if str(item.get("item_id")) not in job.skip]
    job.counts["items"] = len(pending)
    for ordinal, item in enumerate(ordered):
        item_id = str(item.get("item_id"))
        if item_id in job.skip:
            continue
        image = item.get("image")
        if not isinstance(image, dict) or image.get("format") != "nifti":
            job.item(item_id, "skipped", message="needs a NIfTI image")
            continue
        source = Path(str(image.get("path", ""))).resolve()
        if not source.is_file():
            job.item(item_id, "skipped", message="image is missing")
            continue
        token = f"case_{ordinal:06d}"
        target = input_dir / f"{token}_0000.nii.gz"
        target.symlink_to(source)
        staged.append(Staged(token, item_id, source))
    mapping = {item.token: item.item_id for item in staged}
    (scratch / "case-map.json").write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return staged


def _predict_command(
    profile: Profile,
    predictor: Predictor,
    input_dir: Path,
    output_dir: Path,
    parts: int,
    part_id: int,
) -> list[str]:
    return [
        PREDICT,
        "-d",
        profile.dataset,
        "-i",
        str(input_dir),
        "-o",
        str(output_dir),
        "-f",
        *(str(fold) for fold in predictor.folds),
        "-tr",
        predictor.trainer,
        "-c",
        predictor.configuration,
        "-p",
        predictor.plans,
        "-chk",
        predictor.checkpoint,
        "-npp",
        str(profile.preprocessing_per_gpu),
        "-nps",
        str(profile.export_per_gpu),
        "-num_parts",
        str(parts),
        "-part_id",
        str(part_id),
        "-device",
        "cuda",
        "--continue_prediction",
        "--disable_progress_bar",
    ]


def _spawn(name: str, command: list[str], env: dict[str, str]) -> Child:
    return Child(
        name,
        subprocess.Popen(command, env=env, start_new_session=True),
    )


def _terminate(children: list[Child]) -> None:
    alive = [child for child in children if child.process.poll() is None]
    for child in alive:
        try:
            os.killpg(child.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + TERM_GRACE_S
    while alive and time.monotonic() < deadline:
        alive = [child for child in alive if child.process.poll() is None]
        time.sleep(POLL_S)
    for child in alive:
        try:
            os.killpg(child.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _wait(job: Job, children: list[Child], stage: str) -> dict[str, int]:
    pending = list(children)
    codes: dict[str, int] = {}
    try:
        while pending:
            if _cancelled.is_set() or job.cancelled():
                raise Cancelled
            for child in list(pending):
                code = child.process.poll()
                if code is not None:
                    codes[child.name] = code
                    pending.remove(child)
            job.stage(stage, len(children) - len(pending), len(children))
            if pending:
                job.heartbeat()
                time.sleep(POLL_S)
    except BaseException:
        _terminate(children)
        raise
    return codes


def _link_outputs(source: Path, merged: Path) -> None:
    merged.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob("case_*.nii.gz")):
        target = merged / path.name
        if target.exists():
            raise ValueError(f"duplicate prediction output {path.name}")
        try:
            os.link(path, target)
        except OSError:
            shutil.copy2(path, target)


def _postprocess(job: Job, profile: Profile, source: Path, target: Path) -> int:
    pp = profile.postprocessing
    if pp is None:
        target.mkdir(parents=True, exist_ok=True)
        _link_outputs(source, target)
        return 0
    command = [
        POSTPROCESS,
        "-i",
        str(source),
        "-o",
        str(target),
        "-pp_pkl_file",
        str(profile.artifact(pp.pickle)),
        "-np",
        str(profile.export_per_gpu),
        "-plans_json",
        str(profile.artifact(pp.plans)),
        "-dataset_json",
        str(profile.artifact(pp.dataset)),
    ]
    child = _spawn("postprocessing", command, dict(os.environ))
    return _wait(job, [child], "postprocessing")[child.name]


def _validate_mask(image_path: Path, mask_path: Path, labels: dict[str, str]) -> None:
    import nibabel as nib
    import numpy as np

    image: Any = nib.load(image_path)
    mask: Any = nib.load(mask_path)
    if len(image.shape) != 3 or image.shape != mask.shape:
        raise ValueError("output shape differs from the input image")
    if not np.allclose(image.affine, mask.affine, rtol=0, atol=1e-4):
        raise ValueError("output affine differs from the input image")
    unique = np.unique(np.asanyarray(mask.dataobj))
    if not np.all(np.isfinite(unique)) or not np.all(unique == np.floor(unique)):
        raise ValueError("output contains non-integer label values")
    values = {int(value) for value in unique}
    allowed = {0, *(int(value) for value in labels)}
    unexpected = sorted(values - allowed)
    if unexpected:
        raise ValueError(f"output contains unexpected label values: {unexpected}")


def _publish(job: Job, item: Staged, mask: Path, labels: dict[str, str]) -> list[dict[str, Any]]:
    if job.output_dir is None:
        raise ValueError("job has no derived output directory")
    _validate_mask(item.image, mask, labels)
    job.output_dir.mkdir(parents=True, exist_ok=True)
    target = job.output_dir / f"{item.token}.nii.gz"
    if target.exists():
        raise ValueError("derived output already exists")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(mask, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return [{"kind": "mask", "path": str(target), "labels": labels}]


def _versions() -> dict[str, str]:
    versions = {"segment.nnunet": VERSION}
    for package in ("nnunetv2", "torch", "nibabel", "numpy"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "unknown"
    try:
        torch: Any = importlib.import_module("torch")
        versions["cuda"] = str(torch.version.cuda or "none")
    except ImportError:
        versions["cuda"] = "unknown"
    return versions


def _command_templates(profile: Profile, predictor: Predictor, parts: int) -> list[list[str]]:
    commands: list[list[str]] = []
    for part_id in range(parts):
        command = _predict_command(profile, predictor, Path("<staged-input>"), Path("<part-output>"), parts, part_id)
        commands.append(command)
    if profile.postprocessing is not None:
        commands.append(
            [
                POSTPROCESS,
                "-i",
                "<merged-output>",
                "-o",
                "<postprocessed-output>",
                "-pp_pkl_file",
                "<profile:postprocessing.pkl>",
                "-plans_json",
                "<profile:plans.json>",
                "-dataset_json",
                "<profile:dataset.json>",
            ]
        )
    return commands


def _execute(job: Job, profile: Profile, gpus: list[str]) -> dict[str, Any]:
    scratch = job.dir / "nnunet"
    scratch.mkdir(parents=True, exist_ok=True)
    staged = _stage(job, scratch)
    if not staged:
        return {
            "profile": profile.id,
            "profile_sha256": profile.profile_sha256,
            "model_artifacts_sha256": "sha256:" + profile.artifacts_sha256,
            "visible_gpus": gpus,
            "effective_gpus": [],
            "part_assignments": {},
            "commands": [],
        }
    gpu_cap = int(job.settings.get("gpu_cap", 2))
    if not 2 <= gpu_cap <= 4:
        raise ValueError("gpu_cap must be from 2 to 4")
    parts = min(len(staged), len(gpus), gpu_cap)
    predictor = profile.predictors[0]
    part_dirs = [scratch / "predict" / f"part-{part_id}" for part_id in range(parts)]
    children: list[Child] = []
    for part_id, part_dir in enumerate(part_dirs):
        part_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": gpus[part_id]}
        children.append(
            _spawn(
                f"part-{part_id}",
                _predict_command(profile, predictor, scratch / "input", part_dir, parts, part_id),
                env,
            )
        )
    codes = _wait(job, children, "prediction")
    merged = scratch / "merged"
    for part_id, part_dir in enumerate(part_dirs):
        if codes[f"part-{part_id}"] == 0:
            _link_outputs(part_dir, merged)
    final = scratch / "postprocessed"
    successful_parts = {part_id for part_id in range(parts) if codes[f"part-{part_id}"] == 0}
    post_code = _postprocess(job, profile, merged, final) if successful_parts else 1
    assignments = {str(part_id): [item.item_id for item in staged[part_id::parts]] for part_id in range(parts)}
    for index, item in enumerate(staged):
        part_id = index % parts
        if part_id not in successful_parts:
            job.item(
                item.item_id,
                "failed",
                message=f"prediction part {part_id} exited with code {codes[f'part-{part_id}']}",
            )
            continue
        if post_code != 0:
            job.item(item.item_id, "failed", message=f"postprocessing exited with code {post_code}")
            continue
        try:
            output = _publish(job, item, final / f"{item.token}.nii.gz", profile.labels)
        except Exception as exc:  # noqa: BLE001 - isolate a bad output to its item
            job.item(item.item_id, "failed", message=f"{type(exc).__name__}: {exc}")
        else:
            job.item(item.item_id, "ok", output)
    return {
        "profile": profile.id,
        "profile_sha256": profile.profile_sha256,
        "model_artifacts_sha256": "sha256:" + profile.artifacts_sha256,
        "dataset": profile.dataset,
        "pipeline": [
            {
                "trainer": predictor.trainer,
                "plans": predictor.plans,
                "configuration": predictor.configuration,
                "folds": list(predictor.folds),
                "checkpoint": predictor.checkpoint,
                "postprocessing": profile.postprocessing is not None,
            }
        ],
        "visible_gpus": gpus,
        "effective_gpus": gpus[:parts],
        "part_assignments": assignments,
        "processes": {
            "preprocessing_per_gpu": profile.preprocessing_per_gpu,
            "export_per_gpu": profile.export_per_gpu,
        },
        "commands": _command_templates(profile, predictor, parts),
    }


def run(job_dir: str) -> int:
    _cancelled.clear()
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    job = Job(job_dir)
    versions: dict[str, str] = {"segment.nnunet": VERSION}
    try:
        _command_exists(PREDICT)
        _command_exists(POSTPROCESS)
        profile = load_profile(str(job.settings.get("profile", "kits2023-dataset220")))
        gpus = _gpu_ids()
        provenance = _execute(job, profile, gpus)
        versions = _versions()
        job.finish(versions=versions, extra={"provenance": provenance})
        return 0
    except Cancelled:
        job.finish(versions=versions, status="cancelled")
        return 0
    except Exception as exc:  # noqa: BLE001 - protocol must return a terminal result
        already = job.counts["ok"] + job.counts["failed"] + job.counts["skipped"]
        if already == 0:
            pending = [item for item in job.items if str(item.get("item_id")) not in job.skip]
            job.counts["items"] = len(pending)
            for item in pending:
                job.item(
                    str(item.get("item_id")),
                    "failed",
                    message=f"{type(exc).__name__}: {exc}",
                )
        job.log(f"{type(exc).__name__}: {exc}", "error")
        job.finish(versions=versions, status="failed", error=f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]) if len(sys.argv) == 2 else 2)
