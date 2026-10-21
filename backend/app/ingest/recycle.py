"""CUR-16: explicit scan recycling, with a recoverable file manifest (ADR-0029)."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.errors import JobConflict, PreconditionFailed, ValidationProblem
from app.core.fsio import atomic_write_bytes, atomic_write_json, iter_jsonl, read_json
from app.core.ids import new_ulid, utc_now
from app.core.paths import PathResolver, is_within, parse_ref, realpath
from app.core.reviewer import require
from app.events.bus import EventBus
from app.ingest.cases import build_cases
from app.ingest.counting import split_items
from app.ingest.models import Item
from app.ingest.normalize import PhaseRules
from app.ingest.store import IndexStore, item_rows
from app.jobs.manager import JobManager
from app.jobs.types import TERMINAL
from app.projects.service import Workspace

RECYCLE = "recycle_bin"
JOURNAL = "logs/recycle.jsonl"


class RecyclePlan(BaseModel):
    case_id: str
    scan_idx: str
    item_ids: list[str]
    recycle_bin: str
    n_files: int
    n_metadata_rows: int
    projects: list[str]
    token: str


class RecycleRequest(BaseModel):
    confirmed: bool
    token: str = Field(min_length=1)


class RecycleResult(BaseModel):
    recycle_id: str
    recycle_dir: str
    item_ids: list[str]
    project_ids: list[str]


@dataclass
class _Plan:
    public: RecyclePlan
    root: Path
    items: dict[str, list[Item]]
    moves: dict[Path, str] = field(default_factory=dict)
    writes: dict[Path, bytes] = field(default_factory=dict)
    removed: dict[str, Any] = field(default_factory=dict)


def excluded_items(pdir: Path) -> set[str]:
    """Historical input snapshots stay intact; a rebuild must not resurrect a recycled CT."""
    return {str(iid) for row in iter_jsonl(pdir / JOURNAL) for iid in row.get("item_ids", [])}


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return b"".join((json.dumps(r, ensure_ascii=False) + "\n").encode() for r in rows)


def _move_file(source: Path, target: Path) -> None:
    """Rename locally; across mounts, verify a durable copy before unlinking the original."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(source, target)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    try:
        with source.open("rb") as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        with source.open("rb") as src, target.open("rb") as dst:
            if (
                hashlib.file_digest(src, "sha256").digest()
                != hashlib.file_digest(dst, "sha256").digest()
            ):
                raise OSError("Recycle copy verification failed")
        shutil.copystat(source, target)
        source.unlink()
    except BaseException:
        target.unlink(missing_ok=True)
        raise


class RecycleService:
    def __init__(
        self, workspace: Workspace, index: IndexStore, jobs: JobManager, bus: EventBus
    ) -> None:
        self.workspace, self.index, self.jobs, self.bus = workspace, index, jobs, bus

    def _plan(self, pid: str, iid: str) -> _Plan:
        selected = self.index.get_item(pid, iid)
        resolver = self.workspace.resolver(pid)
        if selected.image is None:
            raise ValidationProblem("The scan has no image reference")
        image = resolver.resolve(selected.image.ref)
        imports = list(iter_jsonl(self.workspace.project_dir(pid) / "sources/imports.jsonl"))
        rec = next((r for r in imports if r["import_id"] == selected.import_id), None)
        if rec is None:
            raise ValidationProblem("The scan has no dataset import record")
        root = realpath(Path(rec["root"]))
        # Project conversion imports use the DERIVED alias root; the accumulating dataset
        # has its own folder below it. Imported DatasetID roots are already exact.
        if str(rec.get("source_key") or "").startswith("task:"):
            root = next((p for p in image.parents if p.name == "dataset"), root)
        alias = parse_ref(selected.image.ref).alias
        resolver.guard_for(alias).check(root)
        if not is_within(image, root) or RECYCLE in image.relative_to(root).parts:
            raise ValidationProblem("The image is outside its active dataset")
        recycle = root / RECYCLE
        if recycle.is_symlink() or not is_within(realpath(recycle), root):
            raise ValidationProblem("The recycle bin must be a directory inside the dataset")
        target = [
            i
            for i in self.index.load_resolved(pid).items
            if (i.case_id, i.scan_idx) == (selected.case_id, selected.scan_idx)
        ]
        images = {resolver.resolve(i.image.ref) for i in target if i.image}
        affected = {pid: target}
        # A dataset may be open in several projects. Update every active consumer together.
        for project in self.workspace.list():
            other = project.project_id
            if other == pid:
                continue
            other_resolver = self.workspace.resolver(other)
            indexed = self.index.load_resolved(other).items
            scans = {
                (i.case_id, i.scan_idx)
                for i in indexed
                if i.image and other_resolver.resolve(i.image.ref) in images
            }
            if scans:
                affected[other] = [i for i in indexed if (i.case_id, i.scan_idx) in scans]
        for project in self.workspace.list(archived=True):
            pdir = self.workspace.folder(project.project_id)
            cfg = read_json(pdir / "project.json")
            archived_resolver = PathResolver(
                {r["alias"]: r["path"] for r in cfg["path_roots"]},
                self.workspace.guard,
                roles={r["alias"]: r.get("role", "source") for r in cfg["path_roots"]},
                derived_guard=self.workspace.project_derived_guard(project.project_id)
                if not project.archived
                else self.workspace.derived_guard,
            )
            if any(
                row.get("image") and archived_resolver.resolve(row["image"]["ref"]) in images
                for row in iter_jsonl(pdir / "index/items.jsonl")
            ):
                raise ValidationProblem(
                    "An archived project uses this scan; restore that project first"
                )
        ids = {i.item_id for its in affected.values() for i in its}
        public = RecyclePlan(
            case_id=selected.case_id,
            scan_idx=selected.scan_idx,
            item_ids=sorted(i.item_id for i in target),
            recycle_bin=str(recycle),
            n_files=0,
            n_metadata_rows=0,
            projects=sorted(affected),
            token="",
        )
        plan = _Plan(public, root, affected)

        def add(ref: str, project_id: str) -> None:
            r = self.workspace.resolver(project_id)
            path = r.resolve(ref)
            if not path.exists():
                return
            if not path.is_file() or path.is_symlink():
                raise ValidationProblem("Only regular scan files can be recycled")
            if path in plan.moves:
                return
            name = (
                path.relative_to(root).as_posix()
                if is_within(path, root)
                else f"{project_id}/{parse_ref(ref).alias}/{parse_ref(ref).rel}"
            )
            if RECYCLE in Path(name).parts:
                raise ValidationProblem("A scan references files already in a recycle bin")
            plan.moves[path] = ("files/" if is_within(path, root) else "derived_files/") + name

        for other, its in affected.items():
            for it in its:
                for vol in it.volumes():
                    add(vol.ref, other)
                    if vol.format == "nifti":
                        ref = vol.ref.removesuffix(".gz").removesuffix(".nii") + ".json"
                        add(ref, other)
                    elif vol.format == "npy":
                        add(vol.ref + ".json", other)
                sidecar = it.extra.get("dicom_sidecar")
                if isinstance(sidecar, str) and sidecar:
                    add(sidecar, other)
            pdir = self.workspace.project_dir(other)
            # All registered outputs, including inactive segmentation sets / older runs.
            for run_file in sorted((pdir / "tasks/runs").glob("*/run.json")):
                run = read_json(run_file)
                outputs = run.get("outputs") or []
                removed = [o for o in outputs if o.get("item_id") in ids]
                for output in removed:
                    ref = output.get("ref")
                    if isinstance(ref, str) and ":" in ref:
                        add(ref, other)
                if removed:
                    run["outputs"] = [o for o in outputs if o not in removed]
                    plan.writes[run_file] = (
                        json.dumps(run, ensure_ascii=False, indent=2) + "\n"
                    ).encode()
                    plan.removed[str(run_file)] = removed
                out = run.get("output_dir")
                if out:
                    candidate = Path(out) / "metadata.jsonl"
                    if candidate.is_file():
                        self.workspace.project_derived_guard(other).check(candidate)
                        self._prune_jsonl(plan, candidate, ids, selected)
            candidates = [pdir / "derived/runs.jsonl"]
            for folder in ("tasks/runs", "radiomics/runs"):
                for name in (
                    "items.jsonl",
                    "units.jsonl",
                    "masks.jsonl",
                    "annotations.jsonl",
                    "errors.jsonl",
                ):
                    candidates.extend((pdir / folder).glob(f"*/{name}"))
            for path in candidates:
                for row in iter_jsonl(path):
                    outputs = row.get("outputs") or [row]
                    for output in outputs:
                        if output.get("item_id") in ids:
                            ref = output.get("ref")
                            if isinstance(ref, str) and ":" in ref:
                                add(ref, other)
                self._prune_jsonl(plan, path, ids, selected)
            self._prune_parquet(plan, pdir / "index/variables.parquet", ids)
            hashes = pdir / "index/hashes.json"
            if hashes.is_file():
                raw = read_json(hashes)
                hash_refs = {v.ref for i in its for v in i.volumes()}
                removed_hashes = {k: v for k, v in raw.get("files", {}).items() if k in hash_refs}
                if removed_hashes:
                    raw["files"] = {k: v for k, v in raw["files"].items() if k not in hash_refs}
                    plan.writes[hashes] = json.dumps(raw).encode()
                    plan.removed[str(hashes)] = list(removed_hashes.values())
            fingerprints = {v.fp for i in its for v in i.volumes() if v.fp}
            for cache in (pdir / "cache").glob("**/*"):
                if cache.is_file() and any(cache.name.startswith(fp) for fp in fingerprints):
                    if not is_within(realpath(cache), realpath(pdir / "cache")):
                        raise ValidationProblem("Cached scan file escapes its cache directory")
                    plan.moves[cache] = f"project_cache/{other}/{cache.relative_to(pdir / 'cache')}"
            # Parquet feature tables and parts: retain other scans, archive removed rows.
            for folder in ("radiomics/runs", "tasks/runs"):
                for path in (pdir / folder).glob("**/*.parquet"):
                    self._prune_parquet(plan, path, ids)
            # Events remain append-only history. Capture the relevant layer values in the audit.
            for path in [pdir / "curation/events.jsonl", *(pdir / "events").glob("*.jsonl")]:
                rows = [
                    r
                    for r in iter_jsonl(path)
                    if r.get("item_id") in ids
                    or r.get("target")
                    in {*ids, selected.case_id, f"{selected.case_id}.{selected.scan_idx}"}
                    or (
                        r.get("case_id") == selected.case_id
                        and str(r.get("scan_idx", selected.scan_idx)) == selected.scan_idx
                    )
                ]
                if rows:
                    plan.removed[str(path)] = rows

        for rel in ("metadata.jsonl", "voi/voi_catalog.jsonl", "annotations.jsonl"):
            path = root / rel
            if path.exists():
                if path.is_symlink() or not is_within(realpath(path), root):
                    raise ValidationProblem("Dataset metadata escapes its root")
                resolver.guard_for(alias).check(path)
                self._prune_jsonl(plan, path, ids, selected)
        # Never move a volume used by an unrelated scan (including a shared segmentation).
        for project in self.workspace.list():
            other = project.project_id
            r = self.workspace.resolver(other)
            removed_ids = {i.item_id for i in affected.get(other, [])}
            for it in self.index.load_resolved(other).items:
                if it.item_id in removed_ids:
                    continue
                refs = [v.ref for v in it.volumes()]
                if isinstance(it.extra.get("dicom_sidecar"), str):
                    refs.append(it.extra["dicom_sidecar"])
                if any(r.resolve(ref) in plan.moves for ref in refs):
                    raise ValidationProblem(
                        "A file is shared with another scan; recycle it separately"
                    )
        writable = {root, *(p.parent for p in plan.moves), *(p.parent for p in plan.writes)}
        if any(not os.access(p, os.W_OK) for p in writable):
            raise ValidationProblem(
                "The dataset or related outputs are read-only. Enable write access before "
                "recycling a scan (Docker: set DATA_MOUNT_MODE=rw and recreate the container)."
            )
        if len(set(plan.moves.values())) != len(plan.moves):
            raise ValidationProblem("Two scan files map to the same recycle destination")
        public.n_files = len(plan.moves)
        public.n_metadata_rows = sum(len(v) for v in plan.removed.values())
        signature = [
            (str(p), p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted({*plan.moves, *plan.writes})
        ]
        public.token = hashlib.sha256(
            json.dumps([public.model_dump(), signature], sort_keys=True).encode()
        ).hexdigest()
        return plan

    @staticmethod
    def _prune_jsonl(plan: _Plan, path: Path, ids: set[str], selected: Item) -> None:
        if not path.is_file():
            return
        if path.is_symlink():
            raise ValidationProblem("Refusing to rewrite a symlinked metadata file")
        rows = list(iter_jsonl(path))

        def matches(row: dict[str, Any]) -> bool:
            return row.get("item_id") in ids or (
                str(row.get("case_id", "")) == selected.case_id
                and str(row.get("scan_idx", "")) == selected.scan_idx
            )

        removed = [r for r in rows if matches(r)]
        # The derived ledger has per-item outputs nested inside a run row.
        kept = []
        for row in rows:
            if matches(row):
                continue
            if isinstance(row.get("outputs"), list):
                dropped = [o for o in row["outputs"] if o.get("item_id") in ids]
                if dropped:
                    removed.extend(dropped)
                    row = {**row, "outputs": [o for o in row["outputs"] if o not in dropped]}
            kept.append(row)
        if removed:
            plan.writes[path] = _jsonl(kept)
            plan.removed[str(path)] = removed

    @staticmethod
    def _prune_parquet(plan: _Plan, path: Path, ids: set[str]) -> None:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq

        if not path.is_file():
            return
        if path.is_symlink():
            raise ValidationProblem("Refusing to rewrite a symlinked feature table")
        table = pq.read_table(path)
        if "item_id" not in table.column_names:
            return
        mask = pc.is_in(table["item_id"], value_set=pa.array(sorted(ids)))
        removed = table.filter(mask)
        if removed.num_rows:
            sink = pa.BufferOutputStream()
            pq.write_table(table.filter(pc.invert(mask)), sink)
            plan.writes[path] = sink.getvalue().to_pybytes()
            # Preserve Arrow types and complete metadata in the backup, no lossy JSON cast.
            plan.removed[str(path)] = [{"rows": removed.num_rows, "backup": "original parquet"}]

    def _rollback(self, destination: Path, manifest: dict[str, Any]) -> None:
        for record in reversed(manifest["backups"]):
            path = Path(record["original"])
            self._guard_write(path)
            if record["backup"] is None:
                path.unlink(missing_ok=True)
            else:
                backup = realpath(destination / record["backup"])
                if not is_within(backup, destination):
                    raise ValidationProblem("Invalid recycle backup path")
                atomic_write_bytes(path, backup.read_bytes())
        for record in reversed(manifest["files"]):
            path = Path(record["original"])
            self._guard_write(path)
            recycled = realpath(destination / record["recycled"])
            if not is_within(recycled, destination):
                raise ValidationProblem("Invalid recycled file path")
            if recycled.exists() and not path.exists():
                _move_file(recycled, path)
        manifest["status"] = "rolled_back"
        atomic_write_json(destination / "manifest.json", manifest)
        for pid in manifest["items"]:
            self.index.invalidate(pid)

    def _guard_write(self, path: Path) -> None:
        if not is_within(
            realpath(path), realpath(self.workspace.settings.workspace_root)
        ) and not self.workspace.derived_guard.is_allowed(path):
            self.workspace.guard.check(path)

    def recover(self) -> None:
        """At startup, finish rolling back any interrupted, previously confirmed transaction."""
        pending_dir = self.workspace.settings.workspace_root / "recycle_pending"
        for pending in sorted(pending_dir.glob("*.json")):
            destination = realpath(Path(read_json(pending)["manifest"]).parent)
            self._guard_write(destination)
            if destination.parent.name != RECYCLE:
                raise ValidationProblem("Invalid pending recycle destination")
            manifest = read_json(destination / "manifest.json")
            if manifest["status"] == "prepared":
                self._rollback(destination, manifest)
            pending.unlink()

    def preview(self, pid: str, iid: str) -> RecyclePlan:
        return self._plan(pid, iid).public

    async def recycle(
        self, pid: str, iid: str, request: RecycleRequest, reviewer: str | None
    ) -> RecycleResult:
        reviewer = require(reviewer)
        if not request.confirmed:
            raise ValidationProblem("Confirm moving the whole scan to the recycle bin")
        async with self.workspace.locks("_recycle"), AsyncExitStack() as locks:
            # Lock every active project: sharing and output registration cannot race us.
            pids = sorted(p.project_id for p in self.workspace.list())
            for other in pids:
                await locks.enter_async_context(self.workspace.locks(other))
            self.index.get_item(pid, iid)
            if any(j.status not in TERMINAL for j in self.jobs.list()):
                raise JobConflict("Wait for running jobs before recycling a CT scan")
            plan = self._plan(pid, iid)
            if plan.public.token != request.token:
                raise PreconditionFailed("The scan changed; reopen the recycle confirmation")
            rid = new_ulid()
            destination = plan.root / RECYCLE / rid
            destination.mkdir(parents=True, exist_ok=False)
            manifest: dict[str, Any] = {
                "recycle_id": rid,
                "at": utc_now(),
                "reviewer": reviewer,
                "status": "prepared",
                "scan": plan.public.model_dump(),
                "items": {
                    p: [i.model_dump(mode="json") for i in its] for p, its in plan.items.items()
                },
                "removed_metadata": plan.removed,
                "files": [{"original": str(p), "recycled": name} for p, name in plan.moves.items()],
                "backups": [],
            }
            # Include indexes, status and journal in the same rollback boundary.
            for other, its in plan.items.items():
                pdir = self.workspace.project_dir(other)
                idx = self.index.load_resolved(other)
                ids = {i.item_id for i in its}
                remaining = [i for i in idx.items if i.item_id not in ids]
                warnings = [
                    w
                    for w in idx.warnings
                    if w.item_id not in ids
                    and not (
                        w.case_id == plan.public.case_id
                        and not any(i.case_id == w.case_id for i in remaining)
                    )
                ]
                cfg = self.workspace.get(other)
                cases = build_cases(
                    remaining,
                    warnings,
                    PhaseRules(tuple(cfg.phase_vocabulary), cfg.phase_mapping),
                    cfg.phase_priority,
                )
                plan.writes[pdir / "index/items.jsonl"] = _jsonl(item_rows(remaining))
                plan.writes[pdir / "index/cases.jsonl"] = _jsonl(
                    [c.model_dump(mode="json") for c in cases]
                )
                plan.writes[pdir / "index/qc_warnings.jsonl"] = _jsonl(
                    [w.model_dump(mode="json") for w in warnings]
                )
                status = self.index.status(other).model_dump(mode="json")
                status.update(
                    n_items=split_items(i.status for i in remaining)[0],
                    n_excluded_upstream=split_items(i.status for i in remaining)[1],
                    n_warnings=len(warnings),
                )
                plan.writes[pdir / "index/status.json"] = json.dumps(status).encode()
                journal = pdir / JOURNAL
                entry = {
                    "recycle_id": rid,
                    "at": manifest["at"],
                    "reviewer": reviewer,
                    "item_ids": sorted(ids),
                }
                plan.writes[journal] = (journal.read_bytes() if journal.exists() else b"") + _jsonl(
                    [entry]
                )
            for n, path in enumerate(plan.writes):
                if path.exists():
                    backup = f"metadata/{n}/{path.name}"
                    atomic_write_bytes(destination / backup, path.read_bytes())
                else:
                    backup = None
                manifest["backups"].append({"original": str(path), "backup": backup})
            atomic_write_json(destination / "manifest.json", manifest)
            pending = self.workspace.settings.workspace_root / "recycle_pending" / f"{rid}.json"
            atomic_write_json(pending, {"manifest": str(destination / "manifest.json")})
            try:
                for path, rel in plan.moves.items():
                    to = destination / rel
                    to.parent.mkdir(parents=True, exist_ok=True)
                    _move_file(path, to)
                for path, content in plan.writes.items():
                    atomic_write_bytes(path, content)
                manifest["status"] = "completed"
                atomic_write_json(destination / "manifest.json", manifest)
            except BaseException:
                self._rollback(destination, manifest)
                pending.unlink(missing_ok=True)
                raise
            finally:
                for other in plan.items:
                    self.index.invalidate(other)
            pending.unlink(missing_ok=True)
            for other in plan.items:
                self.bus.publish(other, "project.updated", {"fields": ["recycle"]})
            return RecycleResult(
                recycle_id=rid,
                recycle_dir=str(destination),
                item_ids=plan.public.item_ids,
                project_ids=plan.public.projects,
            )
