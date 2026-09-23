"""Derived curation state readers shared with other services (analytics DB-02/07, ingest).

Contract (lane 2): pure functions over a project folder; no API-process state needed.
"""

from __future__ import annotations

from pathlib import Path


def item_statuses(project_dir: Path) -> dict[str, str]:
    """Latest QC status per item_id (worst over the item's targets, CUR-08)."""
    raise NotImplementedError


def case_statuses(project_dir: Path) -> dict[str, tuple[str, str | None]]:
    """Case rollup per case_id → (worst status, last_reviewed_at) (CUR-08)."""
    raise NotImplementedError
