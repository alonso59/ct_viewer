"""Native phase selection service (PHASE.md PHS-01..08, ADR-0026).

Not a plugin and not gated by one. Selections are events in the core event store namespace
`phase` (PHS-02); the effective phase is joined at read time by the index store (PHS-03).
Stateless like the other services: routers build one per request.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from app.core.errors import ValidationProblem
from app.core.fsio import atomic_write_json
from app.core.ids import utc_now
from app.core.locks import ProjectLocks
from app.events.bus import EventBus
from app.eventstore.store import EventStore, require_reviewer, stamp
from app.ingest.store import IndexStore
from app.phase import state
from app.phase.models import (
    PhaseEvent,
    PhaseExportResult,
    PhaseIn,
    PhaseSelection,
    PhaseState,
)
from app.projects.service import Workspace

EXPORTS: Final = Path("exports")
SELECTIONS: Final = "phase_selections.json"
ANALYZER_FIELD: Final = "phase"  # `annotation_sources` key of the active `analyzer.phase` run


def _invalid(field: str, msg: str) -> ValidationProblem:
    return ValidationProblem(msg, errors=[{"loc": ["body", field], "msg": msg}])


class PhaseService:
    def __init__(
        self, workspace: Workspace, store: IndexStore, locks: ProjectLocks, bus: EventBus
    ) -> None:
        self.workspace = workspace
        self.store = store
        self.events = EventStore(workspace, locks, bus)

    def _pdir(self, project_id: str) -> Path:
        return self.workspace.project_dir(project_id)

    # -- write (PHS-01/02/04) -------------------------------------------------------------------

    def check_value(self, project_id: str, value: str) -> str:
        """A `phase_vocabulary` value; an empty vocabulary is open (PRJ-12)."""
        vocab = self.workspace.get(project_id).phase_vocabulary
        v = value.strip()
        if not v or (vocab and v not in vocab):
            raise _invalid("value", f"allowed: {vocab}" if vocab else "value is empty")
        return v

    async def append(
        self, project_id: str, body: PhaseIn, *, reviewer: str | None, session_id: str | None
    ) -> PhaseEvent:
        """One click = one event; it replaces the effective phase of the scan at once."""
        who = require_reviewer(reviewer)
        value = self.check_value(project_id, body.value)
        idx = self.store.load_resolved(project_id)
        if not any(i.case_id == body.case_id and i.scan_idx == body.scan_idx for i in idx.items):
            raise _invalid("scan_idx", f"scan {body.case_id}/{body.scan_idx} not in index")
        if body.source == "analyzer_accept":
            active = self.workspace.get(project_id).annotation_sources.get(ANALYZER_FIELD)
            if not body.accepted_run_id or body.accepted_run_id != active:
                raise _invalid("accepted_run_id", "must name the active analyzer.phase run")
        elif body.accepted_run_id is not None:
            raise _invalid("accepted_run_id", "only with source analyzer_accept")
        record = stamp(
            who,
            (session_id or "").strip() or body.session_id,
            {"case_id": body.case_id, "scan_idx": body.scan_idx, "value": value,
             "source": body.source, "accepted_run_id": body.accepted_run_id},
        )  # fmt: skip
        await self.events.append(project_id, state.NAMESPACE, [record])  # PHS-05
        return PhaseEvent(**record)

    def append_locked(self, project_id: str, records: Sequence[dict[str, Any]]) -> None:
        """Import compat (PHS-08): the caller holds the project lock and publishes."""
        if records:
            self.events.append_locked(project_id, state.NAMESPACE, records)

    def publish(self, project_id: str, records: Sequence[dict[str, Any]]) -> None:
        if records:
            self.events.publish(project_id, state.NAMESPACE, records, {"fields": ["phase"]})

    # -- read (PHS-02/07) -----------------------------------------------------------------------

    def history(
        self, project_id: str, *, case_id: str | None = None, scan_idx: str | None = None
    ) -> list[PhaseEvent]:
        """PHS-07: every event, newest first."""
        return [
            PhaseEvent.model_validate(e)
            for e in reversed(state.events(self._pdir(project_id)))
            if (case_id is None or e["case_id"] == case_id)
            and (scan_idx is None or e["scan_idx"] == scan_idx)
        ]

    def state(self, project_id: str, *, case_id: str | None = None) -> PhaseState:
        pdir = self._pdir(project_id)
        selected = state.selections(pdir)
        resolved: dict[tuple[str, str], tuple[str, str]] = {}
        for i in self.store.load_resolved(project_id).items:
            resolved.setdefault((i.case_id, i.scan_idx), (i.phase.canonical, i.phase.source))
        rows = []
        for key, e in sorted(selected.items()):
            if case_id is not None and key[0] != case_id:
                continue
            ev = PhaseEvent.model_validate(e)
            base = resolved.get(key)
            rows.append(
                PhaseSelection(
                    **ev.model_dump(exclude={"session_id"}),
                    resolved=base[0] if base else None,
                    resolved_source=base[1] if base else None,
                )
            )
        return PhaseState(n_events=len(state.events(pdir)), selections=rows)

    # -- export (PHS-06) ------------------------------------------------------------------------

    async def export(self, project_id: str) -> PhaseExportResult:
        """`exports/phase_selections.json`, shaped like `phase.json` (INPUT_METADATA)."""
        pdir = self._pdir(project_id)
        async with self.events.locks(project_id):
            selected = state.selections(pdir)
            doc = {
                "schema_version": 1,
                "updated_at": utc_now(),
                "phases": [
                    {"case_id": c, "scan_idx": s, "phase": e["value"]}
                    for (c, s), e in sorted(selected.items())
                ],
            }
            atomic_write_json(pdir / EXPORTS / SELECTIONS, doc)
        return PhaseExportResult(files=[SELECTIONS], at=utc_now())


def import_record(
    reviewer: str, case_id: str, scan_idx: str, value: str, source: str, at: str | None = None
) -> dict[str, Any]:
    """A PHS-08 import event (`v2_import` / `converter_import`); `at` keeps the v2 time."""
    rec = stamp(reviewer, None, {"case_id": case_id, "scan_idx": scan_idx, "value": value,
                                 "source": source, "accepted_run_id": None})  # fmt: skip
    if at:
        rec["at"] = at
    return rec
