"""Case summaries derived from items + warnings (DATA_MODEL.md §Case summary)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from app.ingest.models import CaseSummary, Item, Phase, QcWarning
from app.ingest.normalize import CCRCC_RULES, PhaseRules


def build_cases(
    items: Sequence[Item], warnings: Sequence[QcWarning], rules: PhaseRules = CCRCC_RULES
) -> list[CaseSummary]:
    n_warn = Counter(w.case_id for w in warnings if w.case_id)
    by_case: dict[str, list[Item]] = {}
    for it in items:
        by_case.setdefault(it.case_id, []).append(it)
    out: list[CaseSummary] = []
    for case_id in sorted(by_case):
        all_items = by_case[case_id]
        live = [i for i in all_items if i.status != "excluded_upstream"]
        phases: set[Phase] = {i.phase.canonical for i in live}
        out.append(
            CaseSummary(
                case_id=case_id,
                patient_id=next((i.patient_id for i in all_items if i.patient_id), None),
                phases=rules.order(phases),
                n_scans=len({i.scan_idx for i in live}),
                n_items=len(live),
                has_seg=any(i.scope == "complete" and i.mask is not None for i in live),
                has_voi_L=any(i.scope == "voi" and i.side == "L" for i in live),
                has_voi_R=any(i.scope == "voi" and i.side == "R" for i in live),
                n_warnings=n_warn[case_id],
            )
        )
    return out
