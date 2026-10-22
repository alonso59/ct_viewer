"""TST-22: required full compatibility fails on missing dependencies or skipped coverage."""

from __future__ import annotations

import os

import pytest

from tools.verify_environment import check


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-full",
        action="store_true",
        default=os.environ.get("RW_TEST_REQUIRE_FULL") == "1",
        help="Require the full radiomics environment and refuse skipped coverage",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    if session.config.getoption("require_full"):
        report = check(full=True)
        if not report["ready"]:
            raise pytest.UsageError(
                "Full test environment is incomplete: " + "; ".join(report["errors"])
            )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if exitstatus or not session.config.getoption("require_full"):
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None and reporter.stats.get("skipped"):
        reporter.write_line("TST-22: required full coverage contains skipped tests", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
