#!/usr/bin/env python3
"""TST-10 container smoke, runtime-agnostic: health OK, SPA served, one item viewable.

Talks HTTP only (stdlib, runs with any host python3), so the same check covers Docker and udocker:
it creates a project, imports DATA_ROOT, waits for the index job and reads the first bytes of one
item's image. `scripts/container-smoke.sh` starts the Docker container and calls this.

    python3 scripts/container_smoke.py --url http://127.0.0.1:8000 --root /abs/data/root
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from typing import Any

API = "/api/v1"


def call(base: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers=dict(headers or {}))
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


def run(base: str, root: str, timeout: float) -> None:
    health = wait_health(base, timeout)
    check(health.get("status") == "ok", f"health {health.get('version')} (OPS-07)")

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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--root", required=True, help="data root as seen inside the container")
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args()
    run(args.url.rstrip("/"), args.root, args.timeout)
    print("TST-10 pass")


if __name__ == "__main__":
    main()
