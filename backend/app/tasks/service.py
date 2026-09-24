"""Task service: list, validate, preflight, estimate, runs, outputs (TSK-01..12, API-42..47).

Stateless: routers build one per request from the app context. The API process writes the run
record (`tasks/runs/{run_id}/`), the segmentation-set registration and the derived ledger under
the project lock (BE-05); the task writes only its job dir and its `output_dir` (ADR-0014).
`radiomics.pyradiomics` is served by the radiomics service behind the same endpoints (RAD-13).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import shutil
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from app.config import Settings
from app.core.errors import (
    JobConflict,
    NotFound,
    Problem,
    ValidationProblem,
)
from app.core.fsio import append_jsonl, atomic_write_json, iter_jsonl, read_json
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.core.paths import is_within, realpath
from app.events.bus import EventBus
from app.imaging.fingerprint import quick_fingerprint
from app.ingest.models import Item
from app.ingest.segsets import record_masks
from app.ingest.store import IndexStore
from app.jobs.manager import JobManager
from app.jobs.types import TERMINAL, JobHandle, JobInfo, JobSpec
from app.projects.models import (
    SEG_ID_RE,
    LabelEntry,
    ProjectConfig,
    ProjectPatch,
    SegmentationSet,
    SegProducer,
)
from app.projects.presets import AUTO_LABEL_COLORS, auto_label_name
from app.projects.service import Workspace
from app.tasks import protocol, registry
from app.tasks.builtin import run_entry
from app.tasks.models import (
    RESUMABLE_TASK_RUN,
    TERMINAL_TASK_RUN,
    VOLUME_OUTPUTS,
    PreflightRequest,
    PreflightResult,
    SettingsIssue,
    Suggestion,
    TaskEstimate,
    TaskInfo,
    TaskItemError,
    TaskList,
    TaskManifest,
    TaskRef,
    TaskRunCounts,
    TaskRunDetail,
    TaskRunInput,
    TaskRunOutput,
    TaskRunProgress,
    TaskRunRecord,
    TaskRunRequest,
    TaskRunStarted,
    TaskRunStatus,
    TaskRunSummary,
    TaskSelection,
    TaskValidateResult,
)
from app.tasks.radiomics_task import RadiomicsTask
from app.tasks.registry import RADIOMICS_TASK, Registry
from app.tasks.schema import normalize, settings_hash
from app.variables.service import VariableService

log = logging.getLogger("app.tasks")

TASKS: Final = "tasks"
RUNS: Final = "runs"
RUN_JSON: Final = "run.json"
ITEMS: Final = "items.jsonl"  # per-item outcomes of every attempt (last line per item wins)
LOGS: Final = "log.jsonl"
LEDGER: Final = Path("derived") / "runs.jsonl"
POLL_S: Final = 0.2
CANCEL_GRACE_S: Final = 30.0
SAMPLE_ITEMS: Final = 3
REVIEWER_MAX: Final = 100
_SEG_RE = re.compile(SEG_ID_RE)


def _reviewer(raw: str | None) -> str | None:
    name = (raw or "").strip()
    if len(name) > REVIEWER_MAX:
        raise ValidationProblem(
            "Reviewer name too long",
            errors=[{"loc": ["header", "X-Reviewer"], "msg": f"max {REVIEWER_MAX} chars"}],
        )
    return name or None


def _issue_errors(
    issues: Sequence[SettingsIssue], prefix: Sequence[str | int]
) -> list[dict[str, Any]]:
    return [
        {"loc": [*prefix, *i.loc], "msg": i.msg, "type": i.rule}
        for i in issues
        if i.severity == "error"
    ]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_run(run_dir: Path, rec: TaskRunRecord) -> None:
    atomic_write_json(run_dir / RUN_JSON, rec.model_dump(mode="json"))


def _read_run(run_dir: Path) -> TaskRunRecord:
    return TaskRunRecord.model_validate(read_json(run_dir / RUN_JSON))


def item_outcomes(run_dir: Path) -> dict[str, dict[str, Any]]:
    """item_id → last outcome line over all attempts."""
    out: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(run_dir / ITEMS):
        out[str(row["item_id"])] = row
    return out


def default_seg_id(task_id: str, run_id: str) -> str:
    """`{task-short}-{run_id[:8]}` (TASKS.md §Outputs), lower-cased to the seg_id slug."""
    short = task_id.rsplit(".", 1)[-1].lower()
    return f"{short}-{run_id[:8].lower()}"


@dataclass
class _Live:
    """Per-attempt driver state."""

    pid: str
    rid: str
    run_dir: Path
    job_dir: Path
    manifest: TaskManifest
    seg_id: str | None
    done: int = 0
    registered: bool = False
    outputs: list[TaskRunOutput] = field(default_factory=list)
    cancel_sent: bool = False


class TaskService:
    def __init__(
        self,
        settings: Settings,
        registry: Registry,
        workspace: Workspace,
        store: IndexStore,
        jobs: JobManager,
        bus: EventBus,
        locks: ProjectLocks,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.workspace = workspace
        self.store = store
        self.jobs = jobs
        self.bus = bus
        self.locks = locks

    # -- manifests (API-42/43) -------------------------------------------------------------

    @property
    def queue_dir(self) -> Path:
        return self.settings.workspace_root / "queue"

    def _info(self, info: TaskInfo) -> TaskInfo:
        if info.manifest.runtime.type != "external":
            return info
        return info.model_copy(
            update={"runner_online": registry.runner_online(self.queue_dir, info.manifest.id)}
        )

    def list_tasks(self) -> TaskList:
        return TaskList(
            tasks=[self._info(t) for t in self.registry.tasks.values()],
            invalid=list(self.registry.invalid),
            runners=registry.runners(self.queue_dir),
        )

    def get(self, task_id: str) -> TaskInfo:
        return self._info(self.registry.get(task_id))

    def validate(self, task_id: str, raw: dict[str, Any]) -> TaskValidateResult:
        info = self.registry.get(task_id)
        if task_id == RADIOMICS_TASK:
            return self._radiomics().validate_task(raw)
        m = info.manifest
        norm, issues = normalize(m.settings_schema, m.defaults, raw)
        ok = not any(i.severity == "error" for i in issues)
        return TaskValidateResult(
            ok=ok,
            issues=issues,
            settings=norm if ok else None,
            settings_hash=settings_hash(m.id, m.version, norm) if ok else None,
        )

    def _settings(self, m: TaskManifest, raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Authoritative validation (TSK-02): 422 with field issues, else normalized settings."""
        norm, issues = normalize(m.settings_schema, m.defaults, raw)
        errors = _issue_errors(issues, ["body", "settings"])
        if errors:
            raise ValidationProblem(f"Invalid settings for {m.id}", errors=errors)
        return norm, settings_hash(m.id, m.version, norm)

    # -- selection + preflight (TSK-03/04, API-44) ----------------------------------------

    async def select(self, pid: str, sel: TaskSelection) -> list[Item]:
        """Active items matching an explicit list, or an Explorer filter, or all (TSK-03)."""
        errors: list[dict[str, Any]] = []
        if sel.item_ids is not None and sel.filter is not None:
            errors.append(
                {"loc": ["body", "selection", "filter"], "msg": "Use either item_ids or filter"}
            )
        idx = self.store.load(pid)
        items = [i for i in idx.items if i.status == "active"]
        if sel.item_ids is not None:
            for n, iid in enumerate(sel.item_ids):
                it = idx.by_id.get(iid)
                if it is None:
                    errors.append(
                        {"loc": ["body", "selection", "item_ids", n], "msg": "Unknown item"}
                    )
                elif it.status != "active":
                    errors.append(
                        {"loc": ["body", "selection", "item_ids", n], "msg": f"Item is {it.status}"}
                    )
            wanted = set(sel.item_ids)
            items = [i for i in items if i.item_id in wanted]
        f = sel.filter
        if f is not None:
            if f.phase:
                items = [i for i in items if i.phase.canonical in f.phase]
            if f.side:
                items = [i for i in items if i.side in f.side]
            if f.var:
                vs = VariableService(self.workspace, self.store, self.locks, self.bus)
                ok_ids = (await vs.filter_ids(pid, f.var))["items"]
                items = [i for i in items if i.item_id in ok_ids]
        if sel.scope is not None:
            items = [i for i in items if i.scope == sel.scope]
        if errors:
            raise ValidationProblem("Invalid selection", errors=errors)
        return sorted(items, key=lambda i: i.item_id)

    def _seg_id(self, cfg: ProjectConfig, m: TaskManifest, sel: TaskSelection) -> str | None:
        if m.requires.seg is None:
            return None
        seg_id = sel.seg_id or cfg.default_seg
        if cfg.segmentation(seg_id) is None:
            raise ValidationProblem(
                f"Unknown segmentation set {seg_id!r}",
                errors=[{"loc": ["body", "selection", "seg_id"], "msg": "unknown seg_id"}],
            )
        return seg_id

    def _not_ready(
        self, cfg: ProjectConfig, m: TaskManifest, it: Item, seg_id: str | None
    ) -> str | None:
        """Why an item can't run (TSK-04), or None when it is ready."""
        if m.input == "items" and it.image is None:
            return "no image"
        mods = m.requires.modality
        if mods and it.modality is not None and it.modality not in mods:
            return f"modality {it.modality}"
        if m.requires.seg is not None and seg_id is not None:
            if seg_id not in it.masks:
                return f"no mask in {seg_id}"
            names = m.requires.seg.labels
            if names and seg_id == "imported" and it.labels_present:
                by_name = {e.name: e.value for e in cfg.label_map}
                for name in names:
                    if by_name.get(name) not in it.labels_present:
                        return f"no {name} label in {seg_id}"
        return None

    def _suggest(self, m: TaskManifest, missing: dict[str, int]) -> list[Suggestion]:
        out: list[Suggestion] = []
        mask_gaps = {
            r: n for r, n in missing.items() if r.startswith("no mask") or " label in " in r
        }
        if not mask_gaps:
            return out
        for info in self.registry.tasks.values():
            t = info.manifest
            if t.id == m.id or "masks" not in t.outputs or t.test_only:
                continue
            for reason, n in mask_gaps.items():
                out.append(Suggestion(task_id=t.id, reason=f"{n} items: {reason}"))
        return out

    async def preflight(self, pid: str, task_id: str, req: PreflightRequest) -> PreflightResult:
        m = self.registry.get(task_id).manifest
        cfg = self.workspace.get(pid)
        needs_derived = bool(VOLUME_OUTPUTS & set(m.outputs)) and cfg.derived_root() is None
        if m.input == "source":
            return PreflightResult(
                n_selected=1 if req.selection.source else 0,
                n_ready=1 if req.selection.source else 0,
                missing={} if req.selection.source else {"no source folder": 1},
                suggestions=[],
                derived_root_required=needs_derived,
            )
        items = await self.select(pid, req.selection)
        seg_id = self._seg_id(cfg, m, req.selection)
        missing: Counter[str] = Counter()
        ready: list[str] = []
        for it in items:
            reason = self._not_ready(cfg, m, it, seg_id)
            if reason is None:
                ready.append(it.item_id)
            else:
                missing[reason] += 1
        return PreflightResult(
            n_selected=len(items),
            n_ready=len(ready),
            missing=dict(missing),
            suggestions=self._suggest(m, dict(missing)),
            derived_root_required=needs_derived,
            ready_item_ids=ready,
        )

    # -- job.json ------------------------------------------------------------------------

    def _job_items(
        self, pid: str, items: Sequence[Item], seg_id: str | None
    ) -> list[dict[str, Any]]:
        resolver = self.workspace.resolver(pid)
        out: list[dict[str, Any]] = []
        for it in items:
            image = None
            if it.image is not None:
                with contextlib.suppress(Problem):
                    image = {"path": str(resolver.resolve(it.image.ref)), "format": it.image.format}
            masks: dict[str, dict[str, Any]] = {}
            for sid, vol in it.masks.items():
                if seg_id is not None and sid != seg_id:
                    continue
                with contextlib.suppress(Problem):
                    masks[sid] = {"path": str(resolver.resolve(vol.ref)), "format": vol.format}
            out.append(
                {
                    "item_id": it.item_id,
                    "case_id": it.case_id,
                    "image": image,
                    "masks": masks,
                    "geometry": it.geometry.model_dump() if it.geometry else None,
                    "meta": {
                        "scan_idx": it.scan_idx,
                        "scope": it.scope,
                        "side": it.side,
                        "modality": it.modality,
                        "phase": it.phase.canonical,
                        "phase_raw": it.phase.raw,
                        "patient_id": it.patient_id,
                        "labels_present": it.labels_present,
                        "extra": it.extra,
                    },
                }
            )
        return out

    def _output_dir(self, pid: str, m: TaskManifest, rid: str) -> Path | None:
        if not VOLUME_OUTPUTS & set(m.outputs):
            return None
        root = self.workspace.derived_root(pid)  # derived-root-required (PRJ-13)
        return Path(root.path) / pid / m.id / "runs" / rid

    # -- estimate (TSK-05, API-44) ----------------------------------------------------------

    async def estimate(self, pid: str, task_id: str, req: PreflightRequest) -> TaskEstimate:
        info = self.registry.get(task_id)
        m = info.manifest
        if task_id == RADIOMICS_TASK:
            return await self._radiomics().estimate_task(pid, req)
        pre = await self.preflight(pid, task_id, req)
        n_units = pre.n_ready
        skipped = pre.n_selected - pre.n_ready
        if m.runtime.type == "external" or m.input == "source":
            spi = m.resources.seconds_per_item
            return TaskEstimate(
                n_units=n_units,
                n_skipped=skipped,
                seconds_per_item=spi,
                estimated_total_s=round(spi * n_units, 2) if spi is not None else None,
                basis="manifest" if spi is not None else "unknown",
            )
        settings, _ = self._settings(m, req.settings)
        sample_ids = pre.ready_item_ids[:SAMPLE_ITEMS]
        if not sample_ids:
            return TaskEstimate(
                n_units=0,
                n_skipped=skipped,
                seconds_per_item=None,
                estimated_total_s=None,
                basis="unknown",
            )
        idx = self.store.load(pid)
        seg_id = self._seg_id(self.workspace.get(pid), m, req.selection)
        sample = [idx.by_id[i] for i in sample_ids]
        job_dir = self.settings.workspace_root / ".scratch" / "estimates" / new_ulid()
        out_dir = job_dir / "out"
        protocol.write_job(
            job_dir,
            {
                "job_id": job_dir.name,
                "run_id": "estimate",
                "mode": "estimate",
                "task": {"id": m.id, "version": m.version},
                "settings": settings,
                "items": self._job_items(pid, sample, seg_id),
                "rows": [],
                "output_dir": str(out_dir) if VOLUME_OUTPUTS & set(m.outputs) else None,
                "resume": {"skip": []},
                "batch": {"size": m.resources.max_batch or len(sample)},
            },
        )
        t0 = time.monotonic()
        try:
            assert m.runtime.entry is not None
            await self.jobs.run_in_worker(run_entry, m.runtime.entry, str(job_dir))
            elapsed = time.monotonic() - t0
            result = protocol.read_result(job_dir) or {}
            errors = [
                f"{r.get('item_id')}: {r.get('message')}"
                for r in protocol.Tail(job_dir / protocol.PROGRESS).read()
                if r.get("t") == "item" and r.get("status") == "failed"
            ]
            size = (
                sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
                if out_dir.is_dir()
                else None
            )
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
        spi = elapsed / len(sample)
        if result.get("status") == "failed" and not errors:
            errors = [str(result.get("error") or "sample run failed")]
        return TaskEstimate(
            n_units=n_units,
            n_skipped=skipped,
            seconds_per_item=round(spi, 4),
            estimated_total_s=round(spi * n_units / max(1, self.jobs.workers), 2),
            output_bytes=int(size / len(sample) * n_units) if size else None,
            basis="sample",
            sample_item_ids=sample_ids,
            sample_errors=errors,
        )

    # -- runs (TSK-06..10, API-45/46) --------------------------------------------------------

    def _runs_dir(self, pid: str) -> Path:
        return self.workspace.project_dir(pid) / TASKS / RUNS

    def _run_dir(self, pid: str, rid: str) -> Path:
        d = self._runs_dir(pid) / rid
        if not is_ulid(rid) or not (d / RUN_JSON).is_file():
            raise NotFound(f"Task run {rid!r} not found")
        return d

    def _job(self, job_id: str | None) -> JobInfo | None:
        if job_id is None:
            return None
        try:
            return self.jobs.get(job_id)
        except NotFound:
            return None

    def job_dir(self, m: TaskManifest, job_id: str) -> Path:
        root = self.settings.workspace_root
        if m.runtime.type == "external":
            return root / "queue" / job_id
        return root / ".scratch" / "jobs" / job_id

    async def start(self, pid: str, req: TaskRunRequest, reviewer: str | None) -> TaskRunStarted:
        if req.task_id == RADIOMICS_TASK:
            return await self._radiomics().start_task(pid, req, reviewer)
        info = self.registry.get(req.task_id)
        m = info.manifest
        if not info.available:
            raise ValidationProblem(f"Task {m.id} is unavailable: {info.unavailable_reason}")
        who = _reviewer(reviewer)
        settings, shash = self._settings(m, req.settings)
        if m.input == "source":
            raise ValidationProblem(f"Task {m.id} reads a source folder; use its import flow")
        cfg = self.workspace.get(pid)
        items = await self.select(pid, req.selection)
        seg_id = self._seg_id(cfg, m, req.selection)
        ready = [i for i in items if self._not_ready(cfg, m, i, seg_id) is None]
        if not ready:
            raise ValidationProblem(
                "No selected item is ready for this task",
                errors=[{"loc": ["body", "selection"], "msg": "Nothing to run"}],
            )
        target = settings.get("seg_id") if "masks" in m.outputs else None
        if target is not None and (not isinstance(target, str) or not _SEG_RE.match(target)):
            raise ValidationProblem(
                "seg_id must be a lower-case slug",
                errors=[{"loc": ["body", "settings", "seg_id"], "msg": SEG_ID_RE}],
            )
        if target is not None and cfg.segmentation(target) is not None:
            raise ValidationProblem(
                f"Segmentation set {target!r} already exists; choose another seg_id",
                errors=[{"loc": ["body", "settings", "seg_id"], "msg": "exists"}],
            )
        self._check_conflict(pid, m.id)
        rid = new_ulid()
        out_dir = self._output_dir(pid, m, rid)
        now = utc_now()
        rec = TaskRunRecord(
            run_id=rid,
            task=TaskRef(id=m.id, version=m.version, manifest_hash=info.manifest_hash),
            name=(req.name or "").strip() or f"{m.title} {now}",
            status="queued",
            created_at=now,
            reviewer=who,
            runtime=m.runtime.type,
            settings=settings,
            settings_hash=shash,
            selection=req.selection.model_copy(update={"seg_id": seg_id}),
            item_ids=[i.item_id for i in ready],
            inputs=[
                TaskRunInput(
                    item_id=i.item_id,
                    image_fp=i.image.fp if i.image else None,
                    seg_id=seg_id,
                    mask_fp=(i.masks[seg_id].fp if seg_id and seg_id in i.masks else None),
                )
                for i in ready
            ],
            output_dir=str(out_dir) if out_dir else None,
            counts=TaskRunCounts(items=len(ready), skipped=len(items) - len(ready)),
        )
        run_dir = self._runs_dir(pid) / rid
        async with self.locks(pid):
            run_dir.mkdir(parents=True, exist_ok=True)
            skipped = [
                {
                    "item_id": i.item_id,
                    "status": "skipped",
                    "message": self._not_ready(cfg, m, i, seg_id),
                }
                for i in items
                if i not in ready
            ]
            if skipped:
                append_jsonl(run_dir / ITEMS, skipped)
            _write_run(run_dir, rec)
        return await self._submit(pid, run_dir, m, ready, seg_id, skip=[])

    def _check_conflict(self, pid: str, task_id: str) -> None:
        cur = self.jobs.active(pid, "task", task_id)
        if cur is not None:
            raise JobConflict(f"A {task_id} run is already active: {cur.job_id}")

    async def _submit(
        self,
        pid: str,
        run_dir: Path,
        m: TaskManifest,
        items: Sequence[Item],
        seg_id: str | None,
        skip: Sequence[str],
    ) -> TaskRunStarted:
        rid = run_dir.name
        rec = _read_run(run_dir)
        job_id = new_ulid()
        job_dir = self.job_dir(m, job_id)
        protocol.write_job(
            job_dir,
            {
                "job_id": job_id,
                "run_id": rid,
                "mode": "run",
                "task": {"id": m.id, "version": m.version},
                "settings": rec.settings,
                "items": self._job_items(pid, items, seg_id),
                "rows": [],
                "output_dir": rec.output_dir,
                "resume": {"skip": list(skip)},
                "batch": {"size": m.resources.max_batch or max(1, len(items))},
            },
        )
        live = _Live(pid, rid, run_dir, job_dir, m, rec.selection.seg_id)
        live.registered = any(
            s.producer is not None and s.producer.run_id == rid
            for s in self.workspace.get(pid).segmentations
        )
        n_todo = len([i for i in items if i.item_id not in set(skip)])

        async def driver(h: JobHandle) -> None:
            await self._drive(h, live, n_todo)

        async def on_finish(info: JobInfo) -> str | None:
            await self._finish(live, info)
            return rid

        spec = JobSpec(
            project_id=pid,
            kind="task",
            units=[],
            driver=driver,
            on_finish=on_finish,
            ref=rid,
            job_id=job_id,
            key=m.id,
            meta={"run_id": rid, "task_id": m.id},
        )
        async with self.locks(pid):
            rec = _read_run(run_dir)
            rec.job_id, rec.status, rec.error, rec.finished_at = job_id, "queued", None, None
            rec.attempts += 1
            _write_run(run_dir, rec)
        try:
            self.jobs.submit(spec)
        except Problem as exc:
            async with self.locks(pid):
                rec = _read_run(run_dir)
                rec.status, rec.error, rec.finished_at = "failed", exc.detail, utc_now()
                _write_run(run_dir, rec)
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        return TaskRunStarted(run_id=rid, job_id=job_id, status="queued")

    async def _set_status(self, live: _Live, status: TaskRunStatus) -> None:
        async with self.locks(live.pid):
            rec = _read_run(live.run_dir)
            if rec.status in TERMINAL_TASK_RUN or rec.status == status:
                return
            rec.status = status
            if status == "running":
                rec.started_at = rec.started_at or utc_now()
            _write_run(live.run_dir, rec)

    async def _drive(self, h: JobHandle, live: _Live, total: int) -> None:
        """Builtin: run the entry in a worker and tail its progress (TSK-07)."""
        h.set_total(total)
        tail = protocol.Tail(live.job_dir / protocol.PROGRESS)
        entry = live.manifest.runtime.entry
        assert entry is not None
        await self._set_status(live, "running")
        fut = asyncio.ensure_future(h.run_in_worker(run_entry, entry, str(live.job_dir)))
        stop_at: float | None = None
        try:
            while True:
                await self._on_lines(live, tail.read())
                h.set_done(live.done)
                if fut.done():
                    break
                if h.stopped:
                    if not live.cancel_sent:
                        protocol.request_cancel(live.job_dir)
                        live.cancel_sent = True
                        stop_at = time.monotonic()
                    elif stop_at is not None and time.monotonic() - stop_at > CANCEL_GRACE_S:
                        break
                await asyncio.sleep(POLL_S)
        finally:
            if fut.done() and not fut.cancelled():
                exit_code = int((fut.result() or {}).get("exit_code", 1))
                if exit_code != 0 and protocol.read_result(live.job_dir) is None:
                    raise RuntimeError(
                        f"task exited with code {exit_code}: "
                        + protocol.log_tail(live.job_dir)[-500:]
                    )
        await self._on_lines(live, tail.read())
        h.set_done(live.done)

    async def _on_lines(self, live: _Live, lines: Sequence[dict[str, Any]]) -> None:
        if not lines:
            return
        item_rows: list[dict[str, Any]] = []
        logs: list[dict[str, Any]] = []
        masks: list[dict[str, Any]] = []
        for line in lines:
            t = line.get("t")
            if t == "log":
                logs.append(
                    {
                        "at": utc_now(),
                        "level": line.get("level", "info"),
                        "message": str(line.get("message", ""))[:2000],
                    }
                )
            elif t == "item":
                iid = str(line.get("item_id"))
                status = line.get("status")
                if status not in ("ok", "failed", "skipped"):
                    continue
                row = {
                    "item_id": iid,
                    "status": status,
                    "message": str(line.get("message") or "")[:2000],
                }
                if status == "ok":
                    try:
                        masks += await self._item_outputs(live, iid, line.get("outputs") or [])
                    except ValueError as exc:
                        row = {"item_id": iid, "status": "failed", "message": f"output: {exc}"}
                live.done += 1
                item_rows.append(row)
        if masks and not live.registered:
            await self._register_set(live)
        async with self.locks(live.pid):
            if item_rows:
                append_jsonl(live.run_dir / ITEMS, item_rows)
            if logs:
                append_jsonl(live.run_dir / LOGS, logs)
            if masks:
                record_masks(self.workspace.project_dir(live.pid), live.rid, masks)

    async def _item_outputs(
        self, live: _Live, item_id: str, outputs: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Validate volume outputs (inside `output_dir`, ADR-0014) → `masks.jsonl` rows."""
        rows: list[dict[str, Any]] = []
        for o in outputs:
            kind = o.get("kind")
            if kind != "mask":
                continue
            if "masks" not in live.manifest.outputs:
                raise ValueError("task declared no mask outputs")
            rec = _read_run(live.run_dir)
            if rec.output_dir is None:
                raise ValueError("run has no output_dir")
            path = realpath(Path(str(o.get("path", ""))))
            out_dir = realpath(Path(rec.output_dir))
            if not is_within(path, out_dir) or not path.is_file():
                raise ValueError("mask is not a file inside the run's output_dir")
            root = self.workspace.derived_root(live.pid)
            rel = path.relative_to(realpath(Path(root.path))).as_posix()
            fp = await asyncio.to_thread(quick_fingerprint, path)
            ref = f"{root.alias}:{rel}"
            sha = o.get("sha256") or await asyncio.to_thread(_sha256, path)
            rows.append(
                {
                    "item_id": item_id,
                    "ref": ref,
                    "format": "nifti",
                    "fp": fp,
                    "labels": o.get("labels"),
                }
            )
            live.outputs.append(
                TaskRunOutput(
                    kind="mask",
                    item_id=item_id,
                    ref=ref,
                    seg_id=self._target_seg(live),
                    sha256=str(sha),
                )
            )
        return rows

    def _target_seg(self, live: _Live) -> str:
        rec_settings = _read_run(live.run_dir).settings
        s = rec_settings.get("seg_id")
        return s if isinstance(s, str) and s else default_seg_id(live.manifest.id, live.rid)

    async def _register_set(self, live: _Live) -> None:
        """TSK-09: the segmentation set is created at the first `ok` item (ADR-0015)."""
        m = live.manifest
        rec = _read_run(live.run_dir)
        cfg = self.workspace.get(live.pid)
        names: dict[str, str] = {}
        if m.labels and isinstance(m.labels.get("names"), dict):
            names = {str(k): str(v) for k, v in m.labels["names"].items()}
        mapping, unmatched, new_labels = _match_labels(names, cfg.label_map)
        if new_labels:
            patch = ProjectPatch(label_map=[*cfg.label_map, *new_labels])
            await self.workspace.update(live.pid, patch)
        seg = SegmentationSet(
            seg_id=self._target_seg(live),
            name=rec.name,
            kind="task",
            producer=SegProducer(
                task_id=m.id, version=m.version, run_id=live.rid, settings_hash=rec.settings_hash
            ),
            label_mapping=mapping,
            unmatched=unmatched,
            created_at=utc_now(),
        )
        await self.workspace.put_segmentation(live.pid, seg)
        live.registered = True
        self.bus.publish(live.pid, "project.updated", {"fields": ["segmentations"]})

    async def _finish(self, live: _Live, info: JobInfo) -> None:
        result = protocol.read_result(live.job_dir)
        async with self.locks(live.pid):
            rec = _read_run(live.run_dir)
            outcomes = {
                k: v
                for k, v in item_outcomes(live.run_dir).items()
                if k in set(rec.item_ids) or v["status"] == "skipped"
            }
            n = Counter(v["status"] for v in outcomes.values())
            rec.counts = TaskRunCounts(
                items=len(rec.item_ids), ok=n["ok"], failed=n["failed"], skipped=n["skipped"]
            )
            status: TaskRunStatus
            if info.status == "cancelled":
                status = "cancelled"
            elif info.status == "interrupted":
                status = "interrupted"
            elif info.status == "failed":
                status, rec.error = "failed", info.error
            elif result is None:
                status = "failed"
                rec.error = "task wrote no result.json: " + protocol.log_tail(live.job_dir)[-500:]
            else:
                raw = str(result.get("status"))
                status = raw if raw in TERMINAL_TASK_RUN else "failed"  # type: ignore[assignment]
                if n["failed"] and status == "completed":
                    status = "completed_with_errors"
                rec.error = result.get("error")
                versions = result.get("versions")
                if isinstance(versions, dict):
                    rec.versions = {str(k): str(v) for k, v in versions.items()}
            rec.status = status
            rec.started_at = rec.started_at or info.started_at
            rec.finished_at = utc_now()
            rec.outputs = [*rec.outputs, *live.outputs]
            if live.registered:
                seg = self._target_seg(live)
                if not any(o.kind == "segmentation_set" and o.seg_id == seg for o in rec.outputs):
                    rec.outputs.append(TaskRunOutput(kind="segmentation_set", seg_id=seg))
            _write_run(live.run_dir, rec)
            if live.outputs:
                append_jsonl(
                    self.workspace.project_dir(live.pid) / LEDGER,
                    [
                        {
                            "run_id": live.rid,
                            "task_id": rec.task.id,
                            "version": rec.task.version,
                            "settings_hash": rec.settings_hash,
                            "at": utc_now(),
                            "outputs": [{"ref": o.ref, "sha256": o.sha256} for o in live.outputs],
                        }
                    ],
                )
        if live.registered:
            await self._reindex_masks(live.pid)
        if live.manifest.runtime.type == "builtin":
            shutil.rmtree(live.job_dir, ignore_errors=True)  # disposable scratch (PRJ layout)

    async def _reindex_masks(self, pid: str) -> None:
        from app.ingest.service import IngestService

        ingest = IngestService(self.workspace, self.store, self.jobs, self.bus, self.locks)
        await ingest.reapply_segmentations(pid)

    async def _reconcile(self, pid: str, run_dir: Path) -> TaskRunRecord:
        """A non-terminal run whose job is unknown (server restart) → `interrupted` (BE-06)."""
        rec = _read_run(run_dir)
        if rec.status in TERMINAL_TASK_RUN or self._job(rec.job_id) is not None:
            return rec
        async with self.locks(pid):
            rec = _read_run(run_dir)
            if rec.status not in TERMINAL_TASK_RUN and self._job(rec.job_id) is None:
                rec.status, rec.finished_at = "interrupted", utc_now()
                _write_run(run_dir, rec)
        return rec

    async def get_run(self, pid: str, rid: str) -> TaskRunDetail:
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            return await rad.task_detail(pid, rid)
        run_dir = self._run_dir(pid, rid)
        rec = await self._reconcile(pid, run_dir)
        job = self._job(rec.job_id)
        progress = None
        if job is not None and job.status not in TERMINAL:
            progress = TaskRunProgress(done=job.done, total=job.total, eta_s=job.eta_s)
            if job.status == "waiting_for_runner" and rec.status == "queued":
                rec.status = "waiting_for_runner"
        return TaskRunDetail(**rec.model_dump(), progress=progress)

    async def list_runs(self, pid: str, task_id: str | None = None) -> list[TaskRunSummary]:
        out: list[TaskRunSummary] = []
        d = self._runs_dir(pid)
        if d.is_dir():
            for run_dir in d.iterdir():
                if not is_ulid(run_dir.name) or not (run_dir / RUN_JSON).is_file():
                    continue
                rec = await self._reconcile(pid, run_dir)
                out.append(TaskRunSummary.model_validate(rec.model_dump()))
        out += await self._radiomics().task_summaries(pid)
        if task_id is not None:
            out = [r for r in out if r.task.id == task_id]
        return sorted(out, key=lambda r: r.run_id, reverse=True)

    async def cancel(self, pid: str, rid: str) -> TaskRunDetail:
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            await rad.cancel(pid, rid)
            return await rad.task_detail(pid, rid)
        run_dir = self._run_dir(pid, rid)
        rec = await self._reconcile(pid, run_dir)
        job = self._job(rec.job_id)
        if rec.status not in TERMINAL_TASK_RUN and job is not None and rec.job_id is not None:
            if job.status not in TERMINAL:
                self.jobs.cancel(rec.job_id)
            with contextlib.suppress(TimeoutError):
                await self.jobs.wait(rec.job_id, CANCEL_GRACE_S + 5)
        return await self.get_run(pid, rid)

    async def resume(self, pid: str, rid: str) -> TaskRunStarted:
        """TSK-07: a new attempt that skips the items already `ok` (resume.skip)."""
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            d = await rad.resume(pid, rid)
            return TaskRunStarted(run_id=rid, job_id=d.job_id, status="queued")
        run_dir = self._run_dir(pid, rid)
        rec = await self._reconcile(pid, run_dir)
        if rec.status not in RESUMABLE_TASK_RUN:
            raise JobConflict(f"Run is {rec.status}; only interrupted, cancelled or failed resume")
        info = self.registry.get(rec.task.id)
        m = info.manifest
        if m.version != rec.task.version:
            raise JobConflict(
                f"Run used {m.id} {rec.task.version}; installed is {m.version}. Start a new run."
            )
        self._check_conflict(pid, m.id)
        idx = self.store.load(pid)
        items = [idx.by_id[i] for i in rec.item_ids if i in idx.by_id]
        ok = [k for k, v in item_outcomes(run_dir).items() if v["status"] == "ok"]
        return await self._submit(pid, run_dir, m, items, rec.selection.seg_id, skip=ok)

    # -- outputs (API-47) ---------------------------------------------------------------------

    def errors(self, pid: str, rid: str) -> list[TaskItemError]:
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            return rad.task_errors(pid, rid)
        run_dir = self._run_dir(pid, rid)
        return [
            TaskItemError(item_id=k, status=v["status"], message=v.get("message") or "")
            for k, v in sorted(item_outcomes(run_dir).items())
            if v["status"] != "ok"
        ]

    def outputs(self, pid: str, rid: str) -> list[TaskRunOutput]:
        rad = self._radiomics()
        if rad.has_run(pid, rid):
            return rad.task_outputs(pid, rid)
        return _read_run(self._run_dir(pid, rid)).outputs

    # -- radiomics (RAD-13) ---------------------------------------------------------------------

    def _radiomics(self) -> RadiomicsTask:
        return RadiomicsTask(self.workspace, self.store, self.jobs, self.bus, self.locks)


def _match_labels(
    names: dict[str, str], label_map: Sequence[LabelEntry]
) -> tuple[dict[str, int], list[int], list[LabelEntry]]:
    """ADR-0015 §4: match set labels by name; unmatched → new `label_{value}` entries."""
    by_name = {e.name.lower(): e.value for e in label_map}
    used = {e.value for e in label_map}
    mapping: dict[str, int] = {}
    unmatched: list[int] = []
    new: list[LabelEntry] = []
    for key, name in sorted(names.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        if not key.isdigit():
            continue
        target = by_name.get(name.lower())
        if target is None:
            value = int(key)
            target = value if value not in used else max(used | {0}) + 1
            used.add(target)
            unmatched.append(int(key))
            new.append(
                LabelEntry(
                    value=target,
                    name=name or auto_label_name(target),
                    color=AUTO_LABEL_COLORS[len(new) % len(AUTO_LABEL_COLORS)],
                    opacity=0.2,
                )
            )
        mapping[key] = target
    return mapping, unmatched, new
