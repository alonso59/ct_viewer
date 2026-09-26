"""Workspace tasks (TSK-13, ADR-0021 §2; API-62): `scope: workspace` tasks run without a project.

Inputs come from a source path inside ALLOWED_DATA_ROOTS; outputs go to a new, write-once folder
`{first ALLOWED_DERIVED_ROOTS}/_datasets/{name}/` (a `-1`, `-2` … suffix when the name is taken);
run records live in `WORKSPACE_ROOT/plugins/{plugin}/runs/{run_id}/run.json`. The dataset holds
`metadata.jsonl` (the converter artifact, DCM-13), `nifti/`, `sidecars/`, `annotations.jsonl`
(analyzer layers, ANZ-04) and `dataset.json`; it opens in Open mode and imports like any root
(SRC-16), and an import registers its annotations as an analyzer run of the project.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, Field

from app.config import Settings
from app.core.errors import DerivedRootRequired, JobConflict, NotFound, ValidationProblem
from app.core.fsio import atomic_write_json, iter_jsonl, read_json, write_jsonl_atomic
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.paths import PathGuard
from app.jobs.manager import JobManager
from app.jobs.types import JobHandle, JobInfo, JobSpec
from app.tasks import dry_run, protocol
from app.tasks.builtin import run_entry
from app.tasks.models import (
    TaskEstimate,
    TaskManifest,
    TaskRef,
    TaskRunRecord,
    TaskRunStarted,
    TaskRunStatus,
    TaskSelection,
)
from app.tasks.registry import Registry
from app.tasks.schema import normalize, settings_hash

WORKSPACE_JOBS: Final = "_workspace"  # JobManager project key of workspace task jobs
DATASETS: Final = "_datasets"
DATASET_JSON: Final = "dataset.json"
ANNOTATIONS: Final = "annotations.jsonl"
POLL_S: Final = 0.2
_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class WorkspaceRunRequest(BaseModel):
    task_id: str
    settings: dict[str, Any] = Field(default_factory=dict)
    selection: TaskSelection
    name: str | None = Field(default=None, max_length=120)


class WorkspaceEstimateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    selection: TaskSelection


class WorkspaceRun(BaseModel):
    """`plugins/{plugin}/runs/{run_id}/run.json` and the API-62 payload."""

    run_id: str
    task: TaskRef
    plugin: str
    name: str
    status: TaskRunStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    source: str
    dataset_dir: str
    settings: dict[str, Any]
    settings_hash: str
    counts: dict[str, int] = Field(default_factory=dict)
    progress: dict[str, int] = Field(default_factory=dict)  # {done, total}
    error: str | None = None
    job_id: str | None = None


def default_dataset_name(today: date | None = None) -> str:
    """`dataset-{YYYY-MM-DD}`: the name when the user gives none (AUD-A5-16)."""
    return f"dataset-{(today or date.today()).isoformat()}"


def dataset_name(raw: str) -> str:
    return _NAME_RE.sub("-", raw).strip("-.")[:80] or "dataset"


class WorkspaceTasks:
    def __init__(
        self, settings: Settings, registry: Registry, guard: PathGuard, jobs: JobManager,
        owners: dict[str, str],
    ) -> None:  # fmt: skip
        self.settings = settings
        self.registry = registry
        self.guard = guard
        self.jobs = jobs
        self.owners = owners

    # -- helpers ------------------------------------------------------------------------------

    def _manifest(self, task_id: str) -> TaskManifest:
        info = self.registry.get(task_id)
        m = info.manifest
        if m.scope != "workspace":
            raise ValidationProblem(
                f"{m.id} needs a project (scope: project)",
                errors=[{"loc": ["body", "task_id"], "msg": "not a workspace task"}],
            )
        if not info.available or m.runtime.type != "builtin" or m.input != "source":
            raise ValidationProblem(f"{m.id} cannot run as a workspace task")
        return m

    def _settings(self, m: TaskManifest, raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
        norm, issues = normalize(m.settings_schema, m.defaults, raw)
        errors = [
            {"loc": ["body", "settings", *i.loc], "msg": i.msg, "type": i.rule}
            for i in issues
            if i.severity == "error"
        ]
        if errors:
            raise ValidationProblem(f"Invalid settings for {m.id}", errors=errors)
        return norm, settings_hash(m.id, m.version, norm)

    def _source(self, sel: TaskSelection) -> Path:
        if not sel.source:
            raise ValidationProblem(
                "Choose a source folder or file",
                errors=[{"loc": ["body", "selection", "source"], "msg": "required"}],
            )
        path = self.guard.check(Path(sel.source))
        if not path.exists():
            raise ValidationProblem(
                f"{sel.source} does not exist",
                errors=[{"loc": ["body", "selection", "source"], "msg": "missing"}],
            )
        return path

    def _derived(self) -> Path:
        roots = self.settings.derived_roots
        if not roots:
            raise DerivedRootRequired(
                "ALLOWED_DERIVED_ROOTS is empty: the server has no writable folder for datasets "
                "(OPS-11)",
                actions=["configure:ALLOWED_DERIVED_ROOTS"],
            )
        return roots[0]

    def _runs_dir(self, plugin: str) -> Path:
        return self.settings.workspace_root / "plugins" / plugin / "runs"

    def _plugin(self, m: TaskManifest) -> str:
        return self.owners.get(m.id, m.id.split(".")[0])

    def _read(self, run_dir: Path) -> WorkspaceRun:
        return WorkspaceRun.model_validate(read_json(run_dir / "run.json"))

    def _write(self, run_dir: Path, run: WorkspaceRun) -> None:
        atomic_write_json(run_dir / "run.json", run.model_dump(mode="json"))

    def _find(self, rid: str) -> Path:
        if is_ulid(rid):
            for d in (self.settings.workspace_root / "plugins").glob(f"*/runs/{rid}"):
                if (d / "run.json").is_file():
                    return d
        raise NotFound(f"Workspace task run {rid!r} not found")

    def _spec(self, m: TaskManifest, settings: dict[str, Any], source: Path, out: Path) -> Any:
        return {
            "task": {"id": m.id, "version": m.version},
            "settings": settings,
            "context": {
                "phase_vocabulary": [],  # no project: open vocabulary (ANZ-05)
                "packs": [],
                "target_profile": settings.get("target_profile") or "generic",
            },
            "items": [],
            "rows": [],
            "output_dir": str(out),
            "dataset_dir": str(out),
            "dataset_ref": "DATA:",
            "workspace": True,  # rows relative to the dataset root (SRC-16)
            "source": {"path": str(source)},
            "project_id": "",
        }

    # -- API-62 -------------------------------------------------------------------------------

    async def estimate(self, task_id: str, req: WorkspaceEstimateRequest) -> TaskEstimate:
        """The dry run (DCM-06) without a project: counts and storage, nothing written."""
        m = self._manifest(task_id)
        settings, _ = self._settings(m, req.settings)
        source = self._source(req.selection)
        await dry_run.require_dicom(m.id, source)
        job_dir = self.settings.workspace_root / ".scratch" / "estimates" / new_ulid()
        spec = self._spec(m, settings, source, job_dir / "out")
        protocol.write_job(
            job_dir, {**spec, "job_id": job_dir.name, "run_id": "estimate", "mode": "estimate"}
        )
        t0 = time.monotonic()
        try:
            assert m.runtime.entry is not None
            await self.jobs.run_in_worker(run_entry, m.runtime.entry, str(job_dir))
            result = protocol.read_result(job_dir) or {}
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
        return dry_run.estimate_of(result, time.monotonic() - t0, source)

    async def start(self, req: WorkspaceRunRequest) -> TaskRunStarted:
        m = self._manifest(req.task_id)
        settings, shash = self._settings(m, req.settings)
        source = self._source(req.selection)
        await dry_run.require_dicom(m.id, source)  # never an empty dataset (AUD-A2-07)
        if self.jobs.active(WORKSPACE_JOBS, "task", m.id) is not None:
            raise JobConflict(f"A {m.id} workspace run is already active")
        base = self._derived() / DATASETS
        # never the source folder's name: DICOM folders are often patient names (NFR-17)
        stem = dataset_name(req.name or default_dataset_name())
        out, n = base / stem, 0
        while out.exists():  # write-once: never reuse a dataset folder
            n += 1
            out = base / f"{stem}-{n}"
        out.mkdir(parents=True)
        info = self.registry.get(m.id)
        plugin = self._plugin(m)
        rid, job_id = new_ulid(), new_ulid()
        run_dir = self._runs_dir(plugin) / rid
        run_dir.mkdir(parents=True)
        run = WorkspaceRun(
            run_id=rid,
            task=TaskRef(id=m.id, version=m.version, manifest_hash=info.manifest_hash),
            plugin=plugin,
            name=out.name,
            status="queued",
            created_at=utc_now(),
            source=str(source),
            dataset_dir=str(out),
            settings=settings,
            settings_hash=shash,
            job_id=job_id,
        )
        self._write(run_dir, run)
        job_dir = self.settings.workspace_root / ".scratch" / "jobs" / job_id
        protocol.write_job(
            job_dir,
            {**self._spec(m, settings, source, out), "job_id": job_id, "run_id": rid,
             "mode": "run", "resume": {"skip": []}, "batch": {"size": 1}},
        )  # fmt: skip

        async def driver(h: JobHandle) -> None:
            await self._drive(h, m, run_dir, job_dir)

        async def on_finish(info: JobInfo) -> str | None:
            self._finish(run_dir, job_dir, info)
            return rid

        self.jobs.submit(
            JobSpec(
                project_id=WORKSPACE_JOBS, kind="task", units=[], driver=driver,
                on_finish=on_finish, ref=rid, job_id=job_id, key=m.id,
                meta={"run_id": rid, "task_id": m.id},
            )
        )  # fmt: skip
        return TaskRunStarted(run_id=rid, job_id=job_id, status="queued")

    async def _drive(self, h: JobHandle, m: TaskManifest, run_dir: Path, job_dir: Path) -> None:
        run = self._read(run_dir)
        run.status, run.started_at = "running", utc_now()
        self._write(run_dir, run)
        tail = protocol.Tail(job_dir / protocol.PROGRESS)
        assert m.runtime.entry is not None
        fut = asyncio.ensure_future(h.run_in_worker(run_entry, m.runtime.entry, str(job_dir)))
        done = total = 0
        cancel_sent = False
        while True:
            for line in tail.read():
                if line.get("t") == "total":
                    total = int(line.get("n") or 0)
                    h.set_total(total)
                elif line.get("t") == "item":
                    done += 1
                    h.set_done(done)
            run = self._read(run_dir)
            run.progress = {"done": done, "total": total}
            self._write(run_dir, run)
            if fut.done():
                break
            if h.stopped and not cancel_sent:
                protocol.request_cancel(job_dir)
                cancel_sent = True
            await asyncio.sleep(POLL_S)
        res = fut.result() or {}
        if int(res.get("exit_code", 1)) != 0 and protocol.read_result(job_dir) is None:
            raise RuntimeError(protocol.log_tail(job_dir)[-500:] or "task failed")

    def _finish(self, run_dir: Path, job_dir: Path, info: JobInfo) -> None:
        run = self._read(run_dir)
        result = protocol.read_result(job_dir) or {}
        status: Literal["completed", "failed", "cancelled"]
        if info.status == "cancelled":
            status = "cancelled"
        elif info.status == "failed" or result.get("status") == "failed":
            status = "failed"
        else:
            status = "completed"
        counts = result.get("estimate") if isinstance(result.get("estimate"), dict) else {}
        run.counts = {k: int(v) for k, v in (counts or {}).items() if isinstance(v, int)}
        run.error = info.error or (str(result["error"]) if result.get("error") else None)
        if status == "completed" and not run.counts.get("series"):  # AUD-A2-07
            status, run.error = "failed", run.error or "No DICOM series found in the source"
        run.status, run.finished_at = status, utc_now()
        self._write(run_dir, run)
        shutil.rmtree(job_dir, ignore_errors=True)

    def list(self) -> list[WorkspaceRun]:
        out = [self._read(d.parent) for d in (self.settings.workspace_root / "plugins").glob(
            "*/runs/*/run.json")]  # fmt: skip
        return sorted(out, key=lambda r: r.created_at, reverse=True)

    def get(self, rid: str) -> WorkspaceRun:
        return self._read(self._find(rid))

    def cancel(self, rid: str) -> WorkspaceRun:
        run = self.get(rid)
        if run.job_id and run.status in ("queued", "running"):
            self.jobs.cancel(run.job_id)
        return self.get(rid)


def dataset_annotations(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """A workspace dataset's manifest and analyzer annotations, if `root` is one (SRC-16)."""
    if not (root / DATASET_JSON).is_file():
        return None
    try:
        meta = read_json(root / DATASET_JSON)
    except (OSError, ValueError):
        return None
    rows = [r for r in iter_jsonl(root / ANNOTATIONS) if r.get("item_id") and r.get("field")]
    return meta, rows


def write_imported_run(run_dir: Path, meta: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """The dataset's annotations as a completed task run of the project (ANZ-04 layers)."""
    task = meta.get("task") or {}
    now = utc_now()
    rec = TaskRunRecord(
        run_id=run_dir.name,
        task=TaskRef(id=str(task.get("id") or "dicom.convert"),
                     version=str(task.get("version") or ""), manifest_hash=""),
        name=f"Dataset {meta.get('name', '')}".strip(),
        status="completed",
        created_at=now,
        finished_at=now,
        runtime="builtin",
        settings=meta.get("settings") or {},
        settings_hash="",
        selection=TaskSelection(source=str(meta.get("source") or "")),
    )  # fmt: skip
    run_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl_atomic(run_dir / ANNOTATIONS, rows)
    atomic_write_json(run_dir / "run.json", rec.model_dump(mode="json"))
