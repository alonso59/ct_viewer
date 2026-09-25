"""CUR-08 reducer: events (append order) → derived latest state.

- Key: `(case_id, item_id, target)`; case-target events have `item_id = None`.
- Last-writer-wins by append order (CUR-12), never by the `at` timestamp.
- Item status = worst over its targets; case rollup = worst over the case's item keys and
  case-target keys. Ties go to the later event, which is the "deciding" one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.curation.models import (
    SEVERITY,
    CaseState,
    CurationEvent,
    CurationState,
    ItemState,
    TargetState,
)

Key = tuple[str, str | None, str, str | None]  # case, item, target, seg (mask targets)


@dataclass
class Reduced:
    n_events: int = 0
    # latest event per key, and its append position (for tie-breaks)
    latest: dict[Key, tuple[int, CurationEvent]] = field(default_factory=dict)
    last_at: dict[str, str] = field(default_factory=dict)  # case_id → newest `at`

    def add(self, pos: int, ev: CurationEvent) -> None:
        self.latest[(ev.case_id, ev.item_id, ev.target, ev.seg_key)] = (pos, ev)
        prev = self.last_at.get(ev.case_id)
        if prev is None or ev.at > prev:
            self.last_at[ev.case_id] = ev.at
        self.n_events += 1

    def items(self) -> dict[str, ItemState]:
        groups: dict[str, list[tuple[int, CurationEvent]]] = {}
        for (_, item_id, _, _), pe in self.latest.items():
            if item_id is not None:
                groups.setdefault(item_id, []).append(pe)
        out: dict[str, ItemState] = {}
        for item_id in sorted(groups):
            evs = groups[item_id]
            dec = _worst(evs)
            out[item_id] = ItemState(
                item_id=item_id,
                case_id=dec.case_id,
                status=dec.status,
                reviewer=dec.reviewer,
                at=dec.at,
                event_id=dec.event_id,
                targets=_targets(evs),
            )
        return out

    def cases(self) -> dict[str, CaseState]:
        groups: dict[str, list[tuple[int, CurationEvent]]] = {}
        for (case_id, _, _, _), pe in self.latest.items():
            groups.setdefault(case_id, []).append(pe)
        out: dict[str, CaseState] = {}
        for case_id in sorted(groups):
            evs = groups[case_id]
            dec = _worst(evs)
            out[case_id] = CaseState(
                case_id=case_id,
                status=dec.status,
                reviewer=dec.reviewer,
                at=dec.at,
                event_id=dec.event_id,
                last_reviewed_at=self.last_at[case_id],
                n_items_reviewed=len({e.item_id for _, e in evs if e.item_id is not None}),
                targets=_targets([pe for pe in evs if pe[1].item_id is None]),
            )
        return out

    def state(self, updated_at: str) -> CurationState:
        return CurationState(
            updated_at=updated_at,
            n_events=self.n_events,
            items=list(self.items().values()),
            cases=list(self.cases().values()),
        )


def reduce_events(events: Iterable[CurationEvent], start: int = 0) -> Reduced:
    red = Reduced()
    for pos, ev in enumerate(events, start):
        red.add(pos, ev)
    return red


def _worst(evs: list[tuple[int, CurationEvent]]) -> CurationEvent:
    return max(evs, key=lambda pe: (SEVERITY[pe[1].status], pe[0]))[1]


def _targets(evs: list[tuple[int, CurationEvent]]) -> list[TargetState]:
    return [
        TargetState(
            target=e.target,
            seg_id=e.seg_key,
            status=e.status,
            priority=e.priority,
            comment=e.comment,
            reviewer=e.reviewer,
            at=e.at,
            event_id=e.event_id,
            add_to_queue=e.add_to_queue,
            proposed_side=e.proposed_side,
        )
        for _, e in sorted(evs, key=lambda pe: (pe[1].target, pe[1].seg_key or ""))
    ]
