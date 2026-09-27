"""Curation service: append, history, derived state, queue, exports, v2 import (CUR-*).

Stateless like the other services: routers build one per request. `events.jsonl` is the
source of truth (CUR-02); `state.json` is a derived snapshot rewritten after each append.
Only this (API) process writes, under the project lock (BE-05). Source data is never
written (R1): paths are only resolved to report them (CUR-09).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final

from app.core.errors import Problem, ValidationProblem
from app.core.fsio import append_jsonl, atomic_write_bytes, atomic_write_json
from app.core.ids import new_ulid, parse_item_id, utc_now
from app.core.locks import ProjectLocks
from app.core.reviewer import require as require_reviewer
from app.curation import converter_csv, v2
from app.curation import state as st
from app.curation.models import (
    CASE_TARGET,
    QUEUE_COLUMNS,
    QUEUE_STATUSES,
    CurationEvent,
    CurationState,
    EventIn,
    ExportResult,
    QueueRow,
    V2ImportReport,
)
from app.events.bus import EventBus
from app.eventstore.store import namespace_path
from app.ingest.models import Item, VolumeRef
from app.ingest.store import IndexStore
from app.phase import state as phase_state
from app.phase.service import PhaseService
from app.projects.service import Workspace

EXPORTS: Final = Path("exports")
STATE_CSV: Final = "curation_state.csv"
EVENTS_COPY: Final = "events.jsonl"
STATE_COLUMNS: Final = (
    "case_id",
    "item_id",
    "scope",
    "side",
    "phase",
    "target",
    "seg_id",
    "status",
    "item_status",
    "case_status",
    "priority",
    "comment",
    "proposed_side",
    "add_to_queue",
    "reviewer",
    "at",
    "event_id",
    "source",
)
SSE_EVENT_MAX: Final = 500  # larger v2 imports publish one `project.updated` instead


def _invalid(field: str, msg: str) -> ValidationProblem:
    return ValidationProblem(msg, errors=[{"loc": ["body", field], "msg": msg}])


class CurationService:
    def __init__(
        self, workspace: Workspace, store: IndexStore, locks: ProjectLocks, bus: EventBus
    ) -> None:
        self.workspace = workspace
        self.store = store
        self.locks = locks
        self.bus = bus
        self.phase = PhaseService(workspace, store, locks, bus)  # PHS-08 import compat

    def _pdir(self, project_id: str) -> Path:
        return self.workspace.project_dir(project_id)

    # -- API-50 -----------------------------------------------------------------------------

    def history(
        self, project_id: str, *, item_id: str | None = None, case_id: str | None = None
    ) -> list[CurationEvent]:
        """CUR-14: every event (CUR-12), newest first; filter by item and/or case."""
        events = st.load_events(self._pdir(project_id))
        return [
            e
            for e in reversed(events)
            if (item_id is None or e.item_id == item_id)
            and (case_id is None or e.case_id == case_id)
        ]

    def _validate(self, project_id: str, body: EventIn) -> tuple[str, Item | None]:
        """CUR-03/07: target grammar, label map, item/case existence."""
        cfg = self.workspace.get(project_id)
        idx = self.store.load(project_id)
        item: Item | None = None
        if body.target == CASE_TARGET:
            if body.item_id is not None:
                raise _invalid("item_id", "item_id must be null when target = case")
            if body.case_id is None:
                raise _invalid("case_id", "case_id is required when target = case")
            if body.case_id not in idx.cases_by_id:
                raise _invalid("case_id", f"case {body.case_id!r} not in index")
            case_id = body.case_id
        else:
            if body.item_id is None:
                raise _invalid("item_id", f"item_id is required for target {body.target!r}")
            item = idx.by_id.get(body.item_id)
            if item is None:
                raise _invalid("item_id", f"item {body.item_id!r} not in index")
            if body.case_id is not None and body.case_id != item.case_id:
                raise _invalid("case_id", "case_id does not match the item")
            case_id = item.case_id
        if body.target.startswith("label:"):
            values = {entry.value for entry in cfg.label_map}
            if int(body.target.removeprefix("label:")) not in values:
                raise _invalid("target", f"label value not in label map: {sorted(values)}")
        mask_target = body.target in ("seg", "voi_mask") or body.target.startswith("label:")
        if body.seg_id is not None and (not mask_target or cfg.segmentation(body.seg_id) is None):
            raise _invalid("seg_id", "seg_id must name a segmentation set, on mask targets only")
        return case_id, item

    async def append(
        self,
        project_id: str,
        body: EventIn,
        *,
        reviewer: str | None,
        session_id: str | None = None,
    ) -> CurationEvent:
        """CUR-02/03/05/07/11: validate, append under the lock, publish `curation.appended`."""
        name = require_reviewer(reviewer)
        pdir = self._pdir(project_id)
        case_id, item = self._validate(project_id, body)
        context = dict(body.context)
        if item is not None:
            for k, v in v2.item_context(item).items():
                context.setdefault(k, v)
        ev = CurationEvent(
            event_id=new_ulid(),
            at=utc_now(),
            reviewer=name,
            session_id=(session_id or "").strip() or body.session_id,
            item_id=body.item_id if item is not None else None,
            case_id=case_id,
            target=body.target,
            seg_id=(body.seg_id or self.workspace.get(project_id).default_seg)
            if body.target in ("seg", "voi_mask") or body.target.startswith("label:")
            else None,
            status=body.status,
            priority=body.priority,
            comment=body.comment,
            proposed_side=body.proposed_side,
            add_to_queue=body.add_to_queue,
            context=context,
            source=body.source,
        )
        await self._append(project_id, pdir, [ev])
        return ev

    async def _append(self, project_id: str, pdir: Path, events: Sequence[CurationEvent]) -> None:
        async with self.locks(project_id):
            self._append_locked(pdir, events)
        self._publish(project_id, events)

    def _append_locked(self, pdir: Path, events: Sequence[CurationEvent]) -> None:
        """Caller holds the project lock (BE-05)."""
        # The core event store namespace `curation` keeps `curation/events.jsonl` (ADR-0022)
        append_jsonl(namespace_path(pdir, "curation"), (e.model_dump(mode="json") for e in events))
        self._write_snapshot(pdir)

    def _publish(self, project_id: str, events: Sequence[CurationEvent]) -> None:
        """CUR-11: one `curation.appended` per event (API-40)."""
        if len(events) <= SSE_EVENT_MAX:
            for e in events:
                self.bus.publish(project_id, "curation.appended", e.model_dump(mode="json"))
        else:
            self.bus.publish(project_id, "project.updated", {"fields": ["curation"]})

    def _write_snapshot(self, pdir: Path) -> CurationState:
        snap = CurationState(
            updated_at=utc_now(),
            n_events=st.reduced(pdir).n_events,
            items=list(st.item_states(pdir).values()),
            cases=list(st.case_states(pdir).values()),
        )
        atomic_write_json(pdir / st.STATE, snap.model_dump(mode="json"))
        return snap

    # -- API-51 -----------------------------------------------------------------------------

    def state(
        self, project_id: str, *, case_id: str | None = None, item_id: str | None = None
    ) -> CurationState:
        """CUR-08: latest per `(item_id, target)`, item = worst target, case = worst item."""
        pdir = self._pdir(project_id)
        red = st.reduced(pdir)
        items = st.item_states(pdir).values()
        cases = st.case_states(pdir).values()
        return CurationState(
            updated_at=utc_now(),
            n_events=red.n_events,
            items=[
                i
                for i in items
                if (case_id is None or i.case_id == case_id)
                and (item_id is None or i.item_id == item_id)
            ],
            cases=[
                c
                for c in cases
                if (case_id is None or c.case_id == case_id)
                and (item_id is None or item_id.startswith(f"{c.case_id}."))
            ],
        )

    # -- API-52 -----------------------------------------------------------------------------

    def queue(self, project_id: str) -> list[QueueRow]:
        """CUR-09: item keys whose latest status is in the queue set or `add_to_queue=true`.

        Absolute paths are resolved now (never stored); null when unresolvable.
        """
        pdir = self._pdir(project_id)
        idx = self.store.load(project_id)
        resolver = self.workspace.resolver(project_id)

        def absolute(ref: str | None) -> str | None:
            if not ref:
                return None
            try:
                return str(resolver.resolve(ref))
            except Problem:
                return None

        rows: list[QueueRow] = []
        latest = sorted(st.reduced(pdir).latest.values(), key=lambda pe: pe[0])
        for _, e in latest:
            if e.item_id is None or not (e.status in QUEUE_STATUSES or e.add_to_queue):
                continue
            item = idx.by_id.get(e.item_id)
            scope, side, phase = _item_cols(e.item_id, item)
            rows.append(
                QueueRow(
                    case_id=e.case_id,
                    item_id=e.item_id,
                    scope=scope,
                    side=side,
                    phase=phase,
                    target=e.target,
                    seg_id=e.seg_key,
                    status=e.status,
                    priority=e.priority,
                    comment=e.comment,
                    reviewer=e.reviewer,
                    at=e.at,
                    image_path_abs=absolute(item.image.ref if item and item.image else None),
                    mask_path_abs=absolute(mask.ref if (mask := _mask_of(item, e)) else None),
                )
            )
        return rows

    def queue_csv(self, project_id: str) -> str:
        return _csv(QUEUE_COLUMNS, (r.model_dump() for r in self.queue(project_id)))

    # -- API-53 -----------------------------------------------------------------------------

    async def export(self, project_id: str) -> ExportResult:
        """CUR-10: `curation_state.csv` and an `events.jsonl` copy (phase: PHS-06)."""
        pdir = self._pdir(project_id)
        idx = self.store.load(project_id)
        async with self.locks(project_id):
            red = st.reduced(pdir)
            items = st.item_states(pdir)
            cases = st.case_states(pdir)
            events_path = pdir / st.EVENTS
            raw = events_path.read_bytes() if events_path.exists() else b""
            state_rows: list[dict[str, Any]] = []
            for _, e in sorted(red.latest.values(), key=lambda pe: (pe[1].case_id, pe[0])):
                item = idx.by_id.get(e.item_id) if e.item_id else None
                scope, side, phase = _item_cols(e.item_id, item)
                state_rows.append(
                    {
                        **e.model_dump(mode="json"),
                        "seg_id": e.seg_key,
                        "scope": scope,
                        "side": side,
                        "phase": phase,
                        "item_status": items[e.item_id].status if e.item_id else None,
                        "case_status": cases[e.case_id].status,
                    }
                )
            out = pdir / EXPORTS
            atomic_write_bytes(out / STATE_CSV, _csv(STATE_COLUMNS, state_rows).encode("utf-8"))
            atomic_write_bytes(out / EVENTS_COPY, raw)
        return ExportResult(files=[STATE_CSV, EVENTS_COPY], at=utc_now())

    # -- API-54 -----------------------------------------------------------------------------

    async def import_v2(
        self, project_id: str, data: bytes, *, reviewer: str | None
    ) -> V2ImportReport:
        """CUR-13: v2 rows → `source: "v2_import"` events; skipped rows carry a reason.

        `phase_issue` rows become native phase events (PHS-08).
        """
        name = require_reviewer(reviewer)
        pdir = self._pdir(project_id)
        rows = v2.parse_rows(data)
        cfg = self.workspace.get(project_id)
        idx = self.store.load(project_id)
        async with self.locks(project_id):
            imported = frozenset(
                str(e.context["v2_review_id"])
                for e in st.load_events(pdir)
                if e.source == "v2_import" and e.context.get("v2_review_id")
            )
            ctx = v2.V2Context(
                items=idx.by_id,
                case_ids=frozenset(idx.cases_by_id),
                label_values={entry.name.lower(): entry.value for entry in cfg.label_map},
                vocabulary=tuple(cfg.phase_vocabulary),
                imported_ids=imported,
                fallback_reviewer=name,
                phase_selected=frozenset(phase_state.selections(pdir)),
            )
            out = v2.convert(rows, ctx)
            if out.events:
                self._append_locked(pdir, out.events)
            self.phase.append_locked(project_id, out.phases)
        return self._imported(project_id, len(rows), out)

    async def import_converter(
        self, project_id: str, data: bytes, *, reviewer: str | None
    ) -> V2ImportReport:
        """CUR-15: the converter CLI's `curation.csv` → `source: "converter_import"` events;
        `curated_phase` → native phase events (PHS-08)."""
        name = require_reviewer(reviewer)
        pdir = self._pdir(project_id)
        rows = converter_csv.parse(data)
        cfg = self.workspace.get(project_id)
        idx = self.store.load(project_id)
        async with self.locks(project_id):
            imported = frozenset(
                str(e.context["converter_key"])
                for e in st.load_events(pdir)
                if e.source == "converter_import" and e.context.get("converter_key")
            )
            ctx = converter_csv.ConverterContext(
                items=idx.by_id,
                vocabulary=tuple(cfg.phase_vocabulary),
                mapping=dict(cfg.phase_mapping),
                imported=imported,
                reviewer=name,
                phase_selected=frozenset(phase_state.selections(pdir)),
            )
            out = converter_csv.convert(rows, ctx)
            if out.events:
                self._append_locked(pdir, out.events)
            self.phase.append_locked(project_id, out.phases)
        return self._imported(project_id, len(rows), out)

    def _imported(self, project_id: str, n_rows: int, out: v2.Converted) -> V2ImportReport:
        self._publish(project_id, out.events)
        self.phase.publish(project_id, out.phases)
        return V2ImportReport(
            n_rows=n_rows,
            imported=len(out.events),
            phase_events=len(out.phases),
            skipped=out.skipped,
        )


def _mask_of(item: Item | None, ev: CurationEvent) -> VolumeRef | None:
    """The decision's segmentation set (ADR-0015); other targets show the default mask."""
    if item is None:
        return None
    seg = ev.seg_key
    return item.masks.get(seg) if seg is not None else item.mask


def _item_cols(item_id: str | None, item: Item | None) -> tuple[str | None, str | None, str | None]:
    if item is not None:
        return item.scope, item.side, item.phase.canonical
    parsed = parse_item_id(item_id) if item_id else None
    return (parsed[2], parsed[3], None) if parsed else (None, None, None)


def _csv(columns: Sequence[str], rows: Iterable[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: _cell(r.get(k)) for k in columns})
    return buf.getvalue()


def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return v
