"""Ingest service: preview, commit, index job, queries (IMP-01..08/11, API-11..14, 20..22).

Stateless: routers build one per request from the app context. Only this (API) process
writes project files, always under the project lock (BE-05); workers only read (BE-03).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from app.core.errors import JobConflict, NotFound, Problem, ValidationProblem
from app.core.fsio import append_jsonl, atomic_write_bytes, atomic_write_json, read_json, read_jsonl
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.core.paths import validate_alias
from app.events.bus import EventBus
from app.ingest import indexer, preview
from app.ingest.cases import build_cases
from app.ingest.indexer import ItemProbeResult
from app.ingest.models import CaseSummary, IndexState, IndexStatus, Item, QcWarning
from app.ingest.normalize import build_drafts
from app.ingest.parsers import FILE_NAMES, FileKind, ParsedInputs, parse_inputs
from app.ingest.schemas import (
    CaseDetail,
    CommitResult,
    ImportPreview,
    ImportRecord,
    ItemAdvanced,
    ItemDetail,
    ScanGroup,
)
from app.ingest.store import IndexStore
from app.ingest.validator import finalize, probes_for
from app.jobs.manager import JobManager
from app.jobs.types import JobInfo, JobSpec, WorkUnit
from app.projects.models import PathRoot
from app.projects.service import Workspace

log = logging.getLogger("app.ingest")

IndexHook = Callable[[str], Awaitable[None]]
PREVIEWS = Path("cache") / "previews"
SOURCES = "sources"
IMPORTS = "imports.jsonl"


class IngestService:
    def __init__(
        self,
        workspace: Workspace,
        store: IndexStore,
        jobs: JobManager,
        bus: EventBus,
        locks: ProjectLocks,
        after_index: Sequence[IndexHook] = (),
    ) -> None:
        self.workspace = workspace
        self.store = store
        self.jobs = jobs
        self.bus = bus
        self.locks = locks
        self.after_index = after_index

    # -- import (API-11/12/13) ------------------------------------------------------------

    async def preview(
        self,
        project_id: str,
        root: str,
        *,
        alias: str = "DATA",
        uploads: dict[FileKind, tuple[str, bytes]] | None = None,
    ) -> ImportPreview:
        """IMP-02/03. `uploads=None` auto-detects the input files under `root`."""
        pdir = self.workspace.project_dir(project_id)
        validate_alias(alias)
        if not os.path.isabs(root):
            raise ValidationProblem(
                "Data root must be an absolute path", errors=[{"loc": ["root"], "msg": "relative"}]
            )
        real = self.workspace.guard.check(Path(root))
        if not real.is_dir():
            raise ValidationProblem(
                "Data root is not a directory", errors=[{"loc": ["root"], "msg": "not a directory"}]
            )
        if uploads is None:
            blobs = preview.detect_inputs(real)
        else:
            blobs = {
                k: preview.InputBlob(k, name or FILE_NAMES[k], "uploaded", data)
                for k, (name, data) in uploads.items()
            }
        if "metadata" not in blobs:
            raise ValidationProblem(
                "metadata.jsonl not found",
                errors=[{"loc": ["metadata"], "msg": "required input file missing"}],
            )
        parsed = parse_inputs({k: b.data for k, b in blobs.items()})
        pv = ImportPreview(
            preview_id=new_ulid(),
            root=os.path.normpath(root),
            alias=alias,
            files=preview.input_files(blobs, parsed),
            counts=preview.counts(parsed),
            errors=preview.errors(parsed),
            n_errors=len(parsed.errors),
            field_mapping=preview.field_mapping(parsed),
        )
        d = pdir / PREVIEWS / pv.preview_id
        async with self.locks(project_id):
            for b in blobs.values():
                atomic_write_bytes(d / FILE_NAMES[b.kind], b.data)
            atomic_write_json(d / "preview.json", pv.model_dump(mode="json"))
        return pv

    def _load_preview(
        self, pdir: Path, preview_id: str
    ) -> tuple[ImportPreview, dict[FileKind, bytes]]:
        d = pdir / PREVIEWS / preview_id
        if not is_ulid(preview_id) or not (d / "preview.json").is_file():
            raise NotFound(f"Preview {preview_id!r} not found")
        pv = ImportPreview.model_validate(read_json(d / "preview.json"))
        data: dict[FileKind, bytes] = {}
        for f in pv.files:
            data[f.kind] = (d / FILE_NAMES[f.kind]).read_bytes()
        return pv, data

    async def commit(self, project_id: str, preview_id: str) -> CommitResult:
        """IMP-04/05/06: snapshot inputs, record the import, set the root, start indexing."""
        pdir = self.workspace.project_dir(project_id)
        pv, data = self._load_preview(pdir, preview_id)
        self._check_no_index_job(project_id)
        import_id = new_ulid()
        record = ImportRecord(
            import_id=import_id,
            at=utc_now(),
            alias=pv.alias,
            root=pv.root,
            files=pv.files,
            counts=pv.counts,
        )
        async with self.locks(project_id):
            for kind, blob in data.items():
                atomic_write_bytes(pdir / SOURCES / import_id / FILE_NAMES[kind], blob)
            append_jsonl(pdir / SOURCES / IMPORTS, [record.model_dump(mode="json")])
        await self.workspace.set_root(project_id, PathRoot(alias=pv.alias, path=pv.root))
        job_id = await self._start_index(project_id, import_id, pv.alias, parse_inputs(data))
        return CommitResult(job_id=job_id, import_id=import_id)

    def _check_no_index_job(self, project_id: str) -> None:
        cur = self.jobs.active(project_id, "index")
        if cur is not None:
            raise JobConflict(f"An index job is already active: {cur.job_id}")

    async def _start_index(
        self, project_id: str, import_id: str, alias: str, parsed: ParsedInputs
    ) -> str:
        drafts = build_drafts(parsed, self.workspace.resolver(project_id), alias)
        units = [WorkUnit(indexer.probe_batch, (b,)) for b in indexer.batches(probes_for(drafts))]
        results: dict[str, ItemProbeResult] = {}

        async def on_result(batch: Any) -> None:
            for r in batch:
                results[r.item_id] = r

        async def on_finish(info: JobInfo) -> str | None:
            ok = info.status == "succeeded"
            n_items = n_warnings = 0
            async with self.locks(project_id):
                st = self.store.status(project_id)
                if ok:
                    previous = self.store.load(project_id).by_id
                    items, warnings = finalize(drafts, results, previous, import_id)
                    self.store.replace(project_id, items, build_cases(items, warnings), warnings)
                    n_items, n_warnings = len(items), len(warnings)
                    st = IndexStatus(
                        state="ready",
                        import_id=import_id,
                        job_id=info.job_id,
                        started_at=st.started_at,
                        finished_at=utc_now(),
                        n_items=n_items,
                        n_warnings=n_warnings,
                    )
                else:
                    state: IndexState = "failed"
                    if info.status in ("cancelled", "interrupted"):
                        state = "cancelled" if info.status == "cancelled" else "interrupted"
                    st = st.model_copy(
                        update={"state": state, "finished_at": utc_now(), "error": info.error}
                    )
                self.store.write_status(project_id, st)
            if not ok:
                return import_id
            self.bus.publish(
                project_id,
                "index.rebuilt",
                {"import_id": import_id, "n_items": n_items, "n_warnings": n_warnings},
            )
            for hook in self.after_index:
                try:
                    await hook(project_id)
                except Exception:
                    log.exception("after_index hook failed", extra={"project_id": project_id})
            return import_id

        job_id = new_ulid()
        async with self.locks(project_id):
            before = self.store.status(project_id)
            self.store.write_status(
                project_id,
                IndexStatus(
                    state="running", import_id=import_id, job_id=job_id, started_at=utc_now()
                ),
            )
        spec = JobSpec(
            project_id=project_id,
            kind="index",
            units=units,
            on_result=on_result,
            on_finish=on_finish,
            ref=import_id,
            job_id=job_id,
            meta={"import_id": import_id},
        )
        try:
            self.jobs.submit(spec)
        except Problem:
            async with self.locks(project_id):
                self.store.write_status(project_id, before)
            raise
        return job_id

    def imports(self, project_id: str) -> list[ImportRecord]:
        """API-13: import history, newest first."""
        path = self.workspace.project_dir(project_id) / SOURCES / IMPORTS
        return [ImportRecord.model_validate(r) for r in reversed(read_jsonl(path))]

    async def index_status(self, project_id: str) -> IndexStatus:
        """Persisted index state; a stale `running` becomes `interrupted` (BE-06)."""
        st = self.store.status(project_id)
        if st.state == "running" and self.jobs.active(project_id, "index") is None:
            async with self.locks(project_id):
                st = self.store.status(project_id)
                if st.state == "running" and self.jobs.active(project_id, "index") is None:
                    st = st.model_copy(update={"state": "interrupted", "finished_at": utc_now()})
                    self.store.write_status(project_id, st)
        return st

    # -- queries (API-14, 20..22) ---------------------------------------------------------

    def warnings(
        self,
        project_id: str,
        *,
        code: str | None = None,
        severity: str | None = None,
        case_id: str | None = None,
        item_id: str | None = None,
    ) -> list[QcWarning]:
        return [
            w
            for w in self.store.load(project_id).warnings
            if (code is None or w.code == code)
            and (severity is None or w.severity == severity)
            and (case_id is None or w.case_id == case_id)
            and (item_id is None or w.item_id == item_id)
        ]

    def cases(
        self,
        project_id: str,
        *,
        q: str | None = None,
        group: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        warning: str | None = None,
        has_voi: bool | None = None,
        sort: str = "case_id",
    ) -> list[CaseSummary]:
        """API-20. Cases whose items are all `excluded_upstream` show only for that status."""
        idx = self.store.load(project_id)
        statuses: dict[str, set[str]] = {}
        for it in idx.items:
            statuses.setdefault(it.case_id, set()).add(it.status)
        warned: dict[str, set[str]] = {}
        for w in idx.warnings:
            if w.case_id:
                warned.setdefault(w.case_id, set()).add(w.code)
        needle = (q or "").strip().lower()

        def keep(c: CaseSummary) -> bool:
            st = statuses.get(c.case_id, set())
            if status is None:
                if not st - {"excluded_upstream"}:
                    return False
            elif status not in st:
                return False
            if needle and needle not in f"{c.case_id}\n{c.patient_id or ''}".lower():
                return False
            if group is not None and c.group != group:
                return False
            if phase is not None and phase not in c.phases:
                return False
            if warning is not None and warning not in warned.get(c.case_id, set()):
                return False
            return has_voi is None or (c.has_voi_L or c.has_voi_R) == has_voi

        out = [c for c in idx.cases if keep(c)]
        if sort in ("n_warnings", "-n_warnings"):
            out.sort(key=lambda c: c.case_id)
            out.sort(key=lambda c: c.n_warnings, reverse=sort.startswith("-"))
        elif sort == "-case_id":
            out.sort(key=lambda c: c.case_id, reverse=True)
        else:
            out.sort(key=lambda c: c.case_id)
        return out

    def case_detail(self, project_id: str, case_id: str) -> CaseDetail:
        """API-21: case + scans → items tree + warnings."""
        idx = self.store.load(project_id)
        case = self.store.get_case(project_id, case_id)
        scans: dict[str, list[Item]] = {}
        for it in idx.items:
            if it.case_id == case_id:
                scans.setdefault(it.scan_idx, []).append(it)
        groups = []
        for scan_idx in sorted(scans):
            its = sorted(scans[scan_idx], key=lambda i: (i.scope != "complete", i.side))
            groups.append(ScanGroup(scan_idx=scan_idx, phase=its[0].phase, items=its))
        warnings = [w for w in idx.warnings if w.case_id == case_id]
        return CaseDetail(case=case, scans=groups, warnings=warnings)

    def item_detail(self, project_id: str, item_id: str) -> ItemDetail:
        """API-22: item + absolute paths under `advanced` + its warnings."""
        item = self.store.get_item(project_id, item_id)
        resolver = self.workspace.resolver(project_id)

        def absolute(ref: str | None) -> str | None:
            if ref is None:
                return None
            try:
                return str(resolver.resolve(ref))
            except Problem:
                return None

        warnings = [w for w in self.store.load(project_id).warnings if w.item_id == item_id]
        return ItemDetail(
            **item.model_dump(),
            advanced=ItemAdvanced(
                image_path=absolute(item.image.ref if item.image else None),
                mask_path=absolute(item.mask.ref if item.mask else None),
            ),
            warnings=warnings,
        )
