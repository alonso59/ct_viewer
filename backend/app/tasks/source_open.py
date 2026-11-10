"""Recoverable whole-unit Open headers in the managed inventory."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Iterator
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rw_dicom.inventory import stat_identity

from app.core.errors import JobConflict, NotFound
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import utc_now
from app.sources import formats
from app.sources import open as open_mode
from app.sources.open_service import RETRY as OPEN_ACTIONS
from app.tasks import dicom_stage
from app.tasks.source_inventory import SourceInventory
from app.tasks.source_queries import require_inventory

if TYPE_CHECKING:
    from app.tasks.source_operations import SourceOperations


def reader_identity() -> str:
    """Invalidate cached geometry on reader or probing-code changes."""
    from app.imaging import header, npy_convert

    files = (
        __file__,
        open_mode.__file__,
        dicom_stage.__file__,
        header.__file__,
        npy_convert.__file__,
    )
    return hashlib.sha256(
        json.dumps(
            {
                "versions": {p: version(p) for p in ("nibabel", "numpy", "pydicom", "SimpleITK")},
                "code": [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files if p],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def units(inventory: SourceInventory) -> Iterator[tuple[str, formats.Kind, list[str]]]:
    for kind in ("nifti", "npy"):
        for rel in inventory.rels(kind):
            yield "file:" + rel, kind, [rel]
    for key, rels in inventory.dicom_units():
        yield "series:" + key, "dicom", rels


def dependency_stat(root: Path, path: Path) -> list[int] | None:
    """Pin optional geometry inputs, including their absence, without reading pixels."""
    try:
        st = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not dicom_stage.local_source_file(root, path):
        raise JobConflict("Open geometry dependency is not a local source file")
    return [st.st_size, st.st_mtime_ns, st.st_dev, st.st_ino]


def numpy_dependencies(root: Path, path: Path) -> dict[str, Any]:
    from app.imaging import npy_convert

    sidecar = path.with_name(path.name + ".json")
    result: dict[str, Any] = {"sidecar": dependency_stat(root, sidecar)}
    if result["sidecar"] is not None:
        reference = npy_convert.read_sidecar(path).get("reference_ref")
        if isinstance(reference, str):
            target = (path.parent / reference).resolve()
            if target.is_relative_to(root.resolve()):
                result["reference"] = [
                    str(target.relative_to(root.resolve())),
                    dependency_stat(root, target),
                ]
    return result


def signature(inventory: SourceInventory, rels: list[str]) -> str:
    digest = hashlib.sha256()
    for rel in rels:
        path = inventory.root / rel
        if not dicom_stage.local_source_file(inventory.root, path):
            raise JobConflict("Open source moved outside its guarded root; discover it again")
        row = inventory.entry(rel)
        if row is None:
            raise JobConflict("Open source changed after discovery; resume discovery again")
        saved = [inventory.scanner, *row[2:]]
        st = path.stat(follow_symlinks=False)
        if tuple(saved[1:]) != stat_identity(st):
            raise JobConflict("Open source changed after discovery; resume discovery again")
        digest.update(json.dumps([rel, saved], separators=(",", ":")).encode())
        if path.suffix.lower() == ".npy":
            digest.update(
                json.dumps(numpy_dependencies(inventory.root, path), sort_keys=True).encode()
            )
    return digest.hexdigest()


def validate_prepared_open(
    inventory: SourceInventory, generation: str, session: open_mode.OpenSession
) -> None:
    """Check the prepared input snapshot on hydration; never re-probe image headers."""
    summary = inventory.summary()
    if not summary["complete"] or summary["generation"] != generation:
        raise JobConflict("Open inventory changed; open the source again")
    identity = reader_identity()
    geometry = {
        item.rel
        for item in session.items
        if item.kind == "image" and item.geometry is not None and not item.error
    }
    remaining = set(geometry)
    for key, _kind, rels in units(inventory):
        remaining.difference_update(rels)
        pin = signature(inventory, rels)
        cached = inventory.db.execute(
            "SELECT signature, reader FROM open_headers WHERE unit=?", (key,)
        ).fetchone()
        if (cached is None and any(rel in geometry for rel in rels)) or (
            cached is not None and (cached[0] != pin or cached[1] != identity)
        ):
            raise JobConflict("Prepared Open geometry inputs changed; open the source again")
    if remaining:
        raise JobConflict("Prepared Open inventory lost image pins; open the source again")


def prepare_open(
    inventory: SourceInventory,
    *,
    cancelled: Callable[[], bool] = lambda: False,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> open_mode.OpenSession | None:
    """Return only a complete session; interrupted units never become cached geometry.

    NumPy is re-probed because its geometry can reference external sidecars/volumes.
    The inventory's existing SQLite page quota also bounds this additive header table.
    """
    summary = inventory.summary()
    if not summary["complete"]:
        raise JobConflict("Finish source discovery before preparing Open headers")
    inventory.db.execute(
        "CREATE TABLE IF NOT EXISTS open_headers (unit TEXT PRIMARY KEY, signature TEXT NOT NULL, "
        "reader TEXT NOT NULL, rows TEXT NOT NULL)"
    )
    identity = reader_identity()
    rows: list[dict[str, Any]] = []
    total = summary["nifti"] + summary["npy"] + summary["series"]
    for done, (key, kind, rels) in enumerate(units(inventory), 1):
        if cancelled():
            return None
        pin = signature(inventory, rels)
        cached = inventory.db.execute(
            "SELECT rows FROM open_headers WHERE unit=? AND signature=? AND reader=?",
            (key, pin, identity),
        ).fetchone()
        if cached is not None and kind != "npy":
            current = json.loads(cached[0])
        else:
            try:
                current = open_mode.probe(
                    str(inventory.root), rels, dict.fromkeys(rels, kind), cancelled=cancelled
                )
            except InterruptedError:
                return None
            if cancelled():
                return None
            if signature(inventory, rels) != pin:
                raise JobConflict("Open source changed while reading its headers")
            # Persist before reporting progress: cancellation/restart can reuse this whole unit.
            if not any(row.get("error") for row in current):
                inventory.db.execute(
                    "INSERT OR REPLACE INTO open_headers VALUES (?, ?, ?, ?)",
                    (key, pin, identity, json.dumps(current)),
                )
                inventory.db.commit()
        rows.extend(current)
        if on_progress is not None:
            on_progress({"t": "stage", "stage": "opening", "done": done, "total": total})
    if cancelled():
        return None
    if not rows:
        raise open_mode.refuse_empty(inventory.source, formats.Scan(inventory.root))
    return open_mode.build_session(
        inventory.source,
        rows,
        formats.Scan(inventory.root),
        open_mode.row_modalities(inventory.root),
    )


def open_session(
    operations: SourceOperations, operation: str, *, reopen: bool = False
) -> open_mode.OpenSession:
    operations.get(operation)
    descriptor = os.open(
        operations._dir(operation) / "inventory-use.lock",
        os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise JobConflict("Open state is being updated; retry opening the source") from None
        return _load_open_session(operations, operation, reopen=reopen)
    finally:
        os.close(descriptor)


def _load_open_session(
    operations: SourceOperations, operation: str, *, reopen: bool = False
) -> open_mode.OpenSession:
    """Restore an explicitly prepared Open result; conversion records stay separate."""
    record = operations.get(operation)
    require_inventory(record)
    if record.purpose != "open":
        raise NotFound("This operation has no Open session")
    if record.stage != "opened" or record.status != "completed" or not record.cleanup_verified:
        raise JobConflict(
            "Finish or resume source opening before viewing its result", actions=OPEN_ACTIONS
        )
    operations.guard.check(Path(record.source))
    directory = operations._dir(operation)
    closed = directory / "open-closed.json"
    if closed.exists() and not reopen:
        raise NotFound("This Open session was closed", actions=["choose_another_path", "home"])
    artifact = operations._attempt_dir(record) / "open-session.json"
    try:
        raw = artifact.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record.summary.get(
            "open_session_sha256"
        ) or reader_identity() != record.summary.get("open_reader"):
            raise JobConflict(
                "Open result changed or its reader is incompatible; open the source again",
                actions=OPEN_ACTIONS,
            )
        session = open_mode.OpenSession.model_validate_json(raw)
        prepared = session
        state = directory / "open-session-state.json"
        if state.exists():
            saved = read_json(state)
            if (
                saved.get("version") != 2
                or saved.get("base_sha256") != record.summary["open_session_sha256"]
            ):
                raise JobConflict(
                    "Saved Open state is incompatible; open the source again",
                    actions=OPEN_ACTIONS,
                )
            session = open_mode.OpenSession.model_validate(saved["session"])
            if saved.get("label_inputs") != _open_label_inputs(operations, session):
                raise JobConflict(
                    "Attached Open mask changed; attach it again", actions=OPEN_ACTIONS
                )
    except (OSError, ValueError, KeyError):
        raise JobConflict(
            "Open result is unreadable; open the source again", actions=OPEN_ACTIONS
        ) from None
    if session.sid != operation or session.path != record.source:
        raise JobConflict("Open result belongs to a different source", actions=OPEN_ACTIONS)
    database = directory / "inventory.sqlite"
    try:
        if not database.is_file():
            raise JobConflict("Prepared Open inventory is missing")
        with SourceInventory(database, Path(record.source)) as inventory:
            validate_prepared_open(inventory, record.summary["generation"], prepared)
    except (OSError, sqlite3.Error, JobConflict, KeyError, ValueError) as exc:
        raise JobConflict(
            "Prepared Open inputs changed or are unavailable; open the source again",
            actions=OPEN_ACTIONS,
        ) from exc
    if reopen:
        closed.unlink(missing_ok=True)
    return session


def _open_label_inputs(
    operations: SourceOperations, session: open_mode.OpenSession
) -> dict[str, list[int]]:
    pins = {}
    for item in session.items:
        if item.kind != "label":
            continue
        path = open_mode.source_path(session, item)
        operations.guard.check(path)
        try:
            pin = dependency_stat(path.parent, path)
        except (OSError, JobConflict):
            raise JobConflict(
                "Attached Open mask is unavailable; attach it again", actions=OPEN_ACTIONS
            ) from None
        if pin is None:
            raise JobConflict(
                "Attached Open mask is missing; attach it again", actions=OPEN_ACTIONS
            )
        pins[item.rel] = pin
    return pins


def save_open_session(operations: SourceOperations, session: open_mode.OpenSession) -> None:
    try:
        record = operations.get(session.sid)
    except NotFound:
        return  # compatibility Open sessions are intentionally ephemeral
    if record.purpose == "open":
        atomic_write_json(
            operations._dir(session.sid) / "open-session-state.json",
            {
                "version": 2,
                "label_inputs": _open_label_inputs(operations, session),
                "base_sha256": record.summary.get("open_session_sha256"),
                "session": session.model_dump(mode="json"),
            },
        )


def close_open_session(operations: SourceOperations, operation: str) -> None:
    try:
        record = operations.get(operation)
    except NotFound:
        return
    if record.purpose == "open":
        atomic_write_json(operations._dir(operation) / "open-closed.json", {"closed_at": utc_now()})
