"""D08/D10/D12, SRC-18: durable Open headers retain only whole verified units."""

import hashlib
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.sources import formats
from app.sources import open as open_mode
from app.tasks.source_inventory import SourceInventory
from app.tasks.source_open import prepare_open
from tests.test_sources import ct, nii
from tools.dicom_fixtures import write_series


def test_interrupted_open_reuses_completed_headers_and_keeps_complete_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    nii(source / "a.nii.gz", ct())
    nii(source / "b.nii.gz", ct())
    write_series(source / "nested" / "dicom", shape=(3, 3, 3), marker=(1, 1, 2))
    calls: list[list[str]] = []
    probe = open_mode.probe

    def tracked(
        root: str,
        rels: list[str],
        kinds: dict[str, formats.Kind] | None = None,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[dict[str, Any]]:
        calls.append(rels)
        return probe(root, rels, kinds, cancelled=cancelled)

    monkeypatch.setattr(open_mode, "probe", tracked)
    with SourceInventory(tmp_path / "state" / "inventory.sqlite", source) as inventory:
        inventory.scan()
        progress: list[dict[str, Any]] = []
        first = prepare_open(
            inventory, cancelled=lambda: bool(progress), on_progress=progress.append
        )
        assert first is None and len(calls) == 1
    with SourceInventory(tmp_path / "state" / "inventory.sqlite", source) as inventory:
        inventory.scan()
        session = prepare_open(inventory)
        assert session is not None
        assert len(calls) == 3  # first NIfTI header is recovered, never probed again
        assert [item.format for item in session.items] == ["nifti", "nifti", "dicom"]
        assert len(session.items[-1].files) == 3 and session.items[-1].n_slices == 3
        again = prepare_open(inventory)
        assert again is not None and len(calls) == 3


def test_changed_source_invalidates_its_open_header_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    nii(source / "a.nii.gz", ct())
    nii(source / "b.nii.gz", ct())
    calls: list[list[str]] = []
    probe = open_mode.probe

    def tracked(
        root: str,
        rels: list[str],
        kinds: dict[str, formats.Kind] | None = None,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[dict[str, Any]]:
        calls.append(rels)
        return probe(root, rels, kinds, cancelled=cancelled)

    monkeypatch.setattr(open_mode, "probe", tracked)
    with SourceInventory(tmp_path / "state" / "inventory.sqlite", source) as inventory:
        inventory.scan()
        assert prepare_open(inventory) is not None
        nii(source / "b.nii.gz", ct()[:2, :3, :4])
        inventory.scan()
        session = prepare_open(inventory)
        assert session is not None
        assert calls == [["a.nii.gz"], ["b.nii.gz"], ["b.nii.gz"]]
        assert session.items[1].geometry is not None
        assert session.items[1].geometry.shape == [2, 3, 4]


def test_sigkill_after_a_header_commit_recovers_without_reading_that_header_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    nii(source / "a.nii.gz", ct())
    nii(source / "b.nii.gz", ct())
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    database = tmp_path / "state" / "inventory.sqlite"
    backend = Path(__file__).resolve().parents[1]
    code = """
import os, signal, sys
from pathlib import Path
from app.tasks.source_inventory import SourceInventory
from app.tasks.source_open import prepare_open
with SourceInventory(Path(sys.argv[1]), Path(sys.argv[2])) as inventory:
    inventory.scan()
    prepare_open(inventory, on_progress=lambda _: os.kill(os.getpid(), signal.SIGKILL))
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(database), str(source)],
        cwd=backend,
        env={**os.environ, "PYTHONPATH": f"{backend}:{backend.parent}"},
        capture_output=True,
        timeout=30,
    )
    assert process.returncode == -signal.SIGKILL, process.stderr.decode()
    probe = open_mode.probe

    def checked(root: str, rels: list[str], *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        assert rels == ["b.nii.gz"], "a committed header was re-read after actual SIGKILL"
        return probe(root, rels, *args, **kwargs)

    monkeypatch.setattr(open_mode, "probe", checked)
    with SourceInventory(database, source) as inventory:
        inventory.scan()
        session = prepare_open(inventory)
        assert session is not None and len(session.items) == 2
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}


def test_cancelling_inside_a_series_never_caches_a_partial_series(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_series(source / "series", shape=(3, 3, 6), marker=(1, 1, 5))
    checks = 0

    def cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 6

    with SourceInventory(tmp_path / "state" / "inventory.sqlite", source) as inventory:
        inventory.scan()
        assert prepare_open(inventory, cancelled=cancel) is None
        assert inventory.db.execute("SELECT COUNT(*) FROM open_headers").fetchone()[0] == 0
        session = prepare_open(inventory)
        assert session is not None and len(session.items) == 1
        assert len(session.items[0].files) == 6


@pytest.mark.parametrize("header_number", [1, 3, 6])
def test_sigkill_during_series_headers_preserves_only_whole_committed_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, header_number: int
) -> None:
    """D13/D18, SRC-18: actual process death must not persist partial series geometry."""
    source = tmp_path / "source"
    nii(source / "a.nii.gz", ct())
    write_series(source / "series", shape=(3, 3, 6), marker=(1, 1, 5))
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()
    }
    database = tmp_path / "state" / "inventory.sqlite"
    backend = Path(__file__).resolve().parents[1]
    code = """
import os, signal, sys
from pathlib import Path
from app.tasks.source_inventory import SourceInventory
from app.tasks.source_open import prepare_open
from plugins.dicom import scan
with SourceInventory(Path(sys.argv[1]), Path(sys.argv[2])) as inventory:
    inventory.scan()
    original = scan.read_header
    calls = 0
    def read(*args, **kwargs):
        global calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == int(sys.argv[3]):
            print(f"stopping after DICOM header {calls}", flush=True)
            os.kill(os.getpid(), signal.SIGKILL)
        return result
    scan.read_header = read
    prepare_open(inventory)
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(database), str(source), str(header_number)],
        cwd=backend,
        env={**os.environ, "PYTHONPATH": f"{backend}:{backend.parent}"},
        capture_output=True,
        timeout=30,
    )
    assert process.returncode == -signal.SIGKILL, process.stderr.decode()
    assert f"stopping after DICOM header {header_number}" in process.stdout.decode()
    probe = open_mode.probe
    probed: list[list[str]] = []

    def tracked(root: str, rels: list[str], *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        probed.append(rels)
        assert "a.nii.gz" not in rels, "the committed NIfTI header was unnecessarily re-read"
        return probe(root, rels, *args, **kwargs)

    monkeypatch.setattr(open_mode, "probe", tracked)
    with SourceInventory(database, source) as inventory:
        assert (
            inventory.db.execute("SELECT unit FROM open_headers").fetchall()[0][0]
            == "file:a.nii.gz"
        )
        assert inventory.db.execute("SELECT COUNT(*) FROM open_headers").fetchone()[0] == 1
        inventory.scan()
        session = prepare_open(inventory)
        assert session is not None and len(session.items) == 2
        series = session.items[1]
        assert len(probed) == 1 and len(probed[0]) == 6
        assert series.format == "dicom" and len(series.files) == series.n_slices == 6
        assert series.geometry is not None and series.geometry.shape == [3, 3, 6]
        assert inventory.db.execute("SELECT COUNT(*) FROM open_headers").fetchone()[0] == 2
    assert before == {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()
    }


def test_changed_reader_invalidates_cached_open_geometry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tasks import source_open

    source = tmp_path / "source"
    nii(source / "a.nii.gz", ct())
    with SourceInventory(tmp_path / "state" / "inventory.sqlite", source) as inventory:
        inventory.scan()
        assert prepare_open(inventory) is not None
        monkeypatch.setattr(source_open, "reader_identity", lambda: "changed-reader")
        calls: list[str] = []
        original = open_mode.probe

        def checked(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            calls.append("probe")
            return original(*args, **kwargs)

        monkeypatch.setattr(open_mode, "probe", checked)
        assert prepare_open(inventory) is not None
        assert calls == ["probe"]


def test_open_inventory_and_journal_are_private_to_the_owner(tmp_path: Path) -> None:
    """NFR-17: cached source names/header facts must not inherit a public process umask."""
    source = tmp_path / "source"
    nii(source / "a.nii.gz", ct())
    database = tmp_path / "state" / "inventory.sqlite"
    with SourceInventory(database, source) as inventory:
        inventory.scan()
        assert prepare_open(inventory) is not None
        for file in database.parent.iterdir():
            if file.is_file():
                assert file.stat().st_mode & 0o077 == 0, file.name


def test_prepared_open_validation_reads_no_image_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SRC-19 / BE-12: hydration validates pins rather than repeating native probing."""
    from app.tasks.source_open import validate_prepared_open

    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    write_series(source / "series", shape=(3, 3, 3), marker=(1, 1, 2))
    with SourceInventory(tmp_path / "state/inventory.sqlite", source) as inventory:
        inventory.scan()
        session = prepare_open(inventory)
        assert session is not None

        def forbidden(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Hydration re-read image headers")

        monkeypatch.setattr(open_mode, "probe", forbidden)
        validate_prepared_open(inventory, inventory.summary()["generation"], session)
