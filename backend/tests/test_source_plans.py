"""D12 / DCM-16: complete filtered plans beyond 1,000 series and fenced pagination."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import JobConflict, ValidationProblem
from app.tasks.source_plans import read_plan_page, write_plan


def test_complete_plan_pages_and_filters_across_chunk_boundaries(tmp_path: Path) -> None:
    rows = [
        {
            "case_id": f"case_{index:05d}",
            "scan_idx": "01",
            "n_files": 12,
            "action": "convert" if index % 2 == 0 else "skip",
            "reason": "" if index % 2 == 0 else "localizer",
            "bytes": 100 if index % 2 == 0 else 0,
        }
        for index in range(1027)
    ]
    root = tmp_path / "workspace" / "plan"
    generation = write_plan(root, rows)
    for action in [None, "convert", "skip"]:
        cursor = None
        cases = []
        while True:
            page = read_plan_page(root, limit=127, cursor=cursor, action=action)
            assert len(page.items) <= 127 and page.generation == generation
            cases.extend(row.case_id for row in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        expected = [row["case_id"] for row in rows if action is None or row["action"] == action]
        assert cases == expected and page.total == len(expected)
    old = read_plan_page(root, limit=1)
    with pytest.raises(JobConflict, match="generation"):
        read_plan_page(root, limit=1, cursor=old.next_cursor, action="skip")
    write_plan(root, rows[:3])
    with pytest.raises(JobConflict, match="generation"):
        read_plan_page(root, limit=1, cursor=old.next_cursor)


@pytest.mark.parametrize("cursor", ["invalid", "W10=", "eyJhIjoxfQ==", "bnVsbA=="])
def test_bad_plan_cursor_is_a_validation_problem(tmp_path: Path, cursor: str) -> None:
    write_plan(tmp_path / "plan", [])
    with pytest.raises(ValidationProblem):
        read_plan_page(tmp_path / "plan", cursor=cursor)
