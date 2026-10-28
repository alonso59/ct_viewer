"""D10-D13 / DCM-15/16: durable bounded inventory, complete series and cached headers."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
from plugins.dicom import scan

from app.core.errors import JobConflict, SourceMissing
from app.tasks.source_inventory import SourceInventory
from tools.dicom_fixtures import write_series


def test_inventory_reopens_and_reuses_unchanged_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source"
    for index in range(3):
        write_series(root / str(index), shape=(3, 3, 5), marker=(1, 1, 4), series_number=index)
    db = tmp_path / "workspace" / "inventory.sqlite"
    calls: list[Path] = []
    original = scan.image_info

    def tracked(path: Path, source: Path | None = None) -> object:
        calls.append(path)
        return original(path, source)

    monkeypatch.setattr(scan, "image_info", tracked)
    with SourceInventory(db, root) as inventory:
        summary = inventory.scan()
        assert summary["complete"] and summary["dicom"] == 15 and summary["series"] == 3
        first = inventory.page(limit=2)
        assert first["total"] == 3 and first["next_cursor"]
        generation = first["generation"]
    assert len(calls) == 15
    with SourceInventory(db, root) as inventory:
        assert inventory.scan()["complete"]
        assert len(calls) == 15
        last = inventory.page(limit=2, cursor=first["next_cursor"])
        assert last["generation"] == generation and last["next_cursor"] is None
        rows = first["items"] + last["items"]
        assert len({row["key"] for row in rows}) == 3
        for row in rows:
            series = inventory.series(row["key"])
            assert len(series.files) == len(series.headers) == 5
            assert all(
                float(h.ImagePositionPatient[2]) == 100 + k * 2.5
                for k, h in enumerate(series.headers)
            )


def test_inventory_invalidation_rejects_old_page_generation(tmp_path: Path) -> None:
    root = tmp_path / "source"
    for index in range(2):
        write_series(root / str(index), shape=(3, 3, 2), marker=(1, 1, 1), series_number=index)
    with SourceInventory(tmp_path / "state" / "inventory.sqlite", root) as inventory:
        inventory.scan()
        previous = inventory.page(limit=1)
        write_series(root / "new" / "nested", shape=(3, 3, 1), marker=(1, 1, 0), series_number=9)
        (root / "0" / "IM0000.dcm").unlink()
        inventory.scan()
        assert inventory.summary()["dicom"] == 4
        with pytest.raises(JobConflict, match="generation"):
            inventory.page(limit=1, cursor=previous["next_cursor"])


def test_cancelled_inventory_resumes_completed_batches_without_rereading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source"
    write_series(root / "series", shape=(3, 3, 140), marker=(1, 1, 139))
    db = tmp_path / "workspace" / "inventory.sqlite"
    calls: list[Path] = []
    original = scan.image_info

    def tracked(path: Path, source: Path | None = None) -> object:
        calls.append(path)
        return original(path, source)

    monkeypatch.setattr(scan, "image_info", tracked)
    with SourceInventory(db, root) as inventory:
        result = inventory.scan(cancelled=lambda: len(calls) >= 64)
        assert not result["complete"]
        assert inventory.page()["total"] == 0  # no partly inventoried series is advertised
    first_calls = set(calls)
    with SourceInventory(db, root) as inventory:
        result = inventory.scan()
        assert result["complete"] and result["dicom"] == 140
        row = inventory.page()["items"][0]
        assert len(inventory.series(row["key"]).files) == 140
    assert len(calls) == 140
    assert len(first_calls) == 64


def test_inventory_does_not_follow_replaced_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source"
    write_series(root / "patient" / "study", shape=(3, 3, 1), marker=(1, 1, 0))
    private = tmp_path / "private"
    write_series(private / "study", shape=(3, 3, 1), marker=(1, 1, 0), patient_id="outside")
    original = scan.image_info
    replaced = False

    def replace_then_read(path: Path, source: Path | None = None) -> object:
        nonlocal replaced
        if not replaced:
            replaced = True
            (root / "patient").rename(root / "previous")
            (root / "patient").symlink_to(private, target_is_directory=True)
        return original(path, source)

    monkeypatch.setattr(scan, "image_info", replace_then_read)
    with SourceInventory(tmp_path / "state" / "inventory.sqlite", root) as inventory:
        result = inventory.scan()
        assert not result["complete"]
        assert result["dicom"] == 0 and result["errors"] > 0


def test_partial_inventory_never_exposes_a_prefix_of_a_series(tmp_path: Path) -> None:
    root = tmp_path / "source"
    write_series(root / "series", shape=(3, 3, 750), marker=(1, 1, 749))
    with SourceInventory(tmp_path / "state" / "inventory.sqlite", root) as inventory:
        result = inventory.scan(max_files=100)
        assert not result["complete"] and result["limited"]
        assert inventory.page()["total"] == 0
        assert inventory.scan()["complete"]
        row = inventory.page()["items"][0]
        assert row["n_files"] == len(inventory.series(row["key"]).files) == 750


def test_unreadable_subtree_is_partial_and_valid_neighbor_facts_are_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D05: a refused directory cannot become a silently complete inventory."""
    source = tmp_path / "source"
    for name in ("good", "blocked"):
        write_series(source / name, shape=(3, 3, 3), marker=(1, 1, 2), patient_id=name)
    before = {p: p.read_bytes() for p in source.rglob("*.dcm")}
    original = os.scandir

    def unreadable(path: Any) -> Any:
        if path == source / "blocked":
            raise PermissionError("Synthetic directory permission failure")
        return original(path)

    with SourceInventory(tmp_path / "state/inventory.sqlite", source) as inventory:
        with monkeypatch.context() as fault:
            fault.setattr(os, "scandir", unreadable)
            partial = inventory.scan()
            assert not partial["complete"] and partial["errors"] > 0
            assert partial["dicom"] == 3
        complete = inventory.scan()
        assert complete["complete"] and complete["dicom"] == 6
        assert inventory.page()["total"] == 2
    assert before == {p: p.read_bytes() for p in before}


def test_single_file_inventory_never_includes_neighbor_files(tmp_path: Path) -> None:
    root = tmp_path / "source"
    write_series(root, shape=(3, 3, 4), marker=(1, 1, 3))
    chosen = root / "IM0002.dcm"
    with SourceInventory(tmp_path / "workspace" / "inventory.sqlite", chosen) as inventory:
        result = inventory.scan()
        assert result["complete"] and result["dicom"] == 1
        series = inventory.series(inventory.page()["items"][0]["key"])
        assert series.files == (chosen,)


@pytest.mark.parametrize("single_file", [False, True])
def test_cached_history_survives_an_unavailable_source(tmp_path: Path, single_file: bool) -> None:
    root = tmp_path / "source"
    write_series(root, shape=(3, 3, 3), marker=(1, 1, 2))
    selected = root / "IM0001.dcm" if single_file else root
    db = tmp_path / "workspace" / "inventory.sqlite"
    with SourceInventory(db, selected) as inventory:
        inventory.scan()
        previous = inventory.page()
    root.rename(tmp_path / "offline-source")
    with SourceInventory(db, selected) as inventory:
        assert inventory.page() == previous
        with pytest.raises(SourceMissing):
            inventory.scan()


@pytest.mark.parametrize("change", ["header_budget", "scanner", "tags"])
def test_scanner_changes_invalidate_cached_facts_and_page_cursors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root = tmp_path / "source"
    for index in range(2):
        write_series(root / str(index), shape=(3, 3, 2), marker=(1, 1, 1))
    db = tmp_path / "workspace" / "inventory.sqlite"
    with SourceInventory(db, root) as inventory:
        inventory.scan()
        old_page = inventory.page(limit=1)
    calls = []
    original = scan.image_info

    def tracked(path: Path, source: Path | None = None) -> object:
        calls.append(path)
        return original(path, source)

    monkeypatch.setattr(scan, "image_info", tracked)
    if change == "header_budget":
        monkeypatch.setattr(scan, "MAX_HEADER_BYTES", scan.MAX_HEADER_BYTES * 2)
    elif change == "scanner":
        monkeypatch.setattr(scan, "INVENTORY_VERSION", "test-new-scanner")
    else:
        monkeypatch.setattr(scan, "SCAN_TAGS", [*scan.SCAN_TAGS, "ManufacturerModelName"])
    with SourceInventory(db, root) as inventory:
        # Historical pages remain readable; a read alone must not reset the inventory.
        assert inventory.page(limit=1) == old_page
        result = inventory.scan()
        assert result["complete"] and len(calls) == 4
        with pytest.raises(JobConflict, match="generation"):
            inventory.page(limit=1, cursor=old_page["next_cursor"])


def test_inventory_byte_limit_preserves_batches_and_can_continue_with_more_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source"
    write_series(root / "series", shape=(3, 3, 600), marker=(1, 1, 599))
    db = tmp_path / "workspace" / "inventory.sqlite"
    calls = []
    original = scan.image_info

    def tracked(path: Path, source: Path | None = None) -> object:
        calls.append(path)
        return original(path, source)

    monkeypatch.setattr(scan, "image_info", tracked)
    with SourceInventory(db, root) as inventory:
        partial = inventory.scan(max_bytes=1024**2, batch_size=7)
        assert partial["limited"] and not partial["complete"]
        assert partial["limit_reason"] == "inventory_bytes"
        assert 0 < partial["files"] < 600
        assert inventory.page()["items"] == []
        assert inventory.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert (
        sum(p.stat().st_size for p in db.parent.iterdir() if p.name.startswith(db.name)) <= 1024**2
    )
    cached = partial["files"]
    calls.clear()
    with SourceInventory(db, root) as inventory:
        result = inventory.scan(max_bytes=8 * 1024**2, batch_size=7)
        assert result["complete"] and not result["limited"]
        assert len(inventory.series(inventory.page()["items"][0]["key"]).files) == 600
    assert len(calls) <= 600 - cached + 7


def test_inventory_commits_the_configured_batch_before_a_worker_crash(tmp_path: Path) -> None:
    import subprocess

    root = tmp_path / "source"
    write_series(root / "series", shape=(3, 3, 20), marker=(1, 1, 19))
    db = tmp_path / "workspace" / "inventory.sqlite"
    code = """
import os
import sys
from pathlib import Path
from app.tasks.source_inventory import SourceInventory
with SourceInventory(Path(sys.argv[1]), Path(sys.argv[2])) as inventory:
    def progress(counts):
        if counts['files'] == 7:
            os._exit(37)
    inventory.scan(batch_size=7, on_progress=progress)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", code, str(db), str(root)],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        check=False,
    )
    assert crashed.returncode == 37
    with SourceInventory(db, root) as inventory:
        assert inventory.summary()["files"] == 7
        assert inventory.page()["items"] == []
        assert inventory.scan(batch_size=7)["complete"]


def test_inventory_quota_also_covers_many_small_directories(tmp_path: Path) -> None:
    root = tmp_path / "source"
    for index in range(350):
        write_series(root / str(index), shape=(3, 3, 1), marker=(1, 1, 0))
    with SourceInventory(tmp_path / "workspace" / "inventory.sqlite", root) as inventory:
        partial = inventory.scan(max_bytes=1024**2, batch_size=7)
        assert partial["limited"] and not partial["complete"]
        assert 0 < partial["series"] < 350
        assert inventory.scan(max_bytes=8 * 1024**2, batch_size=7)["complete"]
        assert inventory.page()["total"] == 350


def test_inventory_retains_history_when_a_smaller_budget_cannot_fit_it(tmp_path: Path) -> None:
    root = tmp_path / "source"
    write_series(root / "series", shape=(3, 3, 350), marker=(1, 1, 349))
    with SourceInventory(tmp_path / "workspace" / "inventory.sqlite", root) as inventory:
        assert inventory.scan(max_bytes=8 * 1024**2)["complete"]
        previous = inventory.page()
        too_small = inventory.scan(max_bytes=1024**2)
        assert too_small["limited"] and not too_small["complete"]
        assert inventory.page() == previous
        assert inventory.scan(max_bytes=8 * 1024**2)["complete"]


def test_inventory_does_not_grow_wal_behind_a_pinned_reader(tmp_path: Path) -> None:
    root = tmp_path / "source"
    write_series(root / "series", shape=(3, 3, 5), marker=(1, 1, 4))
    db = tmp_path / "workspace" / "inventory.sqlite"
    with SourceInventory(db, root) as inventory, SourceInventory(db, root) as reader:
        assert inventory.scan()["complete"]
        reader.db.execute("BEGIN")
        reader.db.execute("SELECT COUNT(*) FROM files").fetchone()
        partial = inventory.scan(max_bytes=1024**2)
        assert partial["limited"] and not partial["complete"]
        reader.db.rollback()
        assert inventory.scan(max_bytes=1024**2)["complete"]
