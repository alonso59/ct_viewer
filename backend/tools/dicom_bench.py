"""P7i S1 baseline benchmarks of today's converter (DICOM_STANDALONE_TEST_PLAN B01-B07, C08/C09).

    python -m tools.dicom_bench generate DIR --patients N --series M --slices K [--matrix 16]
    python -m tools.dicom_bench run DIR WORK --out RESULT.json [--stages ...] [--cold]

Each stage runs in a fresh child process, so its peak RSS, CPU and I/O counters are its own.
Timers wrap converter functions inside that child only; no product code changes. `--cold` drops
the source files' cached pages with `posix_fadvise` (no root needed; directory caches stay warm).
Synthetic data only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import signal
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from importlib import metadata
from pathlib import Path
from typing import Any

STAGES = ("discovery", "plan", "convert-app", "cli", "resume")
REPO = Path(__file__).resolve().parents[2]


def _patient(args: tuple[Path, int, int, int, int]) -> int:
    from tools.dicom_fixtures import write_series

    root, index, series, slices, matrix = args
    pid = f"P{index:06d}"
    for s in range(series):
        write_series(
            root / pid / f"s{s:02d}",
            patient_id=pid,
            description=f"ABDOMEN SERIES {s}",
            series_number=s + 1,
            shape=(matrix, matrix, slices),
            marker=(1, 1, slices // 2),
            seed=f"bench-{pid}",
        )
    return series * slices


def generate(root: Path, patients: int, series: int, slices: int, matrix: int) -> int:
    """N patients x M series x K slices, seeded UIDs; keep K >= 10 so series stay selected."""
    jobs = [(root, i, series, slices, matrix) for i in range(patients)]
    with ProcessPoolExecutor(min(32, os.cpu_count() or 1)) as pool:
        return sum(pool.map(_patient, jobs, chunksize=8))


def drop_source_cache(root: Path) -> None:
    for folder, _, names in os.walk(root):
        for name in names:
            fd = os.open(os.path.join(folder, name), os.O_RDONLY)
            try:
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            finally:
                os.close(fd)


class Probe:
    """Wall-clock timers and counters around converter functions, inside one stage child."""

    def __init__(self, stop_after: int | None = None) -> None:
        self.stop_after = stop_after
        self.started = time.monotonic()
        self.seconds: dict[str, float] = defaultdict(float)
        self.calls: dict[str, int] = defaultdict(int)
        self.units: list[float] = []
        self.first: dict[str, float] = {}
        self.in_commit = False

    def wrap(self, owner: Any, name: str, label: Callable[[], str] | str) -> None:
        original = getattr(owner, name)

        def timed(*args: Any, **kwargs: Any) -> Any:
            key = label() if callable(label) else label
            t0 = time.monotonic()
            try:
                return original(*args, **kwargs)
            finally:
                self.seconds[key] += time.monotonic() - t0
                self.calls[key] += 1
                self.first.setdefault(key, t0 - self.started)

        setattr(owner, name, timed)

    def install(self) -> None:
        from rw_dicom import commits, convert, sidecar

        original_commit = commits.commit_series

        def commit(*args: Any, **kwargs: Any) -> Any:
            self.in_commit, t0 = True, time.monotonic()
            try:
                return original_commit(*args, **kwargs)
            finally:
                self.in_commit = False
                self.units.append(time.monotonic() - t0)
                self.first.setdefault("commit_done", time.monotonic() - self.started)
                if self.stop_after is not None and len(self.units) >= self.stop_after:
                    os.kill(os.getpid(), signal.SIGKILL)  # an abrupt stop mid-run

        commits.commit_series = commit
        self.wrap(commits, "input_manifest", lambda: "hash_unit" if self.in_commit else "hash_pin")
        self.wrap(convert, "write_nifti", "decode_write_compress")
        self.wrap(convert, "read_image", "decode")
        self.wrap(commits, "_image_digest", "validate_output")
        self.wrap(sidecar, "write_sidecar", "sidecar")
        self.wrap(os, "fsync", "fsync")

    def report(self) -> dict[str, Any]:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        io = {}
        for line in Path("/proc/self/io").read_text().splitlines():
            key, value = line.split(":")
            if key in {"rchar", "wchar", "read_bytes", "write_bytes"}:
                io[key] = int(value)
        units = sorted(self.units)
        return {
            "wall_s": time.monotonic() - self.started,
            "cpu_user_s": usage.ru_utime,
            "cpu_sys_s": usage.ru_stime,
            "peak_rss_mb": usage.ru_maxrss / 1024,
            "io": io,
            "seconds": dict(self.seconds),
            "calls": dict(self.calls),
            "first_s": self.first,
            "units": {
                "n": len(units),
                "p50_s": statistics.median(units) if units else None,
                "p90_s": units[int(0.9 * (len(units) - 1))] if units else None,
                "max_s": units[-1] if units else None,
            },
        }


def _inventory(source: Path, work: Path) -> Any:
    from app.tasks.source_inventory import SourceInventory

    return SourceInventory(work / "inventory.sqlite", source)


def stage(name: str, source: Path, work: Path) -> dict[str, Any]:
    """One stage in this process; `resume` expects a `cli` output interrupted by `interrupt`."""
    from rw_dicom import cli, pipeline
    from rw_dicom.identity import Identity

    stop_after = os.environ.get("BENCH_INTERRUPT_AFTER") if name == "interrupt" else None
    probe = Probe(int(stop_after) if stop_after else None)
    probe.install()
    extra: dict[str, Any] = {}
    max_bytes = 16384 * 1024**2  # the DICOM_INVENTORY_MB maximum, so the cap never truncates
    if name == "discovery":
        with _inventory(source, work) as inventory:
            inventory.precount(cancelled=lambda: False)
            extra["summary"] = inventory.scan(cancelled=lambda: False, max_bytes=max_bytes)
    elif name in {"plan", "convert-app"}:
        dry = name == "plan"
        out = work / "app"
        with _inventory(source, work) as inventory:
            summary = inventory.summary()
            result = pipeline.run(
                source,
                pipeline.Settings(),
                Identity(),
                nifti_dir=out / "nifti",
                sidecar_dir=out / "sidecars",
                ref_rel="",
                ref_alias="DATA",
                salt="",
                previous=[],
                dry_run=dry,
                inventory=inventory,
                cached_file_total=summary["dicom"],
                checkpoint=None if dry else out / "conversion-pin.json",
            )
        extra["counts"] = result.counts
    elif name in {"cli", "interrupt", "resume"}:
        workers = os.environ.get("BENCH_WORKERS", "1") if name == "cli" else "1"
        extra["workers"] = workers
        extra["exit_code"] = cli.main(
            ["convert", str(source), str(work / "cli"), "--workers", workers]
        )
    else:
        raise ValueError(name)
    return {**probe.report(), **extra}


def environment(source: Path, work: Path) -> dict[str, Any]:
    def mount(path: Path) -> str:
        best = ("", "")
        for line in Path("/proc/mounts").read_text().splitlines():
            _, point, kind, *_ = line.split()
            if str(path.resolve()).startswith(point) and len(point) > len(best[0]):
                best = (point, kind)
        return best[1]

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout

    lock = REPO / "backend" / "requirements-ci.lock"
    return {
        "revision": git("rev-parse", "HEAD").strip(),
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no").strip()),
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "versions": {p: metadata.version(p) for p in ("pydicom", "SimpleITK", "isal")},
        "cpus": len(os.sched_getaffinity(0)),
        "memory_gb": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3,
        "filesystem": {"source": mount(source), "work": mount(work)},
    }


def child(name: str, source: Path, work: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    out = work / f"{name}.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.dicom_bench",
            "stage",
            name,
            str(source),
            str(work),
            str(out),
        ],
        cwd=REPO / "backend",
        env={**os.environ, "PYTHONPATH": f"{REPO / 'backend'}{os.pathsep}{REPO}", **(env or {})},
        capture_output=True,
        text=True,
    )
    if name == "interrupt":
        return {"returncode": proc.returncode}
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(f"stage {name} failed ({proc.returncode}): {proc.stderr[-2000:]}")
    return dict(json.loads(out.read_text()))


def run(
    source: Path, work: Path, stages: list[str], cold: bool, workers: int = 1
) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    files = sum(len(names) for _, _, names in os.walk(source))
    result: dict[str, Any] = {
        "environment": environment(source, work),
        "dataset": {"files": files, "bytes": sum(p.stat().st_size for p in source.rglob("*.dcm"))},
        "cold": cold,
        "stages": {},
    }
    for name in stages:
        if cold:
            drop_source_cache(source)
        if name == "resume":
            planned = result["stages"].get("cli", {}).get("units", {}).get("n")
            if not planned:
                raise ValueError("resume needs a preceding cli stage")
            (work / "cli").rename(work / f"cli-complete-{time.time_ns()}")
            result["stages"]["interrupt"] = child(
                "interrupt", source, work, {"BENCH_INTERRUPT_AFTER": str(max(1, planned // 2))}
            )
            if cold:
                drop_source_cache(source)
        result["stages"][name] = child(name, source, work, {"BENCH_WORKERS": str(workers)})
        print(f"{name}: {result['stages'][name]['wall_s']:.1f} s", file=sys.stderr)
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dicom_bench")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("root", type=Path)
    for flag, default in (("patients", 1), ("series", 4), ("slices", 100), ("matrix", 16)):
        gen.add_argument(f"--{flag}", type=int, default=default)
    bench = sub.add_parser("run")
    bench.add_argument("source", type=Path)
    bench.add_argument("work", type=Path)
    bench.add_argument("--out", type=Path, required=True)
    bench.add_argument("--stages", default=",".join(STAGES))
    bench.add_argument("--cold", action="store_true")
    bench.add_argument(
        "--workers", type=int, default=1, help="CLI stage only; units run in workers"
    )
    one = sub.add_parser("stage")
    one.add_argument("name")
    for name in ("source", "work", "out"):
        one.add_argument(name, type=Path)
    args = parser.parse_args(argv)
    if args.command == "generate":
        n = generate(args.root, args.patients, args.series, args.slices, args.matrix)
        print(json.dumps({"files": n}))
    elif args.command == "run":
        result = run(args.source, args.work, args.stages.split(","), args.cold, args.workers)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, default=str) + "\n")
    else:
        args.out.write_text(json.dumps(stage(args.name, args.source, args.work), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
