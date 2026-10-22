"""TST-22: full compatibility cannot succeed with skipped coverage."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tools.pytest_gate import pytest_sessionfinish as finish


@pytest.mark.parametrize(
    "required,skips,previous,expected",
    [(True, 1, 0, 1), (True, 0, 0, 0), (True, 1, 2, 2), (False, 1, 0, 0)],
)
def test_full_coverage_gate_preserves_failure_and_refuses_skips(
    required: bool,
    skips: int,
    previous: int,
    expected: int,
) -> None:
    reporter = SimpleNamespace(
        stats={"skipped": [object()] * skips}, write_line=lambda text, **kwargs: None
    )
    config = SimpleNamespace(
        getoption=lambda name: required,
        pluginmanager=SimpleNamespace(get_plugin=lambda name: reporter),
    )
    session: Any = SimpleNamespace(config=config, exitstatus=previous)
    finish(session, previous)
    assert session.exitstatus == expected
