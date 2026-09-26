"""Derived curation state readers shared with other services (analytics DB-02/07, ingest).

Contract (lane 2): pure functions over a project folder; no API-process state needed.
`events.jsonl` is append-only (CUR-02), so the per-process cache (BE-07) reads only the
new tail on each call and re-reads fully if the file shrank or was replaced.
Returned containers are shared with the cache: callers must not mutate them.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from app.curation.models import (
    LEGACY_PHASE_TARGET,
    NOT_REVIEWED,
    PARTIALLY_REVIEWED,
    QUEUE_STATUSES,
    CaseState,
    CurationEvent,
    ItemState,
    ReviewState,
    RollupStatus,
)
from app.curation.reducer import Reduced

log = logging.getLogger("app.curation")

EVENTS: Final = Path("curation") / "events.jsonl"
STATE: Final = Path("curation") / "state.json"
CACHE_MAX: Final = 8


@dataclass
class _Entry:
    ino: int = -1
    offset: int = 0  # bytes consumed (always at a line boundary)
    events: list[CurationEvent] = field(default_factory=list)
    reduced: Reduced = field(default_factory=Reduced)
    items: dict[str, ItemState] | None = None
    cases: dict[str, CaseState] | None = None


_cache: OrderedDict[Path, _Entry] = OrderedDict()
_lock = threading.Lock()


def _refresh(project_dir: Path) -> _Entry:
    path = project_dir / EVENTS
    with _lock:
        entry = _cache.get(path)
        try:
            st = os.stat(path)
        except FileNotFoundError:
            entry = _Entry()
        else:
            if entry is None or entry.ino != st.st_ino or st.st_size < entry.offset:
                entry = _Entry(ino=st.st_ino)
            if st.st_size > entry.offset:
                _read_tail(path, entry)
        _cache[path] = entry
        _cache.move_to_end(path)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
        return entry


def _read_tail(path: Path, entry: _Entry) -> None:
    with path.open("rb") as fh:
        fh.seek(entry.offset)
        data = fh.read()
    end = data.rfind(b"\n")
    if end < 0:
        return  # partial line still being written
    for raw in data[: end + 1].splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            ev = CurationEvent.model_validate_json(line)
        except ValidationError:
            if b'"wrong_phase_suspected"' not in line:  # a pre-ADR-0026 status, not malformed
                log.warning("skipping malformed curation event", extra={"path": str(path)})
            continue
        if ev.target == LEGACY_PHASE_TARGET:
            continue  # phase is a native selection now (ADR-0026, PHASE.md)
        entry.reduced.add(len(entry.events), ev)
        entry.events.append(ev)
    entry.offset += end + 1
    entry.items = entry.cases = None


def load_events(project_dir: Path) -> list[CurationEvent]:
    """All valid events in append order."""
    return _refresh(project_dir).events


def reduced(project_dir: Path) -> Reduced:
    return _refresh(project_dir).reduced


def item_states(project_dir: Path) -> dict[str, ItemState]:
    entry = _refresh(project_dir)
    if entry.items is None:
        entry.items = entry.reduced.items()
    return entry.items


def case_states(project_dir: Path) -> dict[str, CaseState]:
    entry = _refresh(project_dir)
    if entry.cases is None:
        entry.cases = entry.reduced.cases()
    return entry.cases


def item_statuses(project_dir: Path) -> dict[str, str]:
    """Latest QC status per item_id (worst over the item's targets, CUR-08)."""
    return {k: v.status for k, v in item_states(project_dir).items()}


@dataclass(frozen=True)
class CaseReview:
    """CUR-08 case rollup: `status` is shown on badges, `state` drives progress."""

    status: RollupStatus
    state: ReviewState
    n_reviewed: int  # active items with a decision
    n_active: int
    last_reviewed_at: str | None


def case_reviews(project_dir: Path, active: Mapping[str, Collection[str]]) -> dict[str, CaseReview]:
    """CUR-08 per case_id, given its active item ids (`active`, from the index).

    A case is reviewed when every active item has a decision (a latest status other than
    `not_reviewed`); with decisions but an undecided active item it is partial. The status is
    the worst decision, except that a partial case whose worst status is not in the queue set
    shows `partially_reviewed` (a problem stays visible). Cases without decisions are omitted.
    """
    items = item_states(project_dir)
    out: dict[str, CaseReview] = {}
    for case_id, cs in case_states(project_dir).items():
        ids = active.get(case_id, ())
        n_rev = sum(1 for i in ids if (s := items.get(i)) is not None and s.status != NOT_REVIEWED)
        state: ReviewState
        if cs.status == NOT_REVIEWED:
            state = "not_reviewed"
        elif n_rev < len(ids):
            state = "partial"
        else:
            state = "reviewed"
        status: RollupStatus = cs.status
        if state == "partial" and status not in QUEUE_STATUSES:
            status = PARTIALLY_REVIEWED
        out[case_id] = CaseReview(status, state, n_rev, len(ids), cs.last_reviewed_at)
    return out
