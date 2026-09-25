"""CUR-15 / PHS-08: the standalone converter's `curation.csv` (DCM-08/09) → events, once.

Columns used: case_id, scan_idx, curated_keep, curated_role, curated_phase, curated_quality,
notes. Per row with a manual value (`source: "converter_import"`):
- a curation event on target `seg`: `curated_keep` false → `rejected`; quality poor/bad →
  needs major, fair → needs minor correction; `curated_keep` true or quality good → `accepted`;
  `notes` (and quality/role) become the comment;
- `curated_phase` → a native phase event (PHS-08), not a curation decision; skipped when the
  scan already has a phase selection (a later import must not override a reviewer's click).
Rows already imported are skipped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.core.ids import new_ulid, utc_now
from app.curation.models import CurationEvent, Status, V2Skipped
from app.curation.v2 import Converted, item_context, parse_rows
from app.ingest.models import Item
from app.phase.service import import_record
from app.projects.presets import MISSING_PHASE_VALUES, UNKNOWN_PHASE, normalize_phase_value

REQUIRED: Final = ("case_id", "scan_idx")
FALSE: Final = {"0", "false", "no", "n", "exclude", "excluded", "drop"}
TRUE: Final = {"1", "true", "yes", "y", "keep", "include"}
QUALITY: Final[dict[str, Status]] = {
    "poor": "needs_major_correction",
    "bad": "needs_major_correction",
    "low": "needs_major_correction",
    "fair": "needs_minor_correction",
    "medium": "needs_minor_correction",
    "good": "accepted",
    "ok": "accepted",
    "high": "accepted",
}


@dataclass(frozen=True)
class ConverterContext:
    items: Mapping[str, Item]
    vocabulary: Sequence[str]
    mapping: Mapping[str, str]
    imported: frozenset[str]  # `case_id|scan_idx` keys already imported
    reviewer: str
    phase_selected: frozenset[tuple[str, str]] = frozenset()  # scans with a phase event


def parse(data: bytes) -> list[tuple[int, dict[str, str]]]:
    return parse_rows(data, REQUIRED, "Not a converter curation.csv")


def phase_value(raw: str, vocabulary: Sequence[str], mapping: Mapping[str, str]) -> str | None:
    """A curated phase in the project vocabulary; None when it cannot be mapped."""
    value = normalize_phase_value(raw, list(vocabulary), dict(mapping))
    if value == UNKNOWN_PHASE and raw.strip().upper() not in {*MISSING_PHASE_VALUES, "UNK"}:
        return None
    return value


def convert(rows: Sequence[tuple[int, dict[str, str]]], ctx: ConverterContext) -> Converted:
    events: list[CurationEvent] = []
    phases: list[dict[str, Any]] = []
    skipped: list[V2Skipped] = []
    seen = set(ctx.imported)
    phase_seen = set(ctx.phase_selected)
    now = utc_now()
    for line, row in rows:
        key = f"{row.get('case_id', '')}|{row.get('scan_idx', '')}"
        keep = row.get("curated_keep", "").lower()
        phase = row.get("curated_phase", "")
        quality = row.get("curated_quality", "").lower()
        notes = row.get("notes", "")
        if not (keep or phase or quality or notes or row.get("curated_role")):
            continue  # nothing curated on this row
        if key in seen:
            skipped.append(V2Skipped(line=line, review_id=key, reason="already imported"))
            continue
        iid = f"{row['case_id']}.{row['scan_idx']}.complete.-"
        item = ctx.items.get(iid)
        if item is None:
            skipped.append(V2Skipped(line=line, review_id=key, reason="item not in index"))
            continue
        comment = "; ".join(
            p
            for p in (
                notes,
                f"quality: {quality}" if quality else "",
                f"role: {row['curated_role']}" if row.get("curated_role") else "",
            )
            if p
        )
        scan = (item.case_id, item.scan_idx)
        if phase:
            value = phase_value(phase, ctx.vocabulary, ctx.mapping)
            if value is None:
                skipped.append(V2Skipped(line=line, review_id=key, reason=f"phase {phase!r}"))
            elif scan in phase_seen:
                skipped.append(V2Skipped(line=line, review_id=key, reason="phase already set"))
            else:
                phases.append(import_record(ctx.reviewer, *scan, value, "converter_import"))
                phase_seen.add(scan)
        status = _status(keep, quality)
        if status is None:
            if not phase:
                skipped.append(V2Skipped(line=line, review_id=key, reason="no mappable decision"))
            continue
        events.append(
            CurationEvent(
                event_id=new_ulid(),
                at=now,
                reviewer=ctx.reviewer,
                item_id=iid,
                case_id=item.case_id,
                target="seg",
                status=status,
                comment=comment,
                context={"converter_key": key, **item_context(item)},
                source="converter_import",
            )
        )
        seen.add(key)
    return Converted(events, phases, skipped)


def _status(keep: str, quality: str) -> Status | None:
    if keep in FALSE:
        return "rejected"
    if quality in QUALITY:
        return QUALITY[quality]
    if keep in TRUE:
        return "accepted"
    return None
