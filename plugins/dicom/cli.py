"""Standalone converter CLI (DCM-09): the legacy YAML config and its own resume registry. It
writes the same clean `metadata.jsonl` as the app (DCM-13: no phase guesses, curation or
selection fields, no `curation.csv`); its output folder is imported into the app as a `source`
root (metadata-v1). An existing `curation.csv` from an older run is left untouched and can be
imported once as curation events (CUR-15).

    python -m plugins.dicom.cli config/converter.yaml
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import uuid
from contextlib import ExitStack, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any

from plugins.dicom import commits, pipeline
from plugins.dicom.identity import Identity
from plugins.protocol import utc_now, write_json_atomic


def load(path: Path) -> dict[str, Any]:
    import yaml  # the CLI keeps the legacy YAML format (PyYAML is a CLI-only dependency)

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        raise ValueError("Invalid converter YAML; check its formatting") from None
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")  # noqa: TRY004 - invalid file content
    return raw


def _read(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("CLI state must be a JSON object")  # noqa: TRY004
    return raw


def _write(path: Path, record: dict[str, Any]) -> None:
    write_json_atomic(path, record)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _output(out: Path, name: str) -> Path:
    relative = Path(name)
    first = relative.parts[0] if relative.parts else ""
    path = (out / relative).resolve()
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not path.is_relative_to(out)
        or first
        in {
            ".rw_identity.json",
            ".rw_active.json",
            ".rw-runs",
            ".rw-cli.lock",
        }
    ):
        raise ValueError("CLI output paths must remain inside the output root and avoid its control files")
    return path


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


def _run(cfg: dict[str, Any]) -> int:
    source = Path(cfg["dataset_root"]).resolve()
    out = Path(cfg["output_root"]).resolve()
    if not source.exists():
        raise ValueError("DICOM source is unavailable")
    if source.is_relative_to(out) or out.is_relative_to(source):
        raise ValueError("DICOM source and output roots must not overlap")
    conv = cfg.get("conversion") or {}
    outs = cfg.get("outputs") or {}
    settings = pipeline.Settings(
        target_profile=str(cfg.get("target_profile") or "generic"),
        convert_primary=bool(conv.get("convert_primary", True)),
        convert_secondary=bool(conv.get("convert_secondary", True)),
        convert_excluded=bool(conv.get("convert_excluded", False)),
        skip_unsafe_geometry=bool(conv.get("skip_unsafe_geometry", False)),
        mixed_folder_policy=str(cfg.get("mixed_folder_policy") or "split"),
        patient_pattern=str(cfg.get("patient_pattern") or "*"),
        patient_limit=cfg.get("patient_limit"),
        include_modality_prefix=bool(outs.get("include_modality_prefix", True)),
    )
    nifti = str(outs.get("nifti_dir") or "nifti")
    image_dir = _output(out, nifti)
    meta_path = _output(out, str(outs.get("metadata_file") or "metadata.jsonl"))
    if meta_path == out or meta_path.is_dir():
        raise ValueError("CLI metadata output must name a file inside the output root")
    sidecar_dir = _output(out, "sidecars")
    dry = cfg.get("mode") == "dry_run"
    failed_only = cfg.get("mode") == "retry_failed"
    record_path = out / ".rw_active.json"
    if failed_only and not record_path.is_file():
        raise ValueError("Retry failed requires an unfinished CLI run with recorded failures")
    with ExitStack() as stack:
        if not dry:
            out.mkdir(parents=True, exist_ok=True)
            fd = os.open(out / ".rw-cli.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            stack.callback(os.close, fd)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        registry_path = out / ".rw_identity.json"
        identity = Identity.from_dict(_read(registry_path) if registry_path.is_file() else None)
        previous = (
            [json.loads(x) for x in meta_path.read_text().splitlines() if x.strip()] if meta_path.is_file() else []
        )
        checkpoint = None
        record: dict[str, Any] = {}
        retry_item_ids = None
        outcomes_file = None
        if not dry:
            request = {
                "source": str(source),
                "settings": asdict(settings),
                "metadata": str(meta_path.relative_to(out)),
                "nifti": nifti,
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
            checkpoint = out / ".rw-runs" / rid / "pin.json"
            outcomes_path = checkpoint.parent / "outcomes.jsonl"
            if failed_only and (record.get("outcomes_version") != 1 or not outcomes_path.is_file()):
                raise ValueError("Recorded CLI outcomes are unavailable; Resume pending before failure-only retry")
            outcomes, valid_end = _outcomes(outcomes_path, int(record["attempts"]))
            if failed_only:
                retry_item_ids = sorted(iid for iid, status in outcomes.items() if status == "failed")
                if not retry_item_ids:
                    raise ValueError("No recorded failed series remain; Resume pending for unattempted series")
            if record.get("plan_pinned") and not checkpoint.is_file():
                raise ValueError(
                    "Resume conflict: pinned CLI plan is missing; preserve the outputs and recover its journal"
                )
            if record.get("plan_pinned") and commits.file_digest(checkpoint)["sha256"] != record.get("pin_sha256"):
                raise ValueError("Resume conflict: pinned CLI plan changed; preserve its journal and outputs")
            run_dirs = checkpoint.parent.parent
            run_dirs.mkdir(mode=0o700, exist_ok=True)
            if run_dirs.is_symlink() or run_dirs.stat().st_mode & 0o077:
                raise ValueError("CLI plan directory must be private (0700) and cannot be a symlink")
            checkpoint.parent.mkdir(mode=0o700, exist_ok=True)
            if checkpoint.parent.is_symlink() or checkpoint.parent.stat().st_mode & 0o077:
                raise ValueError("CLI run directory must be private (0700) and cannot be a symlink")
            ledger_fd = os.open(outcomes_path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            outcomes_file = stack.enter_context(os.fdopen(ledger_fd, "a", encoding="utf-8"))
            if os.fstat(ledger_fd).st_size != valid_end:
                # Keep the unacknowledged fragment before repairing the append boundary.
                with outcomes_path.open("rb") as fh:
                    fh.seek(valid_end)
                    _write(checkpoint.parent / f"torn-{uuid.uuid4().hex}.json", {"fragment": fh.read().hex()})
                os.ftruncate(ledger_fd, valid_end)
            os.fsync(ledger_fd)
            directory_fd = os.open(checkpoint.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            fd = os.open(checkpoint.parent.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            record.update(
                status="running",
                attempts=int(record["attempts"]) + 1,
                attempt_id=uuid.uuid4().hex,
                updated_at=utc_now(),
                outcomes_version=1,
            )
            _write(record_path, record)

        def stage(name: str, done: int, total: int) -> None:
            if not dry and name == "converting" and not record.get("plan_pinned"):
                assert checkpoint is not None
                record.update(plan_pinned=True, pin_sha256=commits.file_digest(checkpoint)["sha256"])
                _write(record_path, record)

        def progress(iid: str, status: str, _outputs: list[dict[str, Any]], _message: str) -> None:
            assert outcomes_file is not None
            outcomes_file.write(json.dumps({"item_id": iid, "status": status, "attempt": record["attempts"]}) + "\n")
            outcomes_file.flush()
            os.fsync(outcomes_file.fileno())

        try:
            result = pipeline.run(
                source,
                settings,
                identity,
                nifti_dir=image_dir,
                sidecar_dir=sidecar_dir,
                ref_rel="",
                ref_alias="DATA",
                salt="",
                previous=previous,
                dry_run=dry,
                checkpoint=checkpoint,
                on_stage=stage,
                progress=None if dry else progress,
                retry_item_ids=retry_item_ids,
            )
            for row in result.rows:
                row["relative_path"] = f"{nifti}/{row.get('filename', '')}"
                if row.get("dicom_sidecar"):
                    row["dicom_sidecar"] = f"sidecars/{row['filename']}.dicom.json"
            successful = (
                result.counts["failed"] == 0
                and result.counts["pending"] == 0
                and result.resource_wait is None
                and result.counts["series"] > 0
            )
            if not dry:
                pipeline.write_jsonl(meta_path, result.rows)
                _write(registry_path, identity.as_dict())
                record.update(
                    status="completed" if successful else "interrupted" if result.counts["pending"] else "failed",
                    counts=result.counts,
                    updated_at=utc_now(),
                )
                _write(record_path, record)
        except BaseException:
            if not dry:
                record.update(status="interrupted", updated_at=utc_now())
                with suppress(OSError):
                    _write(record_path, record)
            raise
    print(json.dumps({"counts": result.counts, "storage": result.storage}, indent=2))
    return 0 if successful else 1


def main(argv: list[str]) -> int:
    try:
        return _run(load(Path(argv[0] if argv else "config/converter.yaml")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, OSError):
            message = os.strerror(exc.errno) if exc.errno else type(exc).__name__
        else:
            message = str(exc)
        print(f"Conversion refused: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
