"""PRJ-06: a concurrent registry addition cannot invalidate an in-progress list response."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.projects.models import ProjectSummary
from tests.test_api_ingest import ctx_of


def test_listing_snapshots_entries_before_reading_summaries(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = [
        client.post("/api/v1/projects", json={"name": name}).json()["project_id"]
        for name in ("one", "two", "added while reading")
    ]
    workspace = ctx_of(client).workspace
    entries = dict(workspace._entries())
    added = entries.pop(ids[2])
    monkeypatch.setattr(workspace, "_entries", lambda: entries)
    summary = workspace.summary

    def add_during_read(pid: str) -> ProjectSummary:
        entries[ids[2]] = added
        return summary(pid)

    monkeypatch.setattr(workspace, "summary", add_during_read)
    first = client.get("/api/v1/projects")
    assert first.status_code == 200
    assert {row["project_id"] for row in first.json()} == set(ids[:2])
    assert {row["project_id"] for row in client.get("/api/v1/projects").json()} == set(ids)
