"""P1 exit check: import a dataset root through the real API and report QC warnings.

Uses worker processes (not inline), a throwaway workspace unless `--workspace` is given, and
`ALLOWED_DATA_ROOTS` = the dataset root. With `--sha256` it hashes every file under the root
before and after (TST-07, R1). With `--expected` (a fixture `expected.json`) it asserts that
every listed defect is reported. Exit code 0 = pass.

    cd backend && .venv/bin/python -m tools.import_check --root /data/Dataset820 --sha256
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

API = "/api/v1"


def sha_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    h.update(block)
            out[p.relative_to(root).as_posix()] = h.hexdigest()
    return out


def wait_job(c: TestClient, job_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = -1
    while time.monotonic() < deadline:
        job: dict[str, Any] = c.get(f"{API}/jobs/{job_id}").json()
        if job["done"] != last:
            last = job["done"]
            print(f"  {job['kind']}: {job['done']}/{job['total']}", file=sys.stderr)
        if job["status"] in ("succeeded", "failed", "cancelled", "interrupted"):
            return job
        time.sleep(0.5)
    raise SystemExit(f"job {job_id} timed out after {timeout}s")


def pages(c: TestClient, url: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = ""
    while True:
        sep = "&" if "?" in url else "?"
        page = c.get(f"{url}{sep}limit=2000&cursor={cursor}").json()
        out += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            return out


def run(args: argparse.Namespace) -> int:
    root: Path = args.root.resolve()
    workspace = args.workspace or Path(tempfile.mkdtemp(prefix="rw-import-check-"))
    before = sha_tree(root) if args.sha256 else None
    settings = Settings(
        workspace_root=workspace,
        allowed_data_roots=str(root),
        job_workers=args.workers,
        _env_file=None,  # type: ignore[call-arg]
    )
    ok = True
    t0 = time.monotonic()
    with TestClient(create_app(settings)) as c:
        pid = c.post(f"{API}/projects", json={"name": args.name or root.name}).json()["project_id"]
        body = {"root": str(root), "detect": True}
        r = c.post(f"{API}/projects/{pid}/imports/preview", json=body)
        r.raise_for_status()
        preview = r.json()
        print(json.dumps({"preview_counts": preview["counts"], "n_errors": preview["n_errors"]}))
        for e in preview["errors"][:10]:
            print(f"  preview error: {e}", file=sys.stderr)
        r = c.post(f"{API}/projects/{pid}/imports", json={"preview_id": preview["preview_id"]})
        r.raise_for_status()
        job = wait_job(c, r.json()["job_id"], args.timeout)
        ok &= job["status"] == "succeeded"
        warnings = pages(c, f"{API}/projects/{pid}/warnings")
        cases = pages(c, f"{API}/projects/{pid}/cases")
        by_code = Counter(w["code"] for w in warnings)
        summary: dict[str, Any] = {
            "project_id": pid,
            "workspace": str(workspace),
            "index_job": job["status"],
            "index_seconds": round(time.monotonic() - t0, 1),
            "cases": len(cases),
            "warnings": dict(sorted(by_code.items())),
        }
        if args.expected:
            expected = json.loads(args.expected.read_text())
            got = {(w["case_id"], w["code"]) for w in warnings}
            missing = [
                d
                for d in expected["defects"]
                if d["code"] != "fingerprint_changed" and (d["case_id"], d["code"]) not in got
            ]
            summary["expected_missing"] = missing
            ok &= not missing
    if before is not None:
        changed = sorted(k for k, v in sha_tree(root).items() if before.get(k) != v)
        summary["sources_hashed"] = len(before)
        summary["sources_changed"] = changed
        ok &= not changed and len(before) == len(sha_tree(root))
    summary["pass"] = ok
    print(json.dumps(summary, indent=2))
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--root", type=Path, required=True, help="dataset root (becomes alias DATA)")
    ap.add_argument("--workspace", type=Path, help="workspace dir (default: new temp dir)")
    ap.add_argument("--name", help="project name (default: root folder name)")
    ap.add_argument("--expected", type=Path, help="fixture expected.json to assert against")
    ap.add_argument("--sha256", action="store_true", help="hash all source files before/after")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=3600)
    raise SystemExit(run(ap.parse_args()))


if __name__ == "__main__":
    main()
