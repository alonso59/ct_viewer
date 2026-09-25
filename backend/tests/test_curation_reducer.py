"""TST-01: CUR-08 reducer, rollup, last-writer-wins (CUR-12), state readers, v2 mapping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.fsio import append_jsonl
from app.core.ids import new_ulid
from app.curation import state as st
from app.curation import v2
from app.curation.models import SEVERITY, CurationEvent
from app.curation.reducer import reduce_events

C1, C2 = "case_00001", "case_00002"
I1, I2 = f"{C1}.01.complete.-", f"{C1}.01.voi.L"


def ev(
    item: str | None, target: str, status: str, at: str = "2026-09-23T10:00:00Z", **kw: Any
) -> CurationEvent:
    case = kw.pop("case_id", item.split(".")[0] if item else C1)
    return CurationEvent.model_validate(
        {
            "event_id": new_ulid(),
            "at": at,
            "reviewer": kw.pop("reviewer", "AP"),
            "item_id": item,
            "case_id": case,
            "target": target,
            "status": status,
            **kw,
        }
    )


def test_last_writer_wins_by_append_order_not_timestamp() -> None:
    red = reduce_events(
        [
            ev(I1, "seg", "rejected", at="2026-09-23T12:00:00Z"),
            ev(I1, "seg", "accepted", at="2026-09-23T09:00:00Z", reviewer="B"),
        ]
    )
    item = red.items()[I1]
    assert item.status == "accepted" and item.reviewer == "B"
    assert red.n_events == 2
    # last_reviewed_at is the newest timestamp seen for the case
    assert red.cases()[C1].last_reviewed_at == "2026-09-23T12:00:00Z"


def test_item_is_worst_over_targets_and_case_is_worst_over_items() -> None:
    red = reduce_events(
        [
            ev(I1, "seg", "accepted"),
            ev(I1, "label:2", "needs_minor_correction", reviewer="X"),
            ev(I2, "voi_mask", "missing"),
            ev(None, "case", "cannot_assess", case_id=C1),
            ev(f"{C2}.01.complete.-", "seg", "accepted"),
        ]
    )
    items = red.items()
    assert items[I1].status == "needs_minor_correction" and items[I1].reviewer == "X"
    assert [t.target for t in items[I1].targets] == ["label:2", "seg"]
    assert items[I2].status == "missing"
    cases = red.cases()
    assert cases[C1].status == "needs_minor_correction"
    assert cases[C1].n_items_reviewed == 2
    assert [t.target for t in cases[C1].targets] == ["case"]
    assert cases[C2].status == "accepted"
    assert None not in items  # case-target events do not create items


def test_case_target_can_dominate_and_ties_go_to_later_event() -> None:
    red = reduce_events(
        [
            ev(I1, "side", "wrong_side_suspected", reviewer="first"),
            ev(I2, "side", "wrong_side_suspected", reviewer="second"),
        ]
    )
    assert "wrong_phase_suspected" not in SEVERITY  # phase is native (ADR-0026)
    assert red.cases()[C1].reviewer == "second"
    red = reduce_events([ev(I1, "seg", "accepted"), ev(None, "case", "rejected", case_id=C1)])
    assert red.cases()[C1].status == "rejected"
    assert red.items()[I1].status == "accepted"


def test_correction_resets_status() -> None:
    red = reduce_events([ev(I1, "seg", "rejected"), ev(I1, "seg", "not_reviewed")])
    assert red.items()[I1].status == "not_reviewed"
    assert red.cases()[C1].status == "not_reviewed"


def test_state_readers_incremental_and_tolerant(tmp_path: Path) -> None:
    pdir = tmp_path / "p"
    assert st.item_statuses(pdir) == {} and st.case_statuses(pdir) == {}
    path = pdir / st.EVENTS
    append_jsonl(path, [ev(I1, "seg", "accepted").model_dump(mode="json")])
    assert st.item_statuses(pdir) == {I1: "accepted"}
    with path.open("a") as fh:
        fh.write("{}\n")  # malformed rows are skipped
        fh.write(json.dumps(ev(I1, "label:1", "rejected").model_dump(mode="json")))  # no \n yet
    assert st.item_statuses(pdir) == {I1: "accepted"}
    with path.open("a") as fh:
        fh.write("\n")
    assert st.item_statuses(pdir) == {I1: "rejected"}
    assert st.case_statuses(pdir) == {C1: ("rejected", "2026-09-23T10:00:00Z")}
    assert len(st.load_events(pdir)) == 2
    path.write_text("")  # replaced/shrunk → full reload
    assert st.item_statuses(pdir) == {}


def test_v2_convert_maps_targets_and_skips_with_reasons() -> None:
    from app.ingest.models import Item, PhaseInfo

    items = {
        I1: Item(
            item_id=I1,
            case_id=C1,
            scan_idx="01",
            scope="complete",
            side="-",
            phase=PhaseInfo(canonical="NP"),
            import_id="I",
        ),
        I2: Item(
            item_id=I2,
            case_id=C1,
            scan_idx="01",
            scope="voi",
            side="L",
            phase=PhaseInfo(canonical="NP"),
            import_id="I",
        ),
    }
    ctx = v2.V2Context(
        items=items,
        case_ids=frozenset({C1}),
        label_values={"foo": 2},
        vocabulary=("NP", "EP"),
        imported_ids=frozenset({"old"}),
        fallback_reviewer="ME",
    )
    header = (
        "review_id,case_id,scan_idx,scope,side,target,status,priority,comment,reviewer,"
        "reviewed_at,proposed_phase\n"
    )
    body = (
        f"r1,{C1},01,complete,,SEG,accepted,high,ok,AP,2026-01-02T10:00:00+00:00,\n"
        f"r2,{C1},1,voi,L,foo_mask,needs_minor_correction,,,,2026-01-01T10:00:00,ep\n"
        f"r3,{C1},,,,SEG,needs_minor_correction,low,,AP,2026-01-03T10:00:00Z,XX\n"
        f"old,{C1},01,complete,,SEG,accepted,,,,2026-01-01T00:00:00Z,\n"
        f"r5,{C1},01,complete,,SEG,bogus,,,,2026-01-01T00:00:00Z,\n"
        f"r6,case_09999,01,complete,,SEG,accepted,,,,2026-01-01T00:00:00Z,\n"
        f"r7,{C1},01,complete,,bar_mask,accepted,,,,2026-01-01T00:00:00Z,\n"
        f"r8,{C1},02,complete,,SEG,accepted,,,,2026-01-01T00:00:00Z,\n"
        f"r9,{C1},01,complete,,SEG,accepted,,,,not-a-date,\n"
        f"r1,{C1},01,complete,,SEG,accepted,,,,2026-01-01T00:00:00Z,\n"
    )
    out = v2.convert(v2.parse_rows((header + body).encode()), ctx)
    events, skipped = out.events, out.skipped
    assert out.phases == []
    assert [e.context["v2_review_id"] for e in events] == ["r2", "r1", "r3"]  # by reviewed_at
    r2, r1, r3 = events
    assert r1.item_id == I1 and r1.target == "seg" and r1.priority == "high"
    assert r2.item_id == I2 and r2.target == "label:2" and r2.reviewer == "ME"
    assert r2.context["v2_proposed_phase"] == "EP" and r2.at == "2026-01-01T10:00:00Z"
    assert r3.item_id is None and r3.target == "case"
    assert r3.context["v2_proposed_phase"] == "XX"
    assert all(e.source == "v2_import" for e in events)
    reasons = {s.review_id: s.reason for s in skipped}
    assert reasons == {
        "old": "already imported",
        "r5": "unknown status 'bogus'",
        "r6": "case 'case_09999' not in index",
        "r7": "unmapped target 'bar_mask'",
        "r8": "item not in index",
        "r9": "invalid reviewed_at",
        "r1": "already imported",
    }
    assert {s.line for s in skipped} == {5, 6, 7, 8, 9, 10, 11}
