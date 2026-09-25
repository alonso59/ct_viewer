"""Phase selections and the read-time join (PHS-02/03), readable without the service.

Pure functions over a project folder, so the index store (BE-07) can join them on load. The
join never writes: `metadata.jsonl`, `phase.json` and `index/` stay as indexed (R1, ADR-0020 §3).
An overridden item keeps the index-time value in `phase.resolved`.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from app.core.fsio import iter_jsonl
from app.eventstore.store import latest, namespace_path
from app.ingest.models import CaseSummary, Item, PhaseInfo

NAMESPACE: Final = "phase"
MANUAL: Final = "manual"  # `phase.source` of a natively selected phase (PHASE.md)

ScanKey = tuple[str, str]  # (case_id, scan_idx)


def path(project_dir: Path) -> Path:
    return namespace_path(project_dir, NAMESPACE)


def signature(project_dir: Path) -> tuple[int, int, int] | None:
    """Changes whenever the event file does; None when there is none yet."""
    try:
        st = os.stat(path(project_dir))
    except FileNotFoundError:
        return None
    return st.st_ino, st.st_size, st.st_mtime_ns


def events(project_dir: Path) -> list[dict[str, Any]]:
    """Well-formed events in append order."""
    return [
        e
        for e in iter_jsonl(path(project_dir))
        if all(isinstance(e.get(k), str) and e.get(k) for k in ("case_id", "scan_idx", "value"))
    ]


def selections(project_dir: Path) -> dict[ScanKey, dict[str, Any]]:
    """PHS-02: latest event per `(case_id, scan_idx)`, in append order."""
    out = latest(events(project_dir), lambda e: (e["case_id"], e["scan_idx"]))
    return {(str(k[0]), str(k[1])): v for k, v in out.items() if isinstance(k, tuple)}


def effective(info: PhaseInfo, value: str) -> PhaseInfo:
    base = info.resolved or info
    return PhaseInfo(canonical=value, raw=base.raw, source=MANUAL, resolved=base)


def apply(
    items: Sequence[Item],
    cases: Sequence[CaseSummary],
    selected: dict[ScanKey, dict[str, Any]],
    vocabulary: Sequence[str],
) -> tuple[list[Item], list[CaseSummary]]:
    """PHS-03: the selected value wins over `Item.phase.canonical`; case `phases` follow.

    Items and cases are copied, never mutated (they are shared with the index cache).
    """
    if not selected:
        return list(items), list(cases)
    out_items: list[Item] = []
    touched: set[str] = set()
    for it in items:
        sel = selected.get((it.case_id, it.scan_idx))
        if sel is None:
            out_items.append(it)
            continue
        out_items.append(it.model_copy(update={"phase": effective(it.phase, sel["value"])}))
        touched.add(it.case_id)
    by_case: dict[str, set[str]] = {}
    for it in out_items:
        if it.case_id in touched and it.status != "excluded_upstream":
            by_case.setdefault(it.case_id, set()).add(it.phase.canonical)
    out_cases = [
        c.model_copy(update={"phases": _order(by_case.get(c.case_id, set()), vocabulary)})
        if c.case_id in touched
        else c
        for c in cases
    ]
    return out_items, out_cases


def _order(phases: set[str], vocabulary: Sequence[str]) -> list[str]:
    """As `PhaseRules.order`: vocabulary order first, then other values sorted."""
    known = [p for p in vocabulary if p in phases]
    return known + sorted(phases - set(known))
