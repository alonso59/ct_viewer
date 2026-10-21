"""TST-21 GPU-host acceptance through the API, external runner and real nnU-Net CLI.

The command generates a disposable synthetic source dataset unless `--root` is given. It keeps
the workspace for review, hashes every source file before and after, and exits nonzero unless a
new indexed segmentation set contains every requested item.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import nibabel as nib
from fastapi.testclient import TestClient

from app.config import Settings
from app.context import AppContext
from app.main import create_app
from tools.make_fixtures import DATASET, generate

API = "/api/v1"
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def sha_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        out[path.relative_to(root).as_posix()] = digest.hexdigest()
    return out


def wait_job(client: TestClient, job_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: tuple[str, int] | None = None
    while time.monotonic() < deadline:
        response = client.get(f"{API}/jobs/{job_id}")
        response.raise_for_status()
        job: dict[str, Any] = response.json()
        current = str(job["status"]), int(job["done"])
        if current != last:
            print(f"  {current[0]}: {current[1]}/{job['total']}", file=sys.stderr)
            last = current
        if current[0] in TERMINAL:
            return job
        time.sleep(1)
    raise TimeoutError(f"job {job_id} did not finish within {timeout:g} seconds")


def context(client: TestClient) -> AppContext:
    ctx: AppContext = client.app.state.ctx  # type: ignore[attr-defined]
    return ctx


def import_root(client: TestClient, project_id: str, root: Path, timeout: float) -> None:
    preview = client.post(f"{API}/projects/{project_id}/imports/preview", json={"root": str(root)})
    preview.raise_for_status()
    commit = client.post(
        f"{API}/projects/{project_id}/imports",
        json={"preview_id": preview.json()["preview_id"]},
    )
    commit.raise_for_status()
    job = wait_job(client, str(commit.json()["job_id"]), timeout)
    if job["status"] != "succeeded":
        raise RuntimeError(f"dataset import failed: {job}")


def ready_items(client: TestClient, project_id: str, count: int) -> list[str]:
    ctx = context(client)
    resolver = ctx.workspace.resolver(project_id)
    selected: list[str] = []
    for item in ctx.index.load(project_id).items:
        if item.modality != "CT" or item.image is None or item.image.format != "nifti":
            continue
        path = resolver.resolve(item.image.ref)
        try:
            image: Any = nib.load(path)
            if len(image.header.get_data_shape()) != 3:
                continue
        except (OSError, ValueError):
            continue
        selected.append(item.item_id)
        if len(selected) == count:
            return selected
    raise RuntimeError(f"only {len(selected)} valid CT NIfTI items are available; need {count}")


def run(args: argparse.Namespace) -> int:
    workspace = (args.workspace or Path(tempfile.mkdtemp(prefix="rw-nnunet-acceptance-"))).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if args.root is None:
        generated = workspace / "source"
        generate(generated)
        root = generated / DATASET
    else:
        root = args.root.resolve()
    derived = workspace / "derived"
    derived.mkdir(exist_ok=True)
    before = sha_tree(root)
    gpu_ids = [value.strip() for value in args.gpus.split(",") if value.strip()]
    if not 2 <= len(gpu_ids) <= 4 or len(set(gpu_ids)) != len(gpu_ids):
        raise ValueError("--gpus must list 2 to 4 distinct GPU ids")
    settings = Settings(
        workspace_root=workspace / "app",
        allowed_data_roots=str(root),
        allowed_derived_roots=str(derived),
        plugins_root=args.plugins.resolve(),
        job_workers=2,
        _env_file=None,  # type: ignore[call-arg]
    )
    runner_log = workspace / "runner.log"
    runner: subprocess.Popen[bytes] | None = None
    ok = False
    summary: dict[str, Any] = {"workspace": str(workspace), "root": str(root)}
    try:
        with TestClient(create_app(settings, inline_jobs=True)) as client:
            created = client.post(
                f"{API}/projects", json={"name": "TST-21 nnU-Net", "packs": ["ccrcc"]}
            )
            created.raise_for_status()
            project_id = str(created.json()["project_id"])
            import_root(client, project_id, root, args.timeout)
            registered = client.put(
                f"{API}/projects/{project_id}/roots/DERIVED",
                json={"path": str(derived), "role": "derived"},
            )
            registered.raise_for_status()
            item_ids = ready_items(client, project_id, args.items)
            runner_env = {
                **os.environ,
                "PATH": f"{args.runner_python.resolve().parent}:{os.environ['PATH']}",
                "CUDA_VISIBLE_DEVICES": ",".join(gpu_ids),
                "nnUNet_results": str(args.results_root.resolve()),
            }
            with runner_log.open("wb") as log_handle:
                runner = subprocess.Popen(
                    [
                        str(args.runner_python.resolve()),
                        str(args.runner.resolve()),
                        "--workspace",
                        str(settings.workspace_root),
                        "--plugins",
                        str(args.plugins.resolve()),
                        "--tasks",
                        "segment.nnunet",
                        "--concurrency",
                        "1",
                        "--poll",
                        "0.5",
                    ],
                    env=runner_env,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                )
            started = client.post(
                f"{API}/projects/{project_id}/task-runs",
                json={
                    "task_id": "segment.nnunet",
                    "name": f"TST-21 real Dataset220 ({args.items} items)",
                    "settings": {
                        "profile": "kits2023-dataset220",
                        "gpu_cap": min(args.gpu_cap, len(gpu_ids)),
                        "seg_id": f"tst21-kits-{args.items}",
                    },
                    "selection": {"item_ids": item_ids},
                },
                headers={"X-Reviewer": "German Pinedo"},
            )
            started.raise_for_status()
            payload = started.json()
            job = wait_job(client, str(payload["job_id"]), args.timeout)
            run_detail = client.get(
                f"{API}/projects/{project_id}/task-runs/{payload['run_id']}"
            ).json()
            sets = {
                row["seg_id"]: row
                for row in client.get(f"{API}/projects/{project_id}/segmentations").json()
            }
            seg_id = f"tst21-kits-{args.items}"
            masks_servable = True
            for item_id in item_ids:
                response = client.get(
                    f"{API}/projects/{project_id}/items/{item_id}/mask",
                    params={"seg": seg_id},
                    headers={"Range": "bytes=0-99"},
                )
                masks_servable = masks_servable and response.status_code in {200, 206}
            source_after = sha_tree(root)
            ok = (
                job["status"] == "succeeded"
                and run_detail["status"] == "completed"
                and run_detail["counts"]["ok"] == args.items
                and sets.get(seg_id, {}).get("n_items") == args.items
                and masks_servable
                and before == source_after
            )
            summary.update(
                {
                    "project_id": project_id,
                    "run_id": payload["run_id"],
                    "job": job["status"],
                    "run": run_detail["status"],
                    "counts": run_detail["counts"],
                    "segmentation": sets.get(seg_id),
                    "masks_servable": masks_servable,
                    "provenance": run_detail.get("provenance"),
                    "sources_hashed": len(before),
                    "sources_changed": sorted(
                        key for key, digest in source_after.items() if before.get(key) != digest
                    ),
                    "runner_log": str(runner_log),
                    "pass": ok,
                }
            )
    finally:
        if runner is not None:
            runner.terminate()
            try:
                runner.wait(15)
            except subprocess.TimeoutExpired:
                runner.kill()
                runner.wait(5)
    print(json.dumps(summary, indent=2))
    return 0 if ok else 1


def main() -> None:
    repository = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, help="existing dataset root; default: synthetic")
    parser.add_argument("--workspace", type=Path, help="audit workspace; default: new /tmp folder")
    parser.add_argument("--items", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--gpus", default="0,1", help="2 to 4 CUDA_VISIBLE_DEVICES ids")
    parser.add_argument("--gpu-cap", type=int, choices=range(2, 5), default=2)
    parser.add_argument(
        "--results-root", type=Path, default=Path("/home/alonso/nnUNet_models/nnUNet_results")
    )
    parser.add_argument(
        "--runner-python", type=Path, default=Path("/home/alonso/miniconda3/envs/torch/bin/python")
    )
    parser.add_argument("--runner", type=Path, default=repository / "scripts" / "rw-runner.py")
    parser.add_argument("--plugins", type=Path, default=repository / "plugins")
    parser.add_argument("--timeout", type=float, default=3600)
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
