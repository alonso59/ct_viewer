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
import numpy as np
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


LEASE = Path.home() / ".local/state/radiology-workbench/gpu-pool/lease.json"


def poll(probe: Any, timeout: float, what: str) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        time.sleep(2)
    raise TimeoutError(what)


def live_attempt_units() -> list[str]:
    out = subprocess.run(
        ["systemctl", "--user", "list-units", "--no-legend", "--state=active", "rw-seg-*"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [line.split()[0] for line in out.splitlines() if line.strip()]


def lifecycle(
    client: TestClient, project_id: str, item_ids: list[str], args: argparse.Namespace
) -> dict[str, Any]:
    """TSK-15 on the GPU host: pause after one committed case, resume, then cancel and archive."""
    base = f"{API}/projects/{project_id}/task-runs"
    headers = {"X-Reviewer": "TST-21 lifecycle"}
    resolver = context(client).workspace.resolver(project_id)

    def start(seg_id: str) -> tuple[str, str]:
        response = client.post(
            base,
            json={
                "task_id": "segment.nnunet",
                "name": f"TST-21 lifecycle {seg_id}",
                "settings": {"profile": "kits2023-dataset220", "gpu_cap": 1, "seg_id": seg_id},
                "selection": {"item_ids": item_ids},
            },
            headers=headers,
        )
        if response.status_code != 202:
            raise RuntimeError(f"start {seg_id}: {response.status_code} {response.text}")
        return f"{base}/{response.json()['run_id']}", str(response.json()["job_id"])

    def ready() -> bool:
        info = client.get(f"{API}/tasks/segment.nnunet").json()
        profiles = info["manifest"]["settings_schema"]["properties"]["profile"].get("enum", [])
        return bool(info.get("available") and info.get("runner_online")) and (
            "kits2023-dataset220" in profiles
        )

    def masks(url: str) -> dict[str, str]:
        rows = client.get(f"{url}/outputs").json()
        return {
            str(row["item_id"]): hashlib.sha256(
                resolver.resolve(row["ref"]).read_bytes()
            ).hexdigest()
            for row in rows
            if row["kind"] == "mask"
        }

    def settled(url: str, status: str) -> dict[str, Any] | None:
        detail: dict[str, Any] = client.get(url).json()
        control = detail.get("control") or {}
        return detail if detail["status"] == status and control.get("acknowledged_at") else None

    out: dict[str, Any] = {}
    poll(ready, 180, "runner catalog advertised")
    url, job_id = start("tst21-lifecycle")
    poll(lambda: masks(url), args.timeout, "first committed case before pause")
    out["pause_request"] = client.post(f"{url}/pause").json()["status"]
    wait_job(client, job_id, args.timeout)
    paused = poll(lambda: settled(url, "paused"), 120, "verified pause")
    committed = masks(url)
    out["paused"] = {
        "status": paused["status"],
        "committed": len(committed),
        "lease_released": not LEASE.exists(),
        "attempt_units": live_attempt_units(),
    }
    resumed = client.post(f"{url}/resume")
    resumed.raise_for_status()
    wait_job(client, str(resumed.json()["job_id"]), args.timeout)
    final = client.get(url).json()
    after = masks(url)
    out["resumed"] = {
        "status": final["status"],
        "counts": final["counts"],
        "committed_unchanged": all(after.get(k) == v for k, v in committed.items()),
        "masks": len(after),
    }

    url2, job2 = start("tst21-cancel")
    poll(lambda: client.get(url2).json()["status"] == "running", args.timeout, "cancel run claimed")
    time.sleep(10)  # let the attempt reach native inference
    out["cancel_request"] = client.post(f"{url2}/cancel").json()["status"]
    wait_job(client, job2, args.timeout)
    cancelled = poll(lambda: settled(url2, "cancelled"), 120, "verified cancel")
    archived = client.post(f"{url2}/archive")
    listed = [r["run_id"] for r in client.get(base).json()]
    out["cancelled"] = {
        "status": cancelled["status"],
        "lease_released": not LEASE.exists(),
        "attempt_units": live_attempt_units(),
        "archived": archived.status_code == 200 and archived.json()["archived"] is True,
        "hidden_from_list": url2.rsplit("/", 1)[1] not in listed,
    }
    out["pass"] = (
        out["pause_request"] in {"pausing", "paused"}
        and out["paused"]["lease_released"]
        and not out["paused"]["attempt_units"]
        and 1 <= out["paused"]["committed"] < len(item_ids)
        and out["resumed"]["status"] == "completed"
        and out["resumed"]["counts"]["ok"] == len(item_ids)
        and out["resumed"]["committed_unchanged"]
        and out["cancel_request"] in {"cancelling", "cancelled"}
        and out["cancelled"]["lease_released"]
        and not out["cancelled"]["attempt_units"]
        and out["cancelled"]["archived"]
        and out["cancelled"]["hidden_from_list"]
    )
    return out


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
    models_before = sha_tree(args.results_root.resolve())
    gpu_ids = [value.strip() for value in args.gpus.split(",") if value.strip()]
    if (
        not 1 <= len(gpu_ids) <= 7
        or len(set(gpu_ids)) != len(gpu_ids)
        or any(value not in {str(index) for index in range(7)} for value in gpu_ids)
    ):
        raise ValueError("--gpus must list unique approved physical GPU IDs from 0 to 6")
    settings = Settings(
        workspace_root=workspace / "app",
        allowed_data_roots=str(root),
        allowed_derived_roots=str(derived),
        plugins_root=args.plugins.resolve(),
        job_workers=2,
        _env_file=None,  # type: ignore[call-arg]
    )
    runner_log = workspace / "runner.log"
    deployment = workspace / "deployment.json"
    deployment_config = {
        "deployment": 1,
        "backend": args.backend,
        "environment": str(args.runner_python.absolute().parent.parent),
        "workspace": str(settings.workspace_root),
        "source_roots": [str(root)],
        "model_roots": [str(args.results_root.resolve())],
        "derived_roots": [str(derived)],
        "gpu_pool": gpu_ids,
        "limits": {
            "cpus": 12,
            "memory_mb": 32768,
            "tasks": 128,
            "seconds": max(60, int(args.timeout)),
            "gpus": 4,
        },
    }
    descriptor = os.open(deployment, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(deployment_config, handle, indent=2)
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
                        "--deployment",
                        str(deployment),
                        "--poll",
                        "0.5",
                    ],
                    env=runner_env,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                )
            if args.lifecycle:
                result = lifecycle(client, project_id, item_ids, args)
                source_after = sha_tree(root)
                models_after = sha_tree(args.results_root.resolve())
                ok = (
                    bool(result["pass"])
                    and before == source_after
                    and models_before == models_after
                )
                summary.update(
                    result,
                    sources_unchanged=before == source_after,
                    models_unchanged=models_before == models_after,
                    runner_log=str(runner_log),
                    passed=ok,
                )
            else:
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
                geometry_ok = True
                resolver = context(client).workspace.resolver(project_id)
                indexed = {
                    item.item_id: item for item in context(client).index.load(project_id).items
                }
                for item_id in item_ids:
                    item = indexed[item_id]
                    mask_ref = item.masks.get(seg_id)
                    if item.image is None or mask_ref is None:
                        geometry_ok = False
                        continue
                    image: Any = nib.load(resolver.resolve(item.image.ref))
                    mask: Any = nib.load(resolver.resolve(mask_ref.ref))
                    geometry_ok = geometry_ok and (
                        image.shape == mask.shape
                        and np.allclose(image.affine, mask.affine, rtol=0, atol=1e-4)
                        and set(np.unique(np.asanyarray(mask.dataobj))).issubset({0, 1, 2, 3})
                    )
                source_after = sha_tree(root)
                models_after = sha_tree(args.results_root.resolve())
                ok = (
                    job["status"] == "succeeded"
                    and run_detail["status"] == "completed"
                    and run_detail["counts"]["ok"] == args.items
                    and sets.get(seg_id, {}).get("n_items") == args.items
                    and masks_servable
                    and geometry_ok
                    and before == source_after
                    and models_before == models_after
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
                        "geometry_and_labels": bool(geometry_ok),
                        "provenance": run_detail.get("provenance"),
                        "sources_hashed": len(before),
                        "sources_changed": sorted(
                            key
                            for key in before.keys() | source_after.keys()
                            if before.get(key) != source_after.get(key)
                        ),
                        "models_hashed": len(models_before),
                        "models_changed": sorted(
                            key
                            for key in models_before.keys() | models_after.keys()
                            if models_before.get(key) != models_after.get(key)
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
    parser.add_argument(
        "--gpus", default="0", help="Approved physical GPU IDs 0..6, checked before allocation"
    )
    parser.add_argument("--gpu-cap", type=int, choices=range(1, 5), default=1)
    parser.add_argument(
        "--lifecycle",
        action="store_true",
        help="TSK-15: pause after one committed case, resume, then cancel and archive",
    )
    parser.add_argument("--backend", choices=("local", "server"), default="server")
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
