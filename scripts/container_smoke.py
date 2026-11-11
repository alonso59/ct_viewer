#!/usr/bin/env python3
"""Container smoke under Docker, plus the image gates.

Image size <= 1.5 GB · IBSI phantom smoke in the image · empty ALLOWED_DATA_ROOTS refuses to start ·
runs as an arbitrary UID · health, SPA, import + one item viewable · Docker HEALTHCHECK ·
source files unchanged (R1). Standard library only; talks to Docker through its CLI.

    make fixtures && make image && python3 scripts/container_smoke.py

Env: IMAGE (default radiology-workbench:<backend/pyproject.toml version>), DATA_ROOT (default the
synthetic fixtures; a custom root skips the mask label checks), SMOKE_PORT (default 8099),
SMOKE_UID (default 12345).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API = "/api/v1"


def call(
    base: str,
    path: str,
    body: Any = None,
    headers: dict[str, str] | None = None,
    method: str | None = None,
) -> Any:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers=dict(headers or {}), method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as res:
        raw = res.read()
        ctype = res.headers.get("Content-Type", "")
        return (res.status, raw) if not ctype.startswith("application/json") else json.loads(raw)


def wait_health(base: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        try:
            body: dict[str, Any] = call(base, f"{API}/health")
            return body
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if time.monotonic() > deadline:
                raise SystemExit(f"FAIL health: {e}") from e
            time.sleep(1)


def check(ok: bool, what: str) -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        raise SystemExit(1)


def run(base: str, root: str, timeout: float, segmentations: bool = False) -> None:
    health = wait_health(base, timeout)
    check(health.get("status") == "ok", f"health {health.get('version')}")

    status, html = call(base, "/")
    check(status == 200 and b'<div id="root"' in html, "SPA index at /")
    status, html = call(base, "/p/does-not-exist/case/x")
    check(status == 200 and b'<div id="root"' in html, "SPA fallback for client routes")
    try:
        call(base, f"{API}/no-such-endpoint")
        check(False, "unknown API path is 404")
    except urllib.error.HTTPError as e:
        check(e.code == 404, "unknown API path is 404, not the SPA")

    pid = call(base, f"{API}/projects", {"name": "container-smoke"})["project_id"]
    preview = call(base, f"{API}/projects/{pid}/imports/preview", {"root": root, "detect": True})
    started = call(base, f"{API}/projects/{pid}/imports", {"preview_id": preview["preview_id"]})
    job = call(base, f"{API}/jobs/{started['job_id']}")
    deadline = time.monotonic() + timeout
    while job["status"] not in ("succeeded", "failed", "cancelled", "interrupted"):
        if time.monotonic() > deadline:
            raise SystemExit("FAIL index job timed out")
        time.sleep(0.5)
        job = call(base, f"{API}/jobs/{job['job_id']}")
    check(job["status"] == "succeeded", f"import + index job ({job['total']} units in workers)")

    cases = call(base, f"{API}/projects/{pid}/cases?limit=2000")["items"]
    iid = next((c["thumb_item_id"] for c in cases if c.get("thumb_item_id")), None)
    check(bool(cases) and iid is not None, f"{len(cases)} cases indexed, one item picked")
    url = f"{API}/projects/{pid}/items/{iid}/image"
    status, head = call(base, url, headers={"Range": "bytes=0-347"})
    # NIfTI-1 header: sizeof_hdr = 348 (possibly gzip-wrapped: 1f 8b).
    nifti = head[:2] == b"\x1f\x8b" or int.from_bytes(head[:4], "little") == 348
    viewable = status == 206 and nifti
    check(viewable, f"item {iid} image bytes (Range 206)")

    if not segmentations:
        return
    project = call(base, f"{API}/projects/{pid}")
    item = call(base, f"{API}/projects/{pid}/items/{iid}")
    check(bool(item["labels_present"]), "synthetic smoke item has segmentation labels")
    label = item["labels_present"][0]
    seg = project["default_seg"]
    mask_url = f"{API}/projects/{pid}/items/{iid}/mask?seg={seg}"
    label_url = f"{API}/projects/{pid}/segmentations/{seg}/labels/{label}"
    _, original = call(base, mask_url)
    call(base, label_url, method="DELETE")
    _, filtered = call(base, mask_url)
    check(filtered != original, "individual label removal filters mask output")
    current = call(base, f"{API}/projects/{pid}/segmentations")
    check(next(s for s in current if s["seg_id"] == seg)["removed_labels"] == [label], "label exclusion persists")
    check(call(base, f"{API}/projects/{pid}")["label_map"] == project["label_map"], "label catalog preserved")
    call(base, f"{label_url}/restore", method="POST")
    _, restored = call(base, mask_url)
    check(restored == original, "label restore returns original mask bytes")


MAX_IMAGE_BYTES = 1_500_000_000


def docker(*args: str, check_exit: bool = True) -> str:
    done = subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    if check_exit and done.returncode:
        raise SystemExit(f"FAIL docker {args[0]}: {done.stderr.strip()}")
    return done.stdout.strip()


def main() -> None:
    repo = Path(__file__).resolve().parent.parent
    version = re.search(r'^version = "(.*)"', (repo / "backend/pyproject.toml").read_text(), re.MULTILINE)
    image = os.environ.get("IMAGE") or f"radiology-workbench:{version.group(1) if version else 'dev'}"
    root = Path(os.environ.get("DATA_ROOT") or repo / ".fixtures/synthetic/Dataset900")
    if not root.is_dir():
        raise SystemExit(f"missing data root {root} (run: make fixtures)")
    root = root.resolve()
    port = os.environ.get("SMOKE_PORT", "8099")
    uid = os.environ.get("SMOKE_UID", "12345")
    name = f"rw-smoke-{os.getpid()}"
    # Named volumes seeded with `docker cp`, not bind mounts: works on any Docker host (remote
    # contexts, VMs without host shares). The data path inside the container is /data/<root name>.
    croot = f"/data/{root.name}"
    try:
        # Uncompressed root filesystem (`docker image inspect .Size` is the compressed content
        # size under the containerd image store).
        size = int(docker("run", "--rm", image, "du", "-sxb", "/").split()[0])
        check(size <= MAX_IMAGE_BYTES, f"image size {size // 1_000_000} MB uncompressed <= 1500 MB")
        docker("run", "--rm", image, "python", "-m", "tools.spikes.ibsi_phantom_smoke")
        check(True, "IBSI phantom smoke in the image")

        docker("run", "-d", "--name", f"{name}-empty", "-e", "ALLOWED_DATA_ROOTS=", image)
        for _ in range(60):
            if docker("inspect", "-f", "{{.State.Running}}", f"{name}-empty") == "false":
                break
            time.sleep(0.5)
        code = docker("inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", f"{name}-empty")
        check(code.startswith("false ") and code != "false 0", f"empty ALLOWED_DATA_ROOTS refuses to start ({code})")
        logs = subprocess.run(["docker", "logs", f"{name}-empty"], capture_output=True, text=True, check=False)
        check("ALLOWED_DATA_ROOTS" in logs.stdout + logs.stderr, "refusal names ALLOWED_DATA_ROOTS")

        docker("create", "--name", f"{name}-seed", "-v", f"{name}-data:/data", image)
        docker("cp", "-q", str(root), f"{name}-seed:{croot}")
        docker("run", "--rm", "-u", "0", "-v", f"{name}-ws:/workspace", image, "chown", f"{uid}:{uid}", "/workspace")

        def hashes() -> str:
            listing = "cd /data && find . -type f -print0 | sort -z | xargs -0 sha256sum"
            return docker("run", "--rm", "-v", f"{name}-data:/data:ro", image, "sh", "-c", listing)

        before = hashes()
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--user",
            f"{uid}:{uid}",
            "-p",
            f"127.0.0.1:{port}:8000",
            "-v",
            f"{name}-ws:/workspace",
            "-v",
            f"{name}-data:/data:ro",
            "-e",
            f"ALLOWED_DATA_ROOTS={croot}",
            image,
        )
        check(True, f"started as arbitrary uid {uid}")
        try:
            run(f"http://127.0.0.1:{port}", croot, 120, segmentations=not os.environ.get("DATA_ROOT"))
        except SystemExit:
            print(docker("logs", "--tail", "40", name, check_exit=False))
            raise

        health = "starting"
        for _ in range(90):
            health = docker("inspect", "-f", "{{.State.Health.Status}}", name)
            if health != "starting":
                break
            time.sleep(1)
        check(health == "healthy", f"Docker HEALTHCHECK {health}")
        check(hashes() == before, f"{len(before.splitlines())} source files unchanged (R1)")
        print(f"container smoke pass: {image}")
    finally:
        subprocess.run(["docker", "rm", "-f", name, f"{name}-empty", f"{name}-seed"], capture_output=True, check=False)
        subprocess.run(["docker", "volume", "rm", "-f", f"{name}-ws", f"{name}-data"], capture_output=True, check=False)


if __name__ == "__main__":
    main()
