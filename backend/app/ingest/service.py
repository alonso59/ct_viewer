"""Ingest service: preview, commit, index job, queries.

Stateless: routers build one per request from the app context. Only this (API) process
writes project files, always under the project lock; workers only read.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.core.errors import JobConflict, NotFound, Problem, UnsupportedFormat, ValidationProblem
from app.core.fsio import (
    append_jsonl,
    atomic_write_bytes,
    atomic_write_json,
    iter_jsonl,
    read_json,
    read_jsonl,
)
from app.core.ids import is_ulid, new_ulid, utc_now
from app.core.locks import ProjectLocks
from app.core.paths import PathResolver, validate_alias
from app.curation.state import CaseReview, case_reviews
from app.events.bus import EventBus
from app.ingest import indexer, preview, sidecars
from app.ingest.cases import build_cases
from app.ingest.counting import split_items
from app.ingest.indexer import ItemProbeResult
from app.ingest.models import CaseSummary, IndexState, IndexStatus, Item, QcWarning
from app.ingest.normalize import (
    Annotation,
    Annotations,
    Draft,
    PhaseRules,
    build_drafts,
    merge_sources,
)
from app.ingest.parsers import FILE_NAMES, FileKind, ParsedInputs, parse_inputs
from app.ingest.schemas import (
    Adapter,
    CaseDetail,
    CommitResult,
    ImportPreview,
    ImportRecord,
    ItemAdvanced,
    ItemDetail,
    ScanGroup,
    SourceInfo,
)
from app.ingest.segsets import apply_registered_masks
from app.ingest.store import IndexStore
from app.ingest.validator import finalize, probes_for
from app.jobs.manager import JobManager
from app.jobs.types import JobInfo, JobSpec, WorkUnit
from app.projects.models import LabelEntry, PathRoot, ProjectPatch
from app.projects.presets import AUTO_LABEL_COLORS, auto_label_name
from app.projects.service import Workspace
from app.sources import detect, formats, identity, nifti_files
from app.sources.identity import IdentityRegistry
from app.sources.nifti_files import NiftiOptions
from app.variables.service import VariableService

log = logging.getLogger("app.ingest")

IndexHook = Callable[[str], Awaitable[None]]
PREVIEWS = Path("cache") / "previews"
SOURCES = "sources"
IMPORTS = "imports.jsonl"
ANNOTATIONS = "annotations.jsonl"
SAMPLE_NAMES = 200
SIDECAR_BATCH = 200  # files per worker unit


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

    async def preview(
        self,
        project_id: str,
        root: str,
        *,
        alias: str = "DATA",
        uploads: dict[FileKind, tuple[str, bytes]] | None = None,
        adapter: Adapter | None = None,
        options: dict[str, Any] | None = None,
        add: bool = False,
        source_key: str | None = None,
    ) -> ImportPreview:
        """`uploads=None` auto-detects the input files under `root`.

        `root` may be a single NIfTI file: the parent folder becomes the root and the import
        keeps an include list.
        """
        pdir = self.workspace.project_dir(project_id)
        validate_alias(alias)
        options = dict(options or {})
        if not os.path.isabs(root):
            raise ValidationProblem(
                "Data root must be an absolute path", errors=[{"loc": ["root"], "msg": "relative"}]
            )
        existing = next(
            (r for r in self.workspace.get(project_id).path_roots if r.alias == alias), None
        )
        guard = (
            self.workspace.project_derived_guard(project_id)
            if existing is not None and existing.role == "derived"
            else self.workspace.guard
        )
        real = guard.check(Path(root))
        if real.is_file() and uploads is None:
            kind = formats.classify(real)
            if kind != "nifti" or adapter == "metadata-v1":
                raise UnsupportedFormat(
                    f"{real.name} is not a NIfTI file; single files import only as NIfTI",
                    actions=["open"] if kind else ["choose_another_path"],
                )
            adapter = "nifti-files"
            options["include"] = [real.name]
            real = real.parent
            root = str(Path(root).parent)
        if not real.is_dir():
            raise ValidationProblem(
                "Data root is not a directory", errors=[{"loc": ["root"], "msg": "not a directory"}]
            )
        adapter = adapter or "metadata-v1"
        if adapter == "metadata-v1":
            # the only metadata-v1 option; reconstructed sidecars go to the derived root
            options = {sidecars.OPTION: True} if options.get(sidecars.OPTION) else {}
            if options:
                self.workspace.derived_root(project_id)  # raises derived-root-required
        extra: dict[str, Any] = {}
        if add:  # next to the other sources, under its own alias when the root differs
            alias = self._free_alias(project_id, alias, os.path.normpath(root))
            include = ",".join(options.get("include") or [])
            source_key = f"add:{alias}:{include}"
        draft_registry: IdentityRegistry | None = None
        if adapter == "nifti-files":
            if uploads is not None:
                raise ValidationProblem("nifti-files takes no uploaded files")
            try:
                opts = NiftiOptions.model_validate(options)
            except PydanticValidationError as exc:
                raise ValidationProblem(
                    "Invalid nifti-files options",
                    errors=[
                        {"loc": ["body", "options", *e["loc"]], "msg": e["msg"]}
                        for e in exc.errors()
                    ],
                ) from None
            reg = identity.load(pdir / SOURCES)
            plan = await asyncio.to_thread(nifti_files.plan, real, opts, reg)
            if not plan.rows:
                raise UnsupportedFormat(
                    "No NIfTI image under the root (masks found by convention are not items)",
                    actions=["choose_another_path"],
                )
            if plan.collisions:
                folder = any("/" in r["relative_path"] for r in plan.rows)
                use = folder and opts.pattern != nifti_files.FOLDER_PATTERN
                raise ValidationProblem(
                    f"{len(plan.collisions)} files give a case and scan already used by another "
                    f"file, so they would collapse into one item. First: {plan.collisions[0]}",
                    errors=[
                        {"loc": ["body", "options", "pattern"], "msg": c}
                        for c in plan.collisions[:SAMPLE_NAMES]
                    ],
                    actions=[f"use_pattern:{nifti_files.FOLDER_PATTERN}"] if use else [],
                )
            data = await asyncio.to_thread(
                lambda: "".join(
                    json.dumps(r, ensure_ascii=False) + "\n" for r in plan.rows
                ).encode()
            )
            blobs: dict[FileKind, preview.InputBlob] = {
                "metadata": preview.InputBlob("metadata", FILE_NAMES["metadata"], "generated", data)
            }
            options = opts.model_dump(mode="json")
            draft_registry = plan.registry
            extra = {
                "sample": plan.sample,
                "unmatched": plan.unmatched[:SAMPLE_NAMES],
                "orphan_masks": plan.orphan_masks[:SAMPLE_NAMES],
                "ignored": plan.ignored,
            }
        elif uploads is None:
            blobs = await asyncio.to_thread(preview.detect_inputs, real)
        else:
            blobs = {
                k: preview.InputBlob(k, name or FILE_NAMES[k], "uploaded", data)
                for k, (name, data) in uploads.items()
            }
        if "metadata" not in blobs:
            detail, actions = await asyncio.to_thread(detect.suggest_for, real)
            raise ValidationProblem(
                detail,
                errors=[{"loc": ["metadata"], "msg": "required input file missing"}],
                actions=actions,
            )
        project_resolver = self.workspace.resolver(project_id)
        resolver = PathResolver(
            {alias: real},
            guard,
            roles={alias: project_resolver.role(alias)},
            derived_guard=project_resolver.derived_guard,
            source_exclusions=project_resolver.source_exclusions,
        )
        parsed = await asyncio.to_thread(
            parse_inputs, {k: b.data for k, b in blobs.items()}, resolver=resolver, alias=alias
        )
        pv = ImportPreview(
            preview_id=new_ulid(),
            root=os.path.normpath(root),
            alias=alias,
            files=preview.input_files(blobs, parsed),
            counts=preview.counts(parsed),
            errors=preview.errors(parsed),
            n_errors=len(parsed.errors),
            field_mapping=preview.field_mapping(parsed),
            adapter=adapter,
            options=options,
            source_key=source_key,
            **extra,
        )
        d = pdir / PREVIEWS / pv.preview_id
        async with self.locks(project_id):
            for b in blobs.values():
                atomic_write_bytes(d / FILE_NAMES[b.kind], b.data)
            if draft_registry is not None:
                identity.save(d, draft_registry)
            atomic_write_json(d / "preview.json", pv.model_dump(mode="json"))
        return pv

    def preview_of(self, project_id: str, preview_id: str) -> ImportPreview:
        d = self.workspace.project_dir(project_id) / PREVIEWS / preview_id
        if not is_ulid(preview_id):
            raise NotFound("Import preview not found; prepare it again")
        try:
            pv = ImportPreview.model_validate(read_json(d / "preview.json"))
            if any(not (d / FILE_NAMES[f.kind]).is_file() for f in pv.files):
                raise NotFound("Import preview inputs are unavailable; prepare it again")
            return pv
        except (OSError, ValueError):
            raise NotFound("Import preview is unavailable; prepare it again") from None

    async def commit(
        self, project_id: str, preview_id: str, *, import_id: str | None = None
    ) -> CommitResult:
        """Snapshot inputs, record the import, set the root, start indexing."""
        pdir = self.workspace.project_dir(project_id)
        pv = self.preview_of(project_id, preview_id)
        data: dict[FileKind, bytes] = {}
        for f in pv.files:
            path = pdir / PREVIEWS / preview_id / FILE_NAMES[f.kind]
            data[f.kind] = await asyncio.to_thread(path.read_bytes)
        import_id = import_id or new_ulid()
        if not is_ulid(import_id):
            raise JobConflict("Invalid import identity")
        record = ImportRecord(
            import_id=import_id,
            at=utc_now(),
            alias=pv.alias,
            root=pv.root,
            files=pv.files,
            counts=pv.counts,
            adapter=pv.adapter,
            source_key=pv.source_key,
        )
        existing = next((r for r in self.imports(project_id) if r.import_id == import_id), None)
        if existing is not None and existing.model_dump(exclude={"at"}) != record.model_dump(
            exclude={"at"}
        ):
            raise JobConflict("Import identity belongs to different preview contents")
        if existing is not None:
            for kind, blob in data.items():
                snapshot = pdir / SOURCES / import_id / FILE_NAMES[kind]
                if not snapshot.is_file() or snapshot.read_bytes() != blob:
                    raise JobConflict(
                        "The committed import snapshot changed; restore it before resuming"
                    )
        active = self.jobs.active(project_id, "index")
        if active is not None:
            if existing is not None and active.ref == import_id:
                return CommitResult(job_id=active.job_id, import_id=import_id)
            self._check_no_index_job(project_id)
        status = self.store.status(project_id)
        if (
            existing is not None
            and status.state == "ready"
            and status.import_id == import_id
            and status.job_id
        ):
            return CommitResult(job_id=status.job_id, import_id=import_id)
        source = SourceInfo(
            adapter=pv.adapter,
            adapter_version=nifti_files.VERSION if pv.adapter == "nifti-files" else "1",
            options=pv.options,
            detected_at=record.at,
        )
        draft = pdir / PREVIEWS / preview_id / identity.IDENTITY
        async with self.locks(project_id):
            if existing is None:
                for kind, blob in data.items():
                    atomic_write_bytes(pdir / SOURCES / import_id / FILE_NAMES[kind], blob)
                atomic_write_json(
                    pdir / SOURCES / import_id / "source.json", source.model_dump(mode="json")
                )
                if draft.is_file():  # append-only merge, keys never renumbered
                    merged = identity.load(pdir / SOURCES).merge(identity.load(draft.parent))
                    identity.save(pdir / SOURCES, merged)
                append_jsonl(pdir / SOURCES / IMPORTS, [record.model_dump(mode="json")])
        current = next(
            (r for r in self.workspace.get(project_id).path_roots if r.alias == pv.alias), None
        )
        if current is None or os.path.normpath(current.path) != pv.root:
            role = current.role if current is not None else "source"
            await self.workspace.set_root(
                project_id, PathRoot(alias=pv.alias, path=pv.root, role=role)
            )
        job_id = await self._start_index(project_id, import_id)
        return CommitResult(job_id=job_id, import_id=import_id)

    def _free_alias(self, project_id: str, alias: str, root: str) -> str:
        """The alias if it is free or already points at `root`; else DATA2, DATA3 …"""
        roots = {
            r.alias: os.path.normpath(r.path) for r in self.workspace.get(project_id).path_roots
        }
        if roots.get(alias) in (None, root):
            return alias
        for r_alias, path in roots.items():
            if path == root:
                return r_alias
        n = 2
        while f"{alias}{n}"[:16] in roots:
            n += 1
        return f"{alias}{n}"[:16]

    def latest_sources(self, project_id: str) -> list[ImportRecord]:
        """The latest import of every source key, oldest first."""
        latest: dict[str, ImportRecord] = {}
        for rec in reversed(self.imports(project_id)):
            latest.pop(rec.key, None)
            latest[rec.key] = rec
        return list(latest.values())

    def _snapshot(self, pdir: Path, rec: ImportRecord, resolver: PathResolver) -> ParsedInputs:
        data: dict[FileKind, bytes] = {}
        for f in rec.files:
            data[f.kind] = (pdir / SOURCES / rec.import_id / FILE_NAMES[f.kind]).read_bytes()
        return parse_inputs(data, resolver=resolver, alias=rec.alias)

    def annotations(self, project_id: str) -> Annotations:
        """Active annotation runs per field: field → item_id → annotation."""
        pdir = self.workspace.project_dir(project_id)
        out: Annotations = {}
        for field_name, run_id in self.workspace.get(project_id).annotation_sources.items():
            if not run_id:
                continue
            by_item: dict[str, Annotation] = {}
            for row in iter_jsonl(pdir / "tasks" / "runs" / run_id / ANNOTATIONS):
                if row.get("field") == field_name and row.get("item_id"):
                    by_item[str(row["item_id"])] = Annotation(
                        str(row.get("value") or ""), run_id, str(row.get("confidence") or "")
                    )
            out[field_name] = by_item
        return out

    async def reindex(self, project_id: str) -> str | None:
        """Rebuild the index from the current snapshots."""
        latest = self.latest_sources(project_id)
        if not latest:
            return None
        self._check_no_index_job(project_id)
        return await self._start_index(project_id, latest[-1].import_id)

    async def import_generated(
        self,
        project_id: str,
        metadata: bytes,
        *,
        root: str,
        alias: str,
        source_key: str,
        run_id: str | None = None,
        check_active: Callable[[], None] | None = None,
    ) -> CommitResult:
        """A task's `metadata.jsonl` as a new snapshot of its own source."""
        if run_id is not None:
            from app.ingest.generated import import_once

            return await import_once(
                self,
                project_id,
                run_id,
                metadata,
                root=root,
                alias=alias,
                source_key=source_key,
                check_active=check_active,
            )
        uploads: dict[FileKind, tuple[str, bytes]] = {"metadata": ("metadata.jsonl", metadata)}
        pv = await self.preview(
            project_id, root, alias=alias, uploads=uploads, source_key=source_key
        )
        return await self.commit(project_id, pv.preview_id)

    def _check_no_index_job(self, project_id: str) -> None:
        cur = self.jobs.active(project_id, "index")
        if cur is not None:
            raise JobConflict(f"An index job is already active: {cur.job_id}")

    def _plan_sidecars(
        self, project_id: str, rec: ImportRecord, drafts: list[Draft]
    ) -> list[sidecars.Spec]:
        """Reconstructed sidecars of an opted-in `metadata-v1` import (the option is kept in
        the snapshot's `source.json`); none without a derived root."""
        if rec.adapter != "metadata-v1":
            return []
        src = self.workspace.project_dir(project_id) / SOURCES / rec.import_id / "source.json"
        opts = SourceInfo.model_validate(read_json(src)).options if src.is_file() else {}
        if not opts.get(sidecars.OPTION):
            return []
        root = self.workspace.get(project_id).derived_root()
        if root is None:
            log.warning("reconstructed sidecars skipped: no derived root",
                        extra={"project_id": project_id, "import_id": rec.import_id})  # fmt: skip
            return []
        resolver = self.workspace.resolver(project_id)
        return sidecars.plan(drafts, resolver, root, project_id, rec.import_id, rec.at)

    async def _start_index(self, project_id: str, import_id: str) -> str:
        """Index the latest snapshot of every source with active annotations."""
        rules = self.phase_rules(project_id)
        pdir = self.workspace.project_dir(project_id)
        resolver = self.workspace.resolver(project_id)
        anns = self.annotations(project_id)
        from app.ingest.recycle import excluded_items

        excluded = excluded_items(pdir)
        per_source: list[list[Draft]] = []
        specs: list[sidecars.Spec] = []
        for rec in self.latest_sources(project_id):
            ds = build_drafts(self._snapshot(pdir, rec, resolver), resolver, rec.alias, rules, anns)
            ds = [d for d in ds if d.item_id not in excluded]
            for d in ds:
                d.import_id = rec.import_id
            specs += self._plan_sidecars(project_id, rec, ds)
            per_source.append(ds)
        drafts = merge_sources(per_source)
        units = [WorkUnit(indexer.probe_batch, (b,)) for b in indexer.batches(probes_for(drafts))]
        units += [  # written by the workers, like the probes
            WorkUnit(sidecars.write_batch, (specs[i : i + SIDECAR_BATCH],))
            for i in range(0, len(specs), SIDECAR_BATCH)
        ]
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
                    cfg = self.workspace.get(project_id)
                    apply_registered_masks(items, self.workspace.project_dir(project_id), cfg)
                    cases = build_cases(items, warnings, rules, cfg.phase_priority)
                    self.store.replace(project_id, items, cases, warnings)
                    n_items, n_excluded = split_items(i.status for i in items)
                    n_warnings = len(warnings)
                    st = IndexStatus(
                        state="ready",
                        import_id=import_id,
                        job_id=info.job_id,
                        started_at=st.started_at,
                        finished_at=utc_now(),
                        n_items=n_items,
                        n_excluded_upstream=n_excluded,
                        n_warnings=n_warnings,
                    )
                else:
                    state: IndexState = "failed"
                    if info.status in ("cancelled", "interrupted"):
                        state = info.status
                    st = st.model_copy(
                        update={"state": state, "finished_at": utc_now(), "error": info.error}
                    )
                self.store.write_status(project_id, st)
            if not ok:
                return import_id
            await self._seed_label_map(project_id)
            try:
                await self.variables.rebuild(project_id)  # profile every import
            except Exception:
                log.exception("variable profiling failed", extra={"project_id": project_id})
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
            drain_workers=True,
        )
        try:
            self.jobs.submit(spec)
        except Problem:
            async with self.locks(project_id):
                self.store.write_status(project_id, before)
            raise
        return job_id

    async def reapply_segmentations(self, project_id: str) -> None:
        """Rejoin registered segmentation manifests into the derived index."""
        async with self.locks(project_id):
            idx = self.store.load_resolved(project_id)  # never the phase join
            if not idx.items:
                return
            cfg = self.workspace.get(project_id)
            items = [i.model_copy(deep=True) for i in idx.items]
            for it in items:
                it.masks = {k: v for k, v in it.masks.items() if k == "imported"}
            apply_registered_masks(items, self.workspace.project_dir(project_id), cfg)
            rules = self.phase_rules(project_id)
            warnings = list(idx.warnings)
            cases = build_cases(items, warnings, rules, cfg.phase_priority)
            self.store.replace(project_id, items, cases, warnings)
        self.bus.publish(
            project_id,
            "index.rebuilt",
            {"import_id": None, "n_items": len(items), "n_warnings": len(warnings)},
        )

    @property
    def variables(self) -> VariableService:
        return VariableService(self.workspace, self.store, self.locks, self.bus)

    def phase_rules(self, project_id: str) -> PhaseRules:
        cfg = self.workspace.get(project_id)
        return PhaseRules(tuple(cfg.phase_vocabulary), dict(cfg.phase_mapping))

    async def _seed_label_map(self, project_id: str) -> None:
        """With no preset labels, name the mask values found as `label_{value}`, or by their
        mask set member name."""
        if self.workspace.get(project_id).label_map:
            return
        items = self.store.load(project_id).items
        values = sorted({v for i in items for v in i.labels_present})
        values = [v for v in values if v > 0]
        names = {v: n for i in items for m in i.masks.values() for n, v in (m.labels or {}).items()}
        if not values:
            return
        labels = [
            LabelEntry(
                value=v,
                name=names.get(v, auto_label_name(v)),
                color=AUTO_LABEL_COLORS[n % len(AUTO_LABEL_COLORS)],
                opacity=0.2,
            )
            for n, v in enumerate(values)
        ]
        await self.workspace.update(project_id, ProjectPatch(label_map=labels))
        self.bus.publish(project_id, "project.updated", {"fields": ["label_map"]})

    def imports(self, project_id: str) -> list[ImportRecord]:
        """Import history, newest first."""
        path = self.workspace.project_dir(project_id) / SOURCES / IMPORTS
        return [ImportRecord.model_validate(r) for r in reversed(read_jsonl(path))]

    async def index_status(self, project_id: str) -> IndexStatus:
        """Persisted index state; a stale `running` becomes `interrupted`."""
        st = self.store.status(project_id)
        if st.state == "running" and self.jobs.active(project_id, "index") is None:
            async with self.locks(project_id):
                st = self.store.status(project_id)
                if st.state == "running" and self.jobs.active(project_id, "index") is None:
                    st = st.model_copy(update={"state": "interrupted", "finished_at": utc_now()})
                    self.store.write_status(project_id, st)
        return st

    def warnings(
        self,
        project_id: str,
        *,
        code: str | None = None,
        severity: str | None = None,
        case_id: str | None = None,
        item_id: str | None = None,
    ) -> Sequence[QcWarning]:
        rows = self.store.load(project_id).warnings
        if code is None and severity is None and case_id is None and item_id is None:
            return rows
        return [
            w
            for w in rows
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
        phase: str | None = None,
        status: str | None = None,
        warning: str | None = None,
        has_voi: bool | None = None,
        sort: str = "case_id",
        var_cases: set[str] | None = None,
        curation_status: str | None = None,
    ) -> list[CaseSummary]:
        """Cases whose items are all `excluded_upstream` show only for that status.

        `var_cases`: case ids passing the `var.{name}` filters, or None for no filter.
        `curation_status`: the case review rollup (`partially_reviewed` included).
        """
        vocab = self.workspace.get(project_id).phase_vocabulary
        if phase is not None and vocab and phase not in vocab:
            raise ValidationProblem(
                f"Unknown phase {phase!r}",
                errors=[{"loc": ["query", "phase"], "msg": f"allowed: {vocab}"}],
            )
        idx = self.store.load(project_id)
        statuses: dict[str, set[str]] = {}
        for it in idx.items:
            statuses.setdefault(it.case_id, set()).add(it.status)
        warned: dict[str, set[str]] = {}
        if warning is not None:
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
            if var_cases is not None and c.case_id not in var_cases:
                return False
            if phase is not None and phase not in c.phases:
                return False
            if warning is not None and warning not in warned.get(c.case_id, set()):
                return False
            return has_voi is None or (c.has_voi_L or c.has_voi_R) == has_voi

        active = _active_by_case(idx.items)
        rollup = case_reviews(self.workspace.project_dir(project_id), active)
        values = self.variables.case_values(project_id)
        out = [
            _with_values(_with_curation(c, rollup, active), values) for c in idx.cases if keep(c)
        ]
        if curation_status is not None:
            out = [c for c in out if c.curation_status == curation_status]
        out.sort(key=lambda c: c.case_id, reverse=sort == "-case_id")
        if sort in ("n_warnings", "-n_warnings"):
            out.sort(key=lambda c: c.n_warnings, reverse=sort.startswith("-"))
        return out

    def case_detail(self, project_id: str, case_id: str) -> CaseDetail:
        idx = self.store.load(project_id)
        active = _active_by_case(idx.items)
        case = _with_values(
            _with_curation(
                self.store.get_case(project_id, case_id),
                case_reviews(self.workspace.project_dir(project_id), active),
                active,
            ),
            self.variables.case_values(project_id),
        )
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


def _with_values(
    case: CaseSummary, values: dict[str, dict[str, float | str | None]]
) -> CaseSummary:
    """Case-level visible variables onto a (cached, so copied) case summary."""
    hit = values.get(case.case_id)
    return case.model_copy(update={"variables": hit}) if hit else case


def _active_by_case(items: Sequence[Item]) -> dict[str, list[str]]:
    """Active item ids per case: the items a case needs a decision on to count as reviewed."""
    out: dict[str, list[str]] = {}
    for it in items:
        if it.status == "active":
            out.setdefault(it.case_id, []).append(it.item_id)
    return out


def _with_curation(
    case: CaseSummary, rollup: dict[str, CaseReview], active: dict[str, list[str]]
) -> CaseSummary:
    """Review rollup onto a (cached, so copied) case summary."""
    hit = rollup.get(case.case_id)
    if hit is None:
        return case.model_copy(update={"n_items_active": len(active.get(case.case_id, ()))})
    return case.model_copy(
        update={
            "curation_status": hit.status,
            "review_state": hit.state,
            "n_items_reviewed": hit.n_reviewed,
            "n_items_active": hit.n_active,
            "last_reviewed_at": hit.last_reviewed_at,
        }
    )
