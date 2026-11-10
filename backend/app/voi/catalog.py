"""A `voi.extract` run's `voi_catalog.jsonl`, read once and served in pages.

A run may hold tens of thousands of VOIs, so the API never returns them all: the summary covers
the whole run, the rows are filtered here and cut to a page of scans or cases.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from app.voi.models import VoiCaseRow, VoiResult, VoiScanRow, VoiSummary

MAX_PAGE = 50
CONFIDENCES = ("verified", "probable", "uncertain", "reviewer")


@lru_cache(maxsize=6)
def _read(path: str, mtime_ns: int, size: int) -> tuple[dict[str, Any], ...]:
    with open(path, encoding="utf-8") as f:
        return tuple(json.loads(line) for line in f if line.strip())


def load(output_dir: Path) -> tuple[dict[str, Any], ...]:
    """The catalog rows in file order (the index is the VOI's `n`); cached until it changes."""
    path = output_dir / "voi_catalog.jsonl"
    try:
        st = path.stat()
    except OSError:
        return ()
    return _read(str(path), st.st_mtime_ns, st.st_size)


def needs_review(row: dict[str, Any]) -> bool:
    """An uncertain side, or any warning."""
    return bool(row.get("warnings")) or (
        bool(row.get("side")) and row.get("side_confidence") == "uncertain"
    )


def _case(row: dict[str, Any]) -> str:
    return str(row.get("case_id") or row["item_id"])


def summary(rows: Iterable[dict[str, Any]]) -> VoiSummary:
    cases: set[str] = set()
    scans: set[str] = set()
    by_conf = dict.fromkeys(CONFIDENCES, 0)
    n = n_warn = n_review = 0
    for row in rows:
        n += 1
        cases.add(_case(row))
        scans.add(row["item_id"])
        if row.get("side") and row.get("side_confidence") in by_conf:
            by_conf[row["side_confidence"]] += 1
        n_warn += bool(row.get("warnings"))
        n_review += needs_review(row)
    return VoiSummary(
        n_cases=len(cases),
        n_scans=len(scans),
        n_vois=n,
        by_confidence=by_conf,
        n_warnings=n_warn,
        n_review=n_review,
    )


def _matches(
    row: dict[str, Any],
    q: str,
    confidence: str | None,
    review: bool,
    warning: str | None,
    side: str | None,
    case: str | None,
) -> bool:
    if case and _case(row) != case:
        return False
    if q and q not in f"{_case(row)} {row['item_id']}".lower():
        return False
    if confidence and not (row.get("side") and row.get("side_confidence") == confidence):
        return False
    if review and not needs_review(row):
        return False
    if warning and warning not in (row.get("warnings") or []):
        return False
    return not (side and row.get("side") != side)


def _voi(n: int, row: dict[str, Any]) -> VoiResult:
    return VoiResult(n=n, **{k: v for k, v in row.items() if k in VoiResult.model_fields})


def query(
    rows: tuple[dict[str, Any], ...],
    *,
    view: Literal["scans", "cases"],
    offset: int,
    limit: int,
    q: str = "",
    confidence: str | None = None,
    review: bool = False,
    warning: str | None = None,
    side: str | None = None,
    case: str | None = None,
) -> tuple[int, list[VoiScanRow], list[VoiCaseRow]]:
    """(rows in the filtered view, a page of scans, a page of cases); only the asked view is filled.

    A scan or case is listed when one of its VOIs matches; a scan row carries all its VOIs.
    """
    limit = max(1, min(limit, MAX_PAGE))
    q = q.strip().lower()
    hit = {
        n for n, row in enumerate(rows) if _matches(row, q, confidence, review, warning, side, case)
    }
    if view == "scans":
        scans: dict[str, list[int]] = defaultdict(list)
        for n, row in enumerate(rows):
            scans[row["item_id"]].append(n)
        ids = sorted(i for i, ns in scans.items() if hit.intersection(ns))
        page = [
            VoiScanRow(
                item_id=i,
                case_id=rows[scans[i][0]].get("case_id"),
                phase=rows[scans[i][0]].get("phase"),
                vois=[_voi(n, rows[n]) for n in scans[i]],
            )
            for i in ids[offset : offset + limit]
        ]
        return len(ids), page, []
    grouped: dict[str, list[int]] = defaultdict(list)
    for n in sorted(hit):
        grouped[_case(rows[n])].append(n)
    names = sorted(grouped)
    cases = [
        VoiCaseRow(
            case_id=c,
            n_scans=len({rows[n]["item_id"] for n in grouped[c]}),
            n_vois=len(grouped[c]),
            n_review=sum(needs_review(rows[n]) for n in grouped[c]),
        )
        for c in names[offset : offset + limit]
    ]
    return len(names), [], cases
