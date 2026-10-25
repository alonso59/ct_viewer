"""One definition per count, shared by the import preview, the project summary and the index
status so that every place showing counts agrees.

A case counts when it has at least one row or item that is not excluded upstream; excluded rows
are counted only under "excluded upstream".
"""

from __future__ import annotations

from collections.abc import Iterable

EXCLUDED = "excluded_upstream"


def split_cases(rows: Iterable[tuple[str, bool]]) -> tuple[set[str], set[str]]:
    """`(case_id, excluded)` rows → (counted cases, cases whose every row is excluded)."""
    counted: set[str] = set()
    seen: set[str] = set()
    for case_id, excluded in rows:
        seen.add(case_id)
        if not excluded:
            counted.add(case_id)
    return counted, seen - counted


def split_items(statuses: Iterable[str]) -> tuple[int, int]:
    """Item statuses → (counted items, items excluded upstream)."""
    n = n_excluded = 0
    for s in statuses:
        if s == EXCLUDED:
            n_excluded += 1
        else:
            n += 1
    return n, n_excluded
