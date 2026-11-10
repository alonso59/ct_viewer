"""Restoring, saving and closing the Open session of a prepared source operation."""

from __future__ import annotations

import fcntl
import hashlib
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.errors import JobConflict, NotFound
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import utc_now
from app.sources import open as open_mode
from app.sources.open_service import RETRY as OPEN_ACTIONS
from app.tasks.source_inventory import SourceInventory
from app.tasks.source_open import dependency_stat, reader_identity, validate_prepared_open
from app.tasks.source_queries import require_inventory

if TYPE_CHECKING:
    from app.tasks.source_operations import SourceOperations


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
