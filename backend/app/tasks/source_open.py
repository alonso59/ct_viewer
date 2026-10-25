"""SRC-18 / ADR-0035: recoverable whole-unit Open headers in the managed inventory."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from importlib.metadata import version
from pathlib import Path
from typing import Any

from app.core.errors import JobConflict
from app.sources import formats
from app.sources import open as open_mode
from app.tasks import dicom_stage
from app.tasks.source_inventory import SourceInventory


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
    for row in inventory.db.execute(
        "SELECT rel, kind FROM files WHERE kind IN ('nifti', 'npy') ORDER BY rel"
    ):
        yield "file:" + row["rel"], row["kind"], [row["rel"]]
    for group in inventory.db.execute(
        "SELECT directory, uid, series_key FROM files WHERE kind='dicom' "
        "GROUP BY directory, uid ORDER BY directory, uid"
    ):
        rels = [
            str(row[0])
            for row in inventory.db.execute(
                "SELECT rel FROM files WHERE series_key=? AND kind='dicom' ORDER BY rel",
                (group["series_key"],),
            )
        ]
        yield "series:" + group["series_key"], "dicom", rels


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
        row = inventory.db.execute("SELECT signature FROM files WHERE rel=?", (rel,)).fetchone()
        saved = json.loads(row[0])
        st = path.stat(follow_symlinks=False)
        if saved[1:] != [st.st_size, st.st_mtime_ns, st.st_dev, st.st_ino]:
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
