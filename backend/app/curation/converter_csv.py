"""CUR-15: the standalone converter's `curation.csv` (DCM-08/09) → events, once.

Columns used: case_id, scan_idx, curated_keep, curated_role, curated_phase, curated_quality,
notes. One event per row with a manual value (`source: "converter_import"`):
- `curated_phase` → target `phase`, `proposed_phase` (vocabulary value), status
  `wrong_phase_suspected` when it differs from the indexed phase, else `accepted`;
- otherwise target `seg`: `curated_keep` false → `rejected`; quality poor/bad → needs major,
  fair → needs minor correction; `curated_keep` true or quality good → `accepted`;
- `notes` (and quality/role) become the comment. Rows already imported are skipped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.core.ids import new_ulid, utc_now
from app.curation.models import CurationEvent, Status, V2Skipped
from app.curation.v2 import item_context, parse_rows
from app.ingest.models import Item
from app.projects.presets import normalize_phase_value

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


def parse(data: bytes) -> list[tuple[int, dict[str, str]]]:
    return parse_rows(data, REQUIRED, "Not a converter curation.csv")


def convert(
    rows: Sequence[tuple[int, dict[str, str]]], ctx: ConverterContext
) -> tuple[list[CurationEvent], list[V2Skipped]]:
    events: list[CurationEvent] = []
    skipped: list[V2Skipped] = []
    seen = set(ctx.imported)
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
        context: dict[str, Any] = {"converter_key": key, **item_context(item)}
        target, status, proposed = "seg", _status(keep, quality), None
        if phase:
            target = "phase"
            proposed = normalize_phase_value(phase, list(ctx.vocabulary), dict(ctx.mapping))
            status = "accepted" if proposed == item.phase.canonical else "wrong_phase_suspected"
            context["converter_phase"] = phase
        if status is None:
            skipped.append(V2Skipped(line=line, review_id=key, reason="no mappable decision"))
            continue
        events.append(
            CurationEvent(
                event_id=new_ulid(),
                at=now,
                reviewer=ctx.reviewer,
                item_id=iid,
                case_id=item.case_id,
                target=target,
                status=status,
                comment=comment,
                proposed_phase=proposed,
                context=context,
                source="converter_import",
            )
        )
        seen.add(key)
    return events, skipped


def _status(keep: str, quality: str) -> Status | None:
    if keep in FALSE:
        return "rejected"
    if quality in QUALITY:
        return QUALITY[quality]
    if keep in TRUE:
        return "accepted"
    return None
