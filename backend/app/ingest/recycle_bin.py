"""The project's recycle bin: list, restore and permanently delete recycled scans."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.errors import JobConflict, NotFound, PreconditionFailed, ValidationProblem
from app.core.fsio import atomic_write_bytes, iter_jsonl, read_json
from app.core.ids import utc_now
from app.core.paths import is_within, realpath
from app.core.reviewer import require
from app.ingest.models import Item, QcWarning
from app.ingest.recycle import (
    JOURNAL,
    MANIFEST,
    RECYCLE,
    RESTORE,
    RecycleService,
    _jsonl,
    prune_rows,
)
from app.jobs.types import TERMINAL

INDEX_FILES = (
    "index/items.jsonl",
    "index/cases.jsonl",
    "index/qc_warnings.jsonl",
    "index/status.json",
)


class RecycleBinEntry(BaseModel):
    recycle_id: str
    at: str
    reviewer: str
    case_id: str | None
    scan_idx: str | None
    item_ids: list[str]
    n_files: int
    projects: list[str]
    # False when the bin folder is gone (moved or deleted by hand); only a delete is possible
    available: bool


class RestorePlan(BaseModel):
    recycle_id: str
    case_id: str
    scan_idx: str
    item_ids: list[str]
    n_files: int
    n_metadata_files: int
    projects: list[str]
    token: str


class RestoreRequest(BaseModel):
    confirmed: bool
    token: str = Field(min_length=1)


class RestoreResult(BaseModel):
    recycle_id: str
    item_ids: list[str]
    project_ids: list[str]


class DeleteRequest(BaseModel):
    confirmed: bool


def _key(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def _unprune(
    backup: list[dict[str, Any]], current: list[dict[str, Any]], ids: set[str], case: str, scan: str
) -> list[dict[str, Any]]:
    """Put the scan's rows back into the current rows, keeping every later change."""
    pairs = prune_rows(backup, ids, case, scan)
    trimmed: dict[str, list[dict[str, Any]]] = {}
    for row, kept in pairs:
        if kept is not None and kept is not row:
            trimmed.setdefault(_key(kept), []).append(row)
    out = []
    for row in current:
        originals = trimmed.get(_key(row))
        out.append(originals.pop(0) if originals else row)
    present = {_key(r) for r in out}
    return out + [row for row, kept in pairs if kept is None and _key(row) not in present]


class RecycleBinService(RecycleService):
    def _journal(self, pid: str) -> list[dict[str, Any]]:
        return list(iter_jsonl(self.workspace.project_dir(pid) / JOURNAL))

    def _entry(self, pid: str, rid: str) -> dict[str, Any]:
        entry = next((e for e in self._journal(pid) if e.get("recycle_id") == rid), None)
        if entry is None or entry.get("purged"):
            raise NotFound(f"Recycled scan {rid!r} not found")
        return entry

    def _bin(self, pid: str, rid: str) -> Path | None:
        """The bin folder of `rid`, searched under the project's import roots."""
        pdir = self.workspace.project_dir(pid)
        candidates: list[Path] = []
        for rec in iter_jsonl(pdir / "sources/imports.jsonl"):
            root = Path(rec["root"])
            candidates.append(root / RECYCLE / rid)
            # conversion datasets live in `{derived root}/{project}/{task}/dataset/`
            if str(rec.get("source_key") or "").startswith("task:") and root.is_dir():
                candidates.extend(root.glob(f"*/*/dataset/{RECYCLE}/{rid}"))
        for folder in dict.fromkeys(candidates):
            if not (folder / MANIFEST).is_file() or folder.is_symlink():
                continue
            real = realpath(folder)
            self._guard_write(real)
            manifest = read_json(real / MANIFEST)
            if (
                real.parent.name == RECYCLE
                and manifest.get("recycle_id") == rid
                and pid in manifest.get("items", {})
            ):
                return real
        return None

    def list(self, pid: str) -> list[RecycleBinEntry]:
        rows = []
        for entry in self._journal(pid):
            if entry.get("purged") or "recycle_id" not in entry:
                continue
            folder = self._bin(pid, entry["recycle_id"])
            manifest = read_json(folder / MANIFEST) if folder else {}
            scan = manifest.get("scan", {})
            rows.append(
                RecycleBinEntry(
                    recycle_id=entry["recycle_id"],
                    at=entry.get("at", ""),
                    reviewer=entry.get("reviewer", ""),
                    case_id=scan.get("case_id"),
                    scan_idx=scan.get("scan_idx"),
                    item_ids=entry.get("item_ids", []),
                    n_files=len(manifest.get("files", [])),
                    projects=sorted(manifest.get("items", {})),
                    available=folder is not None and manifest.get("status") == "completed",
                )
            )
        rows.sort(key=lambda r: r.at, reverse=True)
        return rows

    def _restore_plan(
        self, pid: str, rid: str
    ) -> tuple[RestorePlan, Path, dict[str, Any], dict[Path, Path], dict[Path, bytes]]:
        self._entry(pid, rid)
        folder = self._bin(pid, rid)
        if folder is None:
            raise ValidationProblem("The recycle bin folder of this scan is missing")
        manifest = read_json(folder / MANIFEST)
        if manifest.get("status") != "completed":
            raise ValidationProblem("This recycle did not complete; nothing to restore")
        scan = manifest["scan"]
        case, idx = scan["case_id"], scan["scan_idx"]
        projects = sorted(manifest["items"])
        for other in projects:
            try:
                self.workspace.project_dir(other)
            except NotFound:
                raise ValidationProblem(
                    f"Project {other} shares this scan but is archived or removed; restore it first"
                ) from None
        items = {p: [Item.model_validate(i) for i in rows] for p, rows in manifest["items"].items()}
        ids = {i.item_id for its in items.values() for i in its}
        for other in projects:
            taken = sorted(ids & set(self.index.load_resolved(other).by_id))
            if taken:
                raise ValidationProblem(f"Already in the index of project {other}: {taken[0]}")

        moves: dict[Path, Path] = {}
        for record in manifest["files"]:
            source = realpath(folder / record["recycled"])
            target = Path(record["original"])
            if not is_within(source, folder):
                raise ValidationProblem("Invalid recycled file path")
            if not source.is_file():
                raise ValidationProblem(f"A recycled file is missing: {record['recycled']}")
            occupied = target.exists() or target.is_symlink()
            if occupied and record["recycled"].startswith("project_cache/"):
                continue  # rebuilt since; a cache file is disposable
            if occupied:
                raise ValidationProblem(f"A file already exists at its original path: {target}")
            self._guard_write(target)
            moves[source] = target

        backups: dict[Path, Path] = {}
        for record in manifest["backups"]:
            if record["backup"] is None:  # the file did not exist before the recycle
                continue
            backup = realpath(folder / record["backup"])
            if not is_within(backup, folder) or not backup.is_file():
                raise ValidationProblem("A metadata backup of this scan is missing")
            backups[Path(record["original"])] = backup
        pdirs = {other: self.workspace.project_dir(other) for other in projects}
        own = {realpath(d / f) for d in pdirs.values() for f in (*INDEX_FILES, JOURNAL)}
        writes: dict[Path, bytes] = {}
        refs = {v.ref for its in items.values() for i in its for v in i.volumes()}
        for path, backup in backups.items():
            if realpath(path) in own:
                continue
            self._guard_write(path)
            content = self._merged(path, backup, manifest, ids, case, idx, refs)
            if content is not None:
                writes[path] = content

        by_original = {realpath(path): backup for path, backup in backups.items()}
        for other, its in items.items():
            current = self.index.load_resolved(other)
            pdir = pdirs[other]
            warnings = list(current.warnings)
            seen = {_key(w.model_dump(mode="json")) for w in warnings}
            old = by_original.get(realpath(pdir / "index/qc_warnings.jsonl"))
            # The recycle dropped the scan's warnings, and its case's once no scan was left
            case_gone = case not in current.cases_by_id
            for row in iter_jsonl(old) if old else []:
                w = QcWarning.model_validate(row)
                ours = w.item_id in ids or (case_gone and w.case_id == case)
                if ours and _key(row) not in seen:
                    warnings.append(w)
            self._index_writes(writes, other, [*current.items, *its], warnings)
            journal = pdir / JOURNAL
            writes[journal] = _jsonl(
                [e for e in self._journal(other) if e.get("recycle_id") != rid]
            )

        parents = {*(t.parent for t in moves.values()), *(p.parent for p in writes)}
        for parent in parents:
            existing = next(p for p in (parent, *parent.parents) if p.exists())
            if not os.access(existing, os.W_OK):
                raise ValidationProblem(
                    "The dataset or related outputs are read-only. Enable write access before "
                    "restoring a scan."
                )
        public = RestorePlan(
            recycle_id=rid,
            case_id=case,
            scan_idx=idx,
            item_ids=sorted(i.item_id for i in items.get(pid, [])),
            n_files=len(moves),
            n_metadata_files=len(writes),
            projects=projects,
            token="",
        )
        signature = [
            (str(p), p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted({*moves, *writes})
            if p.exists()
        ]
        public.token = hashlib.sha256(
            json.dumps([public.model_dump(), signature], sort_keys=True).encode()
        ).hexdigest()
        return public, folder, manifest, moves, writes

    @staticmethod
    def _merged(
        path: Path,
        backup: Path,
        manifest: dict[str, Any],
        ids: set[str],
        case: str,
        idx: str,
        refs: set[str],
    ) -> bytes | None:
        """The current file with the scan's rows from `backup` added back; None if unchanged."""
        if path.suffix == ".parquet":
            import pyarrow as pa
            import pyarrow.compute as pc
            import pyarrow.parquet as pq

            old = pq.read_table(backup)
            rows = old.filter(pc.is_in(old["item_id"], value_set=pa.array(sorted(ids))))
            if path.is_file():
                table = pq.read_table(path)
                rows = rows.filter(
                    pc.invert(pc.is_in(rows["item_id"], value_set=table["item_id"].unique()))
                )
                try:
                    rows = pa.concat_tables([table, rows], promote_options="default")
                except (pa.ArrowInvalid, pa.ArrowTypeError):
                    raise ValidationProblem(
                        f"The columns of {path.name} changed since the recycle; rerun the task "
                        "after restoring"
                    ) from None
            sink = pa.BufferOutputStream()
            pq.write_table(rows, sink)
            data: bytes = sink.getvalue().to_pybytes()
            return data
        if path.name == "run.json":
            run = read_json(path) if path.is_file() else read_json(backup)
            outputs = run.get("outputs") or []
            back = [o for o in manifest["removed_metadata"].get(str(path), []) if o not in outputs]
            if not back:
                return None
            run["outputs"] = outputs + back
            return (json.dumps(run, ensure_ascii=False, indent=2) + "\n").encode()
        if path.name == "hashes.json":
            raw = read_json(path) if path.is_file() else {"files": {}}
            hashes = read_json(backup).get("files", {})
            added = {k: v for k, v in hashes.items() if k in refs and k not in raw.get("files", {})}
            if not added:
                return None
            raw["files"] = {**raw.get("files", {}), **added}
            return json.dumps(raw).encode()
        current = list(iter_jsonl(path)) if path.is_file() else []
        merged = _unprune(list(iter_jsonl(backup)), current, ids, case, idx)
        return None if merged == current else _jsonl(merged)

    def preview_restore(self, pid: str, rid: str) -> RestorePlan:
        return self._restore_plan(pid, rid)[0]

    async def restore(
        self, pid: str, rid: str, request: RestoreRequest, reviewer: str | None
    ) -> RestoreResult:
        reviewer = require(reviewer)
        if not request.confirmed:
            raise ValidationProblem("Confirm restoring the scan")
        async with self.workspace.locks("_recycle"), AsyncExitStack() as locks:
            for other in sorted(p.project_id for p in self.workspace.list()):
                await locks.enter_async_context(self.workspace.locks(other))
            if any(j.status not in TERMINAL for j in self.jobs.list()):
                raise JobConflict("Wait for running jobs before restoring a CT scan")
            public, folder, manifest, moves, writes = self._restore_plan(pid, rid)
            if public.token != request.token:
                raise PreconditionFailed("The recycle bin changed; reopen the restore confirmation")
            transaction: dict[str, Any] = {
                "kind": "restore",
                "recycle_id": rid,
                "at": utc_now(),
                "reviewer": reviewer,
                "status": "prepared",
                "items": manifest["items"],
                "files": manifest["files"],
                "backups": [],
            }
            self._commit(folder, transaction, RESTORE, moves, writes, "restore")
            # What is left (manifest, backups) describes a recycle that no longer exists
            shutil.rmtree(folder, ignore_errors=True)
            for other in public.projects:
                self.bus.publish(other, "project.updated", {"fields": ["recycle"]})
            return RestoreResult(
                recycle_id=rid, item_ids=public.item_ids, project_ids=public.projects
            )

    async def delete(self, pid: str, rid: str, request: DeleteRequest) -> None:
        if not request.confirmed:
            raise ValidationProblem("Confirm deleting the scan permanently")
        async with self.workspace.locks("_recycle"), AsyncExitStack() as locks:
            for other in sorted(p.project_id for p in self.workspace.list()):
                await locks.enter_async_context(self.workspace.locks(other))
            self._entry(pid, rid)
            folder = self._bin(pid, rid)
            projects = {pid}
            if folder is not None:
                projects.update(read_json(folder / MANIFEST).get("items", {}))
                shutil.rmtree(folder)
            active = {p.project_id for p in self.workspace.list()}
            for other in sorted(projects & active):
                journal = self.workspace.project_dir(other) / JOURNAL
                rows = [
                    # Only what keeps an index rebuild from bringing the items back
                    {"recycle_id": rid, "item_ids": e.get("item_ids", []), "purged": True}
                    if e.get("recycle_id") == rid
                    else e
                    for e in self._journal(other)
                ]
                atomic_write_bytes(journal, _jsonl(rows))
                self.bus.publish(other, "project.updated", {"fields": ["recycle"]})
