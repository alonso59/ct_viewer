"""Python API of `rw-dicom`: convert a DICOM source into a dataset ct_viewer imports directly.

    from rw_dicom import api
    summary = api.convert("/data/dicom", "/data/out", settings={"anonymize": "basic"}, workers=4)

An output folder is one dataset (ct_viewer's workspace-dataset layout, DCM-14/28). Running the
same conversion again resumes it: verified series are kept, the rest is converted. Private run
state (inventory with cached headers, pins, journal, outcomes) lives in `.rw-runs/` (0700); the
inventory can live elsewhere (`state_dir`).
`convert_batches` splits a source's patient folders into one dataset per batch.
"""

from __future__ import annotations

import contextlib
import fcntl
import fnmatch
import hashlib
import json
import os
import tempfile
import uuid
from collections.abc import Callable
from contextlib import ExitStack, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rw_dicom import commits, dataset, pipeline, scan
from rw_dicom import files as source_files
from rw_dicom.analyzers import checkpoint
from rw_dicom.durable import sync_dir, utc_now, write_json_atomic
from rw_dicom.identity import Identity
from rw_dicom.inventory import SourceInventory
from rw_dicom.settings import conversion_settings

LOCK, JOURNAL, REGISTRY, RUNS, BATCHES = (
    ".rw-cli.lock",
    ".rw_active.json",
    ".rw_identity.json",
    ".rw-runs",
    ".rw-batches.json",
)
CONTROL = {LOCK, JOURNAL, REGISTRY, RUNS, BATCHES}
MIB = 1024**2
Stage = Callable[[str, int, int], None]


def default_workers() -> int:
    """Available CPUs, at most 8: the P7i benchmarks gained little beyond (DICOM_STANDALONE_TEST_PLAN)."""
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
    return max(1, min(cpus, 8))


def default_memory_mb() -> int:
    """Half of this SLURM allocation or of physical memory: the budget all workers share."""
    per_node = os.environ.get("SLURM_MEM_PER_NODE", "")
    per_cpu, cpus = os.environ.get("SLURM_MEM_PER_CPU", ""), os.environ.get("SLURM_CPUS_ON_NODE", "")
    if per_node.isdigit() and int(per_node) > 0:  # 0 asks for all the node's memory
        return max(1, int(per_node) // 2)
    if per_cpu.isdigit() and cpus.isdigit() and int(per_cpu) * int(cpus) > 0:
        return max(1, int(per_cpu) * int(cpus) // 2)
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 / MIB)
    except (ValueError, OSError):
        return 8192


def versions() -> dict[str, str]:
    from importlib import metadata

    out = {"dicom.convert": pipeline.VERSION}
    for pkg in ("rw-dicom", "pydicom", "SimpleITK", "isal"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = ""
    return out


def _read(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("CLI state must be a JSON object")  # noqa: TRY004
    return raw


def _write(path: Path, record: dict[str, Any]) -> None:
    write_json_atomic(path, record)


def _output(out: Path, name: str) -> Path:
    relative = Path(name)
    first = relative.parts[0] if relative.parts else ""
    path = (out / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(out) or first in CONTROL:
        raise ValueError("CLI output paths must remain inside the output root and avoid its control files")
    return path


def _private(directory: Path) -> None:
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError("CLI run state must be private (0700) and cannot be a symlink")


def _outcomes(path: Path, attempt: int) -> tuple[dict[str, str], int]:
    latest: dict[str, str] = {}
    end = previous_attempt = 0
    if not path.exists():
        return latest, end
    with path.open("rb") as fh:
        for raw in fh:
            if not raw.endswith(b"\n"):
                break
            try:
                event = json.loads(raw)
                iid, status, epoch = event["item_id"], event["status"], event["attempt"]
                if (
                    not isinstance(iid, str)
                    or not iid
                    or status not in {"ok", "failed", "skipped"}
                    or type(epoch) is not int
                    or not previous_attempt <= epoch <= attempt
                    or epoch < 1
                ):
                    raise ValueError("Invalid outcome")
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("CLI outcome history is damaged; preserve it before recovering this run") from exc
            latest[iid], previous_attempt = status, epoch
            end += len(raw)
    return latest, end


def _phase(state: Path, result: pipeline.Result, stop: Callable[[], bool]) -> dict[str, Any]:
    """The phase layer with an open vocabulary, as a workspace dataset gets it (DCM-14)."""
    try:
        analysis = checkpoint.analyze_phase(state, result.analyzer_rows, {"phase_vocabulary": []}, cancelled=stop)
    except Exception as exc:  # noqa: BLE001 - optional analysis cannot fail committed conversion
        analysis = {
            "task": "analyzer.phase",
            "status": "failed",
            "total": len(result.analyzer_rows),
            "error": str(exc) if isinstance(exc, checkpoint.AnalysisConflict) else f"{type(exc).__name__}: retry",
        }
    return analysis


def convert(
    source: str | Path,
    output: str | Path,
    *,
    settings: dict[str, Any] | None = None,
    workers: int | None = None,
    memory_mb: int | None = None,
    max_failures: int | None = None,
    allow_mixed_versions: bool = False,
    mode: str = "convert",
    nifti_dir: str = "nifti",
    metadata_file: str = "metadata.jsonl",
    inventory_mb: int = 16384,
    state_dir: str | Path | None = None,
    stop: Callable[[], bool] = lambda: False,
    on_stage: Stage | None = None,
) -> dict[str, Any]:
    """Convert (`mode`: convert | retry_failed) or plan (dry_run) one dataset; see the module doc.

    `workers` None: `default_workers()`; with more than one, `memory_mb` None is half the RAM.
    `state_dir` keeps the inventory on a local disk, since SQLite's WAL does not work over network
    file systems. Losing it costs a new header scan: pins and commits stay in the output."""
    workers = default_workers() if workers is None else workers
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if workers > 1 and memory_mb is None:
        memory_mb = default_memory_mb()
    source, out = Path(source).resolve(), Path(output).resolve()
    if not source.exists():
        raise ValueError("DICOM source is unavailable")
    if source.is_relative_to(out) or out.is_relative_to(source):
        raise ValueError("DICOM source and output roots must not overlap")
    state_root = None if state_dir is None else Path(state_dir).resolve()
    if state_root is not None and state_root.is_relative_to(source):
        raise ValueError("The state folder must be outside the DICOM source")
    if mode not in {"convert", "dry_run", "retry_failed"}:
        raise ValueError("mode must be convert, dry_run or retry_failed")
    normalized, _ = conversion_settings(settings or {})
    conv = pipeline.Settings.from_dict(normalized)
    image_dir = _output(out, nifti_dir)
    meta_path = _output(out, metadata_file)
    if meta_path == out or meta_path.is_dir():
        raise ValueError("CLI metadata output must name a file inside the output root")
    sidecar_dir = _output(out, "sidecars")
    dry = mode == "dry_run"
    failed_only = mode == "retry_failed"
    record_path = out / JOURNAL
    if failed_only and not record_path.is_file():
        raise ValueError("Retry failed requires an unfinished CLI run with recorded failures")
    with ExitStack() as stack:
        if not dry:
            out.mkdir(parents=True, exist_ok=True)
            fd = os.open(out / LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            stack.callback(os.close, fd)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        registry_path = out / REGISTRY
        identity = Identity.from_dict(_read(registry_path) if registry_path.is_file() else None)
        previous = (
            [json.loads(x) for x in meta_path.read_text().splitlines() if x.strip()] if meta_path.is_file() else []
        )
        checkpoint_path = None
        record: dict[str, Any] = {}
        retry_item_ids = None
        outcomes_file = None
        if not dry:
            request = {
                "source": str(source),
                "settings": asdict(conv),
                "metadata": str(meta_path.relative_to(out)),
                "nifti": nifti_dir,
            }
            if record_path.exists():
                record = _read(record_path)
                if record.get("version") != 1 or record.get("status") not in {
                    "running",
                    "failed",
                    "interrupted",
                    "completed",
                }:
                    raise ValueError("CLI journal is damaged or incompatible; preserve it and use a new output root")
                if record["status"] != "completed" and record.get("request") != request:
                    raise ValueError(
                        "Resume conflict: CLI source/settings/output changed; restore them or use a new output root"
                    )
            if not record or record["status"] == "completed":
                if failed_only:
                    raise ValueError("Retry failed requires an unfinished CLI run; completed runs remain sealed")
                record = {
                    "version": 1,
                    "run_id": uuid.uuid4().hex,
                    "attempts": 0,
                    "request": request,
                    "created_at": utc_now(),
                    "plan_pinned": False,
                }
            rid = record.get("run_id")
            if not isinstance(rid, str) or len(rid) != 32 or any(c not in "0123456789abcdef" for c in rid):
                raise ValueError("CLI run identity is invalid; preserve its journal")
            run_dirs = out / RUNS
            _private(run_dirs)
            checkpoint_path = run_dirs / rid / "pin.json"
            outcomes_path = checkpoint_path.parent / "outcomes.jsonl"
            if failed_only and (record.get("outcomes_version") != 1 or not outcomes_path.is_file()):
                raise ValueError("Recorded CLI outcomes are unavailable; Resume pending before failure-only retry")
            outcomes, valid_end = _outcomes(outcomes_path, int(record["attempts"]))
            if failed_only:
                retry_item_ids = sorted(iid for iid, status in outcomes.items() if status == "failed")
                if not retry_item_ids:
                    raise ValueError("No recorded failed series remain; Resume pending for unattempted series")
            if record.get("plan_pinned") and not checkpoint_path.is_file():
                raise ValueError(
                    "Resume conflict: pinned CLI plan is missing; preserve the outputs and recover its journal"
                )
            if record.get("plan_pinned") and commits.file_digest(checkpoint_path)["sha256"] != record.get("pin_sha256"):
                raise ValueError("Resume conflict: pinned CLI plan changed; preserve its journal and outputs")
            _private(checkpoint_path.parent)
            ledger_fd = os.open(outcomes_path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            outcomes_file = stack.enter_context(os.fdopen(ledger_fd, "a", encoding="utf-8"))
            if os.fstat(ledger_fd).st_size != valid_end:
                # Keep the unacknowledged fragment before repairing the append boundary.
                with outcomes_path.open("rb") as fh:
                    fh.seek(valid_end)
                    _write(checkpoint_path.parent / f"torn-{uuid.uuid4().hex}.json", {"fragment": fh.read().hex()})
                os.ftruncate(ledger_fd, valid_end)
            os.fsync(ledger_fd)
            for directory in (checkpoint_path.parent, run_dirs):
                sync_dir(directory)
            record.update(
                status="running",
                attempts=int(record["attempts"]) + 1,
                attempt_id=uuid.uuid4().hex,
                updated_at=utc_now(),
                outcomes_version=1,
            )
            _write(record_path, record)
            inventory_dir = run_dirs
            if state_root is not None:  # one inventory per output, also for batches sharing the folder
                state_root.mkdir(parents=True, exist_ok=True)
                inventory_dir = state_root / hashlib.sha256(str(out).encode()).hexdigest()[:16]
                _private(inventory_dir)
            inventory_path = inventory_dir / "inventory.sqlite"
        else:
            inventory_path = (
                Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="rw-dicom-plan-"))) / "inventory.sqlite"
            )

        def stage(name: str, done: int, total: int) -> None:
            if not dry and name == "converting" and not record.get("plan_pinned"):
                assert checkpoint_path is not None
                record.update(plan_pinned=True, pin_sha256=commits.file_digest(checkpoint_path)["sha256"])
                _write(record_path, record)
            if on_stage is not None:
                on_stage(name, done, total)

        def progress(iid: str, status: str, _outputs: list[dict[str, Any]], _message: str) -> None:
            assert outcomes_file is not None
            outcomes_file.write(json.dumps({"item_id": iid, "status": status, "attempt": record["attempts"]}) + "\n")
            outcomes_file.flush()
            os.fsync(outcomes_file.fileno())

        try:
            with SourceInventory(inventory_path, source, conv.patient_folders) as inventory:
                # Every run walks again: unchanged files keep their cached headers (stat only), so
                # added, removed or edited series are seen without reading every header again.
                inventory.precount(cancelled=stop)
                found = inventory.scan(
                    cancelled=stop,
                    max_bytes=inventory_mb * MIB,
                    processes=workers,
                    on_progress=None
                    if on_stage is None
                    else lambda c: on_stage("reading", int(c.get("files", 0)), int(c.get("files_total") or 0)),
                )
                if not found["complete"]:
                    if stop():
                        raise _Stopped
                    raise ValueError(
                        "Discovery is incomplete: the inventory budget was reached; raise --inventory-mb and run again"
                        if found.get("limited")
                        else f"Discovery is incomplete: {found.get('errors', 0)} unreadable entries; repair them and run again"
                    )
                result = pipeline.run(
                    source,
                    conv,
                    identity,
                    nifti_dir=image_dir,
                    sidecar_dir=sidecar_dir,
                    ref_rel="",
                    ref_alias="DATA",
                    salt="",
                    previous=previous,
                    dry_run=dry,
                    checkpoint=checkpoint_path,
                    on_stage=stage,
                    progress=None if dry else progress,
                    cancelled=stop,
                    inventory=inventory,
                    cached_file_total=int(found["dicom"]),
                    retry_item_ids=retry_item_ids,
                    workers=workers,
                    memory_mb=memory_mb if workers > 1 else None,
                    allow_mixed_versions=allow_mixed_versions,
                    max_failures=max_failures,
                )
            if dry:
                return {
                    "status": "planned",
                    "complete": False,
                    "counts": result.counts,
                    "storage": result.storage,
                    "plan": result.plan,
                }
            dataset.relative_rows(result.rows, nifti_dir)
            successful = dataset.is_complete(result, stop()) and result.counts["series"] > 0
            annotations = result.annotations
            analysis = None
            if successful and normalized.get("phase_analyzer", True) and result.analyzer_rows:
                assert checkpoint_path is not None
                analysis = _phase(checkpoint_path.parent / "phase-analyzer", result, stop)
                phase_rows = analysis.pop("annotations", [])
                if analysis["status"] == "completed":
                    annotations = [*annotations, *phase_rows]
            manifest = dataset.manifest(
                name=out.name, run_id=str(rid), phase_run_id=None, source=source, settings=normalized, result=result
            )
            dataset.write(
                out,
                rows=result.rows,
                diagnostics=[d.as_dict() for d in result.diagnostics],
                summary={
                    "counts": result.counts,
                    "storage": result.storage,
                    "versions": versions(),
                    "analysis": analysis,
                    "units_by_versions": result.units_by_versions,
                },
                annotations=annotations,
                dataset=manifest,
                complete=successful,
                metadata_name=str(meta_path.relative_to(out)),
            )
            _write(registry_path, identity.as_dict())
            status = "completed" if successful else "interrupted" if result.counts["pending"] or stop() else "failed"
            record.update(status=status, counts=result.counts, updated_at=utc_now())
            _write(record_path, record)
        except _Stopped:
            record.update(status="interrupted", updated_at=utc_now())
            _write(record_path, record)
            return {"status": "interrupted", "complete": False, "counts": {}, "storage": {}}
        except BaseException:
            if not dry:
                record.update(status="interrupted", updated_at=utc_now())
                with suppress(OSError):
                    _write(record_path, record)
            raise
    return {"status": status, "complete": successful, "counts": result.counts, "storage": result.storage}


class _Stopped(Exception):
    pass


def _patient_folders(source: Path, pattern: str) -> list[str]:
    return sorted(
        (
            p.name
            for p in source.iterdir()
            if p.is_dir()
            and not p.is_symlink()
            and not source_files.excluded(p.name)
            and fnmatch.fnmatch(p.name, pattern)
        ),
        key=str.lower,
    )


def convert_batches(
    source: str | Path,
    output: str | Path,
    *,
    batch_size: int,
    settings: dict[str, Any] | None = None,
    stop: Callable[[], bool] = lambda: False,
    **options: Any,
) -> dict[str, Any]:
    """One dataset per `batch_size` top-level patient folders, `OUTPUT/b01` … (cf. ADR-0040).

    The partition is frozen on the first run (folder names stay in a private 0600 file); a run
    again resumes every unfinished batch and skips complete ones. Folders added later are counted,
    never moved into a frozen batch.
    """
    source, out = Path(source).resolve(), Path(output).resolve()
    if batch_size < 1:
        raise ValueError("batch size must be at least 1")
    if not source.is_dir() or scan.has_dicom_files(source):
        raise ValueError("Batches need a source folder of patient folders")
    raw = dict(settings or {})
    if raw.get("patient_folders") is not None:
        raise ValueError("Batches choose the patient folders; remove patient_folders")
    out.mkdir(parents=True, exist_ok=True)
    plan_path = out / BATCHES
    with ExitStack() as stack:
        fd = os.open(out / LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        stack.callback(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        folders = _patient_folders(source, str(raw.get("patient_pattern") or "*"))
        if plan_path.exists():
            plan = _read(plan_path)
            if plan.get("source") != str(source) or plan.get("batch_size") != batch_size:
                raise ValueError("This output holds batches of another source or batch size; use a new output")
        else:
            limit = raw.get("patient_limit")
            chosen = folders[:limit] if limit else folders
            plan = {
                "version": 1,
                "source": str(source),
                "batch_size": batch_size,
                "batches": [chosen[i : i + batch_size] for i in range(0, len(chosen), batch_size)],
            }
            fdp = os.open(plan_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            os.close(fdp)
            _write(plan_path, plan)
        planned = {name for batch in plan["batches"] for name in batch}
        width = max(2, len(str(len(plan["batches"]))))
        report = []
        for index, names in enumerate(plan["batches"], 1):
            target = out / f"b{index:0{width}d}"
            if (target / dataset.DATASET_JSON).is_file():
                report.append({"batch": target.name, "status": "completed"})
                continue
            if stop():
                report.append({"batch": target.name, "status": "pending"})
                continue
            batch_settings = {k: v for k, v in raw.items() if k not in {"patient_pattern", "patient_limit"}}
            try:
                summary = convert(
                    source, target, settings={**batch_settings, "patient_folders": names}, stop=stop, **options
                )
            except (OSError, ValueError, commits.CommitConflict) as exc:
                summary = {
                    "status": "failed",
                    "error": str(exc) if not isinstance(exc, OSError) else type(exc).__name__,
                }
            report.append(
                {"batch": target.name, **{k: summary[k] for k in ("status", "counts", "error") if k in summary}}
            )
        complete = all(item["status"] == "completed" for item in report)
    return {
        "status": "completed" if complete else "incomplete",
        "complete": complete,
        "batches": report,
        "new_folders": len(set(folders) - planned),
    }


def status(output: str | Path) -> dict[str, Any]:
    """Journal state and outcome counts of a dataset or a batch root, without names or paths."""
    out = Path(output).resolve()
    if (out / BATCHES).is_file():
        plan = _read(out / BATCHES)
        width = max(2, len(str(len(plan["batches"]))))
        return {
            "batches": [status(out / f"b{i:0{width}d}") for i in range(1, len(plan["batches"]) + 1)],
        }
    if not (out / JOURNAL).is_file():
        return {"status": "not_started", "complete": False}
    record = _read(out / JOURNAL)
    outcomes: dict[str, str] = {}
    with contextlib.suppress(ValueError, OSError):
        outcomes, _ = _outcomes(out / RUNS / str(record.get("run_id")) / "outcomes.jsonl", int(record["attempts"]))
    tally: dict[str, int] = {}
    for value in outcomes.values():
        tally[value] = tally.get(value, 0) + 1
    return {
        "status": record.get("status"),
        "complete": (out / dataset.DATASET_JSON).is_file(),
        "attempts": record.get("attempts"),
        "counts": record.get("counts"),
        "outcomes": tally,
    }
