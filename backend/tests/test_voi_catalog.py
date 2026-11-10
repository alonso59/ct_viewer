"""Paging, filters and the summary over a run's VOI catalog (large runs)."""

from __future__ import annotations

import json
from pathlib import Path

from app.voi import catalog


def row(
    case: str, scan: int, side: str, conf: str, warnings: list[str] | None = None, phase: str = "NP"
) -> dict:
    return {
        "item_id": f"{case}.{scan:02d}.complete.-",
        "case_id": case,
        "phase": phase,
        "side": side,
        "candidate": side,
        "region": "kidney",
        "labels": ["kidney"],
        "image": "x.nii.gz",
        "mask": "y.nii.gz",
        "shape": [1, 1, 1],
        "spacing": [1.0, 1.0, 1.0],
        "crop_size_mm": [1.0, 1.0, 1.0],
        "volume_ml": 1.0,
        "warnings": warnings or [],
        "side_confidence": conf,
    }


def write(tmp_path: Path, rows: list[dict]) -> tuple[dict, ...]:
    (tmp_path / "voi_catalog.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return catalog.load(tmp_path)


def test_many_cases_one_scan_each(tmp_path: Path) -> None:
    rows = []
    for i in range(500):
        c = f"case_{i:04d}"
        rows += [
            row(c, 1, "R", "verified"),
            row(c, 1, "L", "uncertain" if i % 100 == 0 else "verified"),
        ]
    loaded = write(tmp_path, rows)
    s = catalog.summary(loaded)
    assert (s.n_cases, s.n_scans, s.n_vois) == (500, 500, 1000)
    assert s.by_confidence["uncertain"] == 5 and s.n_review == 5
    total, page, _ = catalog.query(loaded, view="scans", offset=0, limit=50)
    assert total == 500 and len(page) == 50 and page[0].item_id.startswith("case_0000")
    assert len(page[0].vois) == 2  # a scan row carries all its VOIs
    total, page, _ = catalog.query(
        loaded, view="scans", offset=450, limit=50, confidence="uncertain"
    )
    assert total == 5 and page == []  # five scans match; the page is past them
    total, page, _ = catalog.query(loaded, view="scans", offset=0, limit=50, review=True)
    assert total == 5 and next(p.case_id for p in page) == "case_0000"
    total, page, _ = catalog.query(loaded, view="scans", offset=0, limit=50, q="case_0123")
    assert total == 1


def test_few_cases_many_scans(tmp_path: Path) -> None:
    rows = []
    for c in range(40):
        for k in range(125):
            rows.append(
                row(f"case_{c:02d}", k, "R", "probable", ["at_image_edge"] if k == 7 else [])
            )
    loaded = write(tmp_path, rows)
    total, _, cases = catalog.query(loaded, view="cases", offset=0, limit=50)
    assert total == 40 and cases[0].n_scans == 125 and cases[0].n_review == 1
    total, scans, _ = catalog.query(loaded, view="scans", offset=100, limit=50, case="case_03")
    assert total == 125 and len(scans) == 25 and all(s.case_id == "case_03" for s in scans)
    total, _, cases = catalog.query(
        loaded, view="cases", offset=0, limit=50, warning="at_image_edge"
    )
    assert total == 40 and all(c.n_vois == 1 for c in cases)  # counts follow the filter


def test_filters_by_side_and_confidence_need_a_side(tmp_path: Path) -> None:
    loaded = write(
        tmp_path, [row("a", 1, "L", "verified"), row("a", 2, "", ""), row("b", 1, "R", "reviewer")]
    )
    assert catalog.query(loaded, view="scans", offset=0, limit=50, side="R")[0] == 1
    assert catalog.query(loaded, view="scans", offset=0, limit=50, confidence="reviewer")[0] == 1
    assert catalog.query(loaded, view="scans", offset=0, limit=50, confidence="verified")[0] == 1
    assert catalog.summary(loaded).by_confidence == {
        "verified": 1,
        "probable": 0,
        "uncertain": 0,
        "reviewer": 1,
    }


def test_catalog_is_cached_until_it_changes(tmp_path: Path) -> None:
    first = write(tmp_path, [row("a", 1, "L", "verified")])
    assert catalog.load(tmp_path) is first
    second = write(tmp_path, [row("a", 1, "L", "verified"), row("b", 1, "R", "verified")])
    assert len(second) == 2
    assert catalog.load(tmp_path / "missing") == ()
