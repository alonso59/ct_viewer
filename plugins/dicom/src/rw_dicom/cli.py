"""`rw-dicom`: convert a DICOM folder into a dataset ct_viewer imports directly (DCM-09, DCM-26).

    rw-dicom convert SOURCE OUTPUT [--workers auto|N] [--set anonymize=basic] [--config run.yaml]
    rw-dicom convert SOURCE OUTPUT --batch-size 40      # one dataset per 40 patient folders
    rw-dicom convert SOURCE OUTPUT --dry-run            # plan only: no output state, no pixels
    rw-dicom convert SOURCE OUTPUT --retry-failed       # only the recorded failures
    rw-dicom status OUTPUT
    rw-dicom LEGACY.yaml                                # the converter's original YAML keys

Run the same command again to resume. The first SIGINT, SIGTERM or SIGHUP stops dispatching and
lets running series finish (the run is resumable); a second one stops them at once. The process
does not outlive its terminal: use tmux, screen, nohup or `systemd-run --user` for long runs.
Exit code 0: complete; 1: incomplete, failed or refused. Messages never name files or patients.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Self

from rw_dicom import api
from rw_dicom.inventory import InventoryError

SETTING_KEYS = (
    "target_profile", "mixed_folder_policy", "patient_pattern", "patient_limit", "patient_folders",
    "anonymize", "sidecars", "phase_analyzer",
)  # fmt: skip
EXECUTION_KEYS = {"workers", "memory_mb", "max_failures", "allow_mixed_versions", "batch_size", "inventory_mb"}


def load(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        raw = json.loads(text)
    else:
        import yaml  # optional extra: rw-dicom[yaml]

        try:
            raw = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            raise ValueError("Invalid converter YAML; check its formatting") from None
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")  # noqa: TRY004 - invalid file content
    return raw


def legacy(cfg: dict[str, Any]) -> dict[str, Any]:
    """The original converter keys (`dataset_root`, `conversion`, `outputs`, `mode`) as a run."""
    conv = cfg.get("conversion") or {}
    outs = cfg.get("outputs") or {}
    settings = {k: cfg[k] for k in SETTING_KEYS if cfg.get(k) is not None}
    settings |= {
        k: conv[k]
        for k in ("convert_primary", "convert_secondary", "convert_excluded", "skip_unsafe_geometry")
        if k in conv
    }
    if "include_modality_prefix" in outs:
        settings["include_modality_prefix"] = outs["include_modality_prefix"]
    return {
        "source": cfg["dataset_root"],
        "output": cfg["output_root"],
        "settings": settings,
        "execution": {"workers": 1},  # the original converter ran serially; keep its behavior
        "mode": cfg.get("mode") or "convert",
        "nifti_dir": str(outs.get("nifti_dir") or "nifti"),
        "metadata_file": str(outs.get("metadata_file") or "metadata.jsonl"),
    }


def structured(cfg: dict[str, Any]) -> dict[str, Any]:
    unknown = set(cfg) - {"source", "output", "settings", "execution"}
    if unknown or not isinstance(cfg.get("settings", {}), dict) or not isinstance(cfg.get("execution", {}), dict):
        raise ValueError("A config holds only source, output, settings and execution")
    if set(cfg.get("execution") or {}) - EXECUTION_KEYS:
        raise ValueError("Unknown execution option; use " + ", ".join(sorted(EXECUTION_KEYS)))
    return {"settings": dict(cfg.get("settings") or {}), "execution": dict(cfg.get("execution") or {}), **cfg}


class Stop:
    """First signal: finish running series and stop; second: stop now. Terminal writes stop on SIGHUP."""

    def __init__(self) -> None:
        self.requested = False
        self.quiet = False
        self.previous: dict[int, Any] = {}

    def __enter__(self) -> Self:
        with contextlib.suppress(ValueError):  # not the main thread: the caller handles signals
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                self.previous[sig] = signal.signal(sig, self._handle)
        return self

    def __exit__(self, *_: object) -> None:
        for sig, handler in self.previous.items():
            signal.signal(sig, handler)

    def _handle(self, sig: int, _frame: Any) -> None:
        if sig == signal.SIGHUP:
            self.quiet = True
        if self.requested:
            raise KeyboardInterrupt
        self.requested = True

    def __call__(self) -> bool:
        return self.requested


class Progress:
    def __init__(self, stop: Stop) -> None:
        self.stop = stop
        self.last = 0.0
        self.tty = sys.stderr.isatty()

    def __call__(self, name: str, done: int, total: int) -> None:
        if not self.tty or self.stop.quiet or time.monotonic() - self.last < 0.5:
            return
        self.last = time.monotonic()
        try:
            sys.stderr.write(f"\r{name}: {done}/{total or '?'}   ")
            sys.stderr.flush()
        except OSError:
            self.stop.quiet = True


def _value(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rw-dicom", description="DICOM to NIfTI datasets for ct_viewer")
    p.add_argument("--version", action="store_true", help="print converter and reader versions")
    sub = p.add_subparsers(dest="command")
    c = sub.add_parser("convert", help="convert or resume a dataset")
    c.add_argument("source", nargs="?")
    c.add_argument("output", nargs="?")
    c.add_argument("--config", type=Path, help="YAML or JSON: source, output, settings, execution")
    c.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="a conversion setting")
    c.add_argument("--workers", help="parallel series: auto (default: CPUs, at most 8) or a number")
    c.add_argument("--memory-mb", type=int, help="total memory budget of all workers")
    c.add_argument("--max-failures", type=int, help="stop dispatching after this many failed series")
    c.add_argument("--batch-size", type=int, help="one dataset per this many patient folders")
    c.add_argument("--allow-mixed-versions", action="store_true", help="add series made by other readers")
    c.add_argument("--inventory-mb", type=int, help="inventory storage budget (default 16384)")
    mode = c.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="plan only")
    mode.add_argument("--retry-failed", action="store_true", help="only the recorded failures")
    s = sub.add_parser("status", help="state of a dataset or batch output")
    s.add_argument("output")
    return p


def _run(args: argparse.Namespace, stop: Stop) -> int:
    if args.command == "status":
        print(json.dumps(api.status(args.output), indent=2))
        return 0
    cfg: dict[str, Any] = {"settings": {}, "execution": {}}
    if args.config is not None:
        raw = load(args.config)
        cfg = legacy(raw) if "dataset_root" in raw else structured(raw)
    for item in args.set:
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError("--set needs KEY=VALUE")
        cfg["settings"][key] = _value(value)
    execution = dict(cfg.get("execution") or {})
    for name in ("memory_mb", "max_failures", "batch_size", "inventory_mb"):
        if getattr(args, name) is not None:
            execution[name] = getattr(args, name)
    if args.workers is not None:
        execution["workers"] = args.workers
    if args.allow_mixed_versions:
        execution["allow_mixed_versions"] = True
    source = args.source or cfg.get("source")
    output = args.output or cfg.get("output")
    if not source or not output:
        raise ValueError("Give SOURCE and OUTPUT, as arguments or in --config")
    mode = "dry_run" if args.dry_run else "retry_failed" if args.retry_failed else cfg.get("mode", "convert")
    return _convert(source, output, cfg, execution, mode, stop)


def _convert(source: str, output: str, cfg: dict[str, Any], execution: dict[str, Any], mode: str, stop: Stop) -> int:
    workers_raw = execution.get("workers", "auto")
    workers = api.default_workers() if workers_raw == "auto" else int(workers_raw)
    if workers < 1:
        raise ValueError("--workers must be auto or at least 1")
    options: dict[str, Any] = {
        "settings": cfg.get("settings") or {},
        "workers": workers,
        "memory_mb": execution.get("memory_mb") or (api.default_memory_mb() if workers > 1 else None),
        "max_failures": execution.get("max_failures"),
        "allow_mixed_versions": bool(execution.get("allow_mixed_versions")),
        "mode": mode,
        "nifti_dir": cfg.get("nifti_dir", "nifti"),
        "metadata_file": cfg.get("metadata_file", "metadata.jsonl"),
        "inventory_mb": int(execution.get("inventory_mb") or 16384),
        "stop": stop,
        "on_stage": Progress(stop),
    }
    if execution.get("batch_size"):
        if mode != "convert":
            raise ValueError("Batches convert; plan or retry one batch folder at a time")
        options.pop("mode")
        summary = api.convert_batches(source, output, batch_size=int(execution["batch_size"]), **options)
    else:
        summary = api.convert(source, output, **options)
    summary.pop("plan", None)
    if not stop.quiet:
        if sys.stderr.isatty():
            sys.stderr.write("\n")
        print(json.dumps(summary, indent=2))
    return 0 if summary["complete"] or summary["status"] == "planned" else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    with Stop() as stop:
        return _main(argv, stop)


def _main(argv: list[str], stop: Stop) -> int:
    try:
        if len(argv) == 1 and argv[0] not in {"convert", "status", "--version", "-h", "--help"}:
            # The original invocation: one YAML file with the converter's legacy keys.
            cfg = load(Path(argv[0]))
            run = legacy(cfg) if "dataset_root" in cfg else structured(cfg)
            if not run.get("source") or not run.get("output"):
                raise ValueError("The config needs source and output")
            return _convert(str(run["source"]), str(run["output"]), run, dict(run.get("execution") or {}),
                            str(run.get("mode") or "convert"), stop)  # fmt: skip
        args = parser().parse_args(argv)
        if args.version:
            print(json.dumps(api.versions(), indent=2))
            return 0
        if args.command is None:
            parser().print_help()
            return 1
        return _run(args, stop)
    except (OSError, ValueError, KeyError, TypeError, InventoryError) as exc:
        if isinstance(exc, OSError):
            message = os.strerror(exc.errno) if exc.errno else type(exc).__name__
        else:
            message = str(exc)
        print(f"Conversion refused: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
