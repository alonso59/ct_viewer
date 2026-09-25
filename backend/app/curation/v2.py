"""CUR-13: v2 `curation_review.csv` rows → v3 curation events (`source: "v2_import"`).

v2 columns used: review_id, case_id, scan_idx, scope, side, target, status, priority,
comment, reviewer, reviewed_at, proposed_phase. v2 statuses map one to one to the v3 set
(ROADMAP P0 decision), except `wrong_phase_suspected`, which v3 no longer has (ADR-0026).
v2 targets map to v3 targets: `SEG → seg`, `VOI_mask → voi_mask`, `side_laterality_issue →
side`, and `{name}_mask → label:{value}` through the project label map (PRJ-07; no hard-coded
names). A row without `scan_idx` was a case-level decision and becomes `target = case`.
`phase_issue` rows with a `proposed_phase` become native phase events instead (PHS-08): the
latest per scan, skipped when the scan already has a phase selection.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, cast

from app.core.errors import ValidationProblem
from app.core.ids import new_ulid
from app.curation.models import SEVERITY, CurationEvent, Priority, Status, V2Skipped
from app.ingest.models import Item
from app.phase.service import import_record

REQUIRED_COLUMNS: Final = ("case_id", "target", "status")
FIXED_TARGETS: Final = {
    "seg": "seg",
    "voi_mask": "voi_mask",
    "side_laterality_issue": "side",
}
PRIORITIES: Final = ("low", "medium", "high")
PHASE_ISSUE: Final = "phase_issue"


@dataclass(frozen=True)
class V2Context:
    items: Mapping[str, Item]
    case_ids: frozenset[str]
    label_values: Mapping[str, int]  # lower-case label name → value
    vocabulary: Sequence[str]
    imported_ids: frozenset[str]  # v2 review_ids already imported
    fallback_reviewer: str
    phase_selected: frozenset[tuple[str, str]] = frozenset()  # scans with a phase event


@dataclass
class Converted:
    """Curation events, PHS-08 phase event records, and the skipped rows with a reason."""

    events: list[CurationEvent] = field(default_factory=list)
    phases: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[V2Skipped] = field(default_factory=list)


def item_context(item: Item) -> dict[str, Any]:
    """Audit snapshot stored in `event.context` (not used for logic)."""
    return {
        "image_fp": item.image.fp if item.image else None,
        "mask_fp": item.mask.fp if item.mask else None,
        "phase": item.phase.canonical,
        "import_id": item.import_id,
    }


def parse_rows(
    data: bytes,
    required: Sequence[str] = REQUIRED_COLUMNS,
    what: str = "Not a v2 curation_review.csv",
) -> list[tuple[int, dict[str, str]]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationProblem(
            "CSV must be UTF-8", errors=[{"loc": ["file"], "msg": "not UTF-8"}]
        ) from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    cols = [c.strip() for c in (reader.fieldnames or [])]
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValidationProblem(
            what,
            errors=[{"loc": ["file"], "msg": f"missing columns: {missing}"}],
        )
    rows: list[tuple[int, dict[str, str]]] = []
    for row in reader:
        clean = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None}
        rows.append((reader.line_num, clean))
    return rows


def _at(raw: str) -> str | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _target(raw: str, labels: Mapping[str, int]) -> str | None:
    key = raw.strip().lower()
    if key in FIXED_TARGETS:
        return FIXED_TARGETS[key]
    if key.endswith("_mask"):
        value = labels.get(key.removesuffix("_mask"))
        if value is not None:
            return f"label:{value}"
    return None


def _find_item(ctx: V2Context, case_id: str, scan_idx: str, scope: str, side: str) -> str | None:
    side_v = "-" if scope == "complete" else side.upper()
    if scope not in ("complete", "voi") or side_v not in ("L", "R", "-"):
        return None
    if scope == "voi" and side_v == "-":
        return None
    exact = f"{case_id}.{scan_idx}.{scope}.{side_v}"  # DATA_MODEL §item_id
    if exact in ctx.items:
        return exact
    for it in ctx.items.values():  # tolerate `1` vs `01` scan indexes
        if (
            it.case_id == case_id
            and it.scope == scope
            and it.side == side_v
            and it.scan_idx.lstrip("0") == scan_idx.lstrip("0")
        ):
            return it.item_id
    return None


def convert(rows: Sequence[tuple[int, dict[str, str]]], ctx: V2Context) -> Converted:
    """Map rows to events sorted by v2 `reviewed_at` (append order drives LWW, CUR-12)."""
    events: list[tuple[str, int, CurationEvent]] = []
    phases: dict[tuple[str, str], tuple[str, int, str | None, dict[str, Any]]] = {}
    skipped: list[V2Skipped] = []
    seen: set[str] = set(ctx.imported_ids)
    for line, row in rows:
        rid = row.get("review_id") or None

        def skip(reason: str, rid: str | None = rid, line: int = line) -> None:
            skipped.append(V2Skipped(line=line, review_id=rid, reason=reason))

        if rid is not None and rid in seen:
            skip("already imported")
            continue
        case_id = row.get("case_id", "")
        v2_target = row.get("target", "")
        is_phase = v2_target.strip().lower() == PHASE_ISSUE
        status = row.get("status", "")
        if not is_phase and status not in SEVERITY:
            skip(f"unknown status {status!r}")
            continue
        if case_id not in ctx.case_ids:
            skip(f"case {case_id!r} not in index")
            continue
        target = None if is_phase else _target(v2_target, ctx.label_values)
        if not is_phase and target is None:
            skip(f"unmapped target {v2_target!r}")
            continue
        at = _at(row.get("reviewed_at", ""))
        if at is None:
            skip("invalid reviewed_at")
            continue
        scan_idx = row.get("scan_idx", "")
        item: str | None = None
        if scan_idx:
            item = _find_item(
                ctx, case_id, scan_idx, row.get("scope") or "complete", row.get("side", "")
            )
            if item is None:
                skip("item not in index")
                continue
        else:
            target = "case"
        proposed = (row.get("proposed_phase") or "").upper() or None
        if is_phase:  # PHS-08: a native phase event, not a curation decision
            if item is None:
                skip("phase_issue without scan_idx")
            elif proposed is None or (ctx.vocabulary and proposed not in ctx.vocabulary):
                skip(f"phase_issue without a vocabulary proposed_phase ({proposed!r})")
            else:
                it = ctx.items[item]
                scan = (it.case_id, it.scan_idx)
                if scan in ctx.phase_selected:
                    skip("phase already set")
                else:
                    reviewer = row.get("reviewer") or ctx.fallback_reviewer
                    rec = import_record(reviewer, *scan, proposed, "v2_import", at)
                    prev = phases.get(scan)
                    superseded = "superseded by a later phase_issue row"
                    if prev is None or (at, line) >= prev[:2]:
                        if prev is not None:
                            skip(superseded, rid=prev[2], line=prev[1])
                        phases[scan] = (at, line, rid, rec)
                    else:
                        skip(superseded)
                    if rid is not None:
                        seen.add(rid)
            continue
        assert target is not None
        context: dict[str, Any] = {"v2_target": v2_target}
        if rid is not None:
            context["v2_review_id"] = rid
        if proposed is not None:
            context["v2_proposed_phase"] = proposed  # audit only: phase is native (ADR-0026)
        if item is not None:
            context |= item_context(ctx.items[item])
        priority = row.get("priority", "medium")
        ev = CurationEvent(
            event_id=new_ulid(),
            at=at,
            reviewer=row.get("reviewer") or ctx.fallback_reviewer,
            item_id=item,
            case_id=case_id,
            target=target,
            status=cast(Status, status),  # checked against SEVERITY above
            priority=cast(Priority, priority if priority in PRIORITIES else "medium"),
            comment=row.get("comment", ""),
            context=context,
            source="v2_import",
        )
        if rid is not None:
            seen.add(rid)
        events.append((at, line, ev))
    events.sort(key=lambda t: (t[0], t[1]))
    return Converted(
        events=[e for _, _, e in events],
        phases=[p[3] for p in sorted(phases.values(), key=lambda t: (t[0], t[1]))],
        skipped=skipped,
    )
