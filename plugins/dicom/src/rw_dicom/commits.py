"""Verified, no-clobber publication and recovery of one series artifact set."""

from __future__ import annotations

import contextlib
import fcntl
import gzip
import hashlib
import io
import json
import math
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from rw_dicom import convert, files, sidecar
from rw_dicom.scan import Series

CHUNK = 1024 * 1024
# Settings that change a series' artifacts; selection settings may differ between runs.
DATASET_FIXED = ("anonymize", "sidecars", "include_modality_prefix", "salt")


class CommitConflict(ValueError):
    """Preserve existing output and require a new operation or explicit recovery."""


def _sync(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path: Path, record: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w") as stream:
            json.dump(record, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        _sync(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def file_digest(path: Path, root: Path | None = None) -> dict[str, Any]:
    sha = hashlib.sha256()
    with files.open_file(path, root) as stream:
        before = os.fstat(stream.fileno())
        while data := stream.read(CHUNK):
            sha.update(data)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise CommitConflict("Resume conflict: source or artifact changed while hashing")
    return {"size": after.st_size, "sha256": sha.hexdigest()}


def input_manifest(series: Series) -> dict[str, Any]:
    root = series.source_root or series.dicom_dir
    return {
        "root": str(root),
        "series": series.series_id,
        "files": [{"path": str(p.relative_to(root)), **file_digest(p, root)} for p in series.files],
    }


def reader_versions(version: str) -> dict[str, str]:
    return {"dicom.convert": version, **{name: metadata.version(name) for name in ("SimpleITK", "pydicom", "isal")}}


def fixed_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return {key: settings[key] for key in DATASET_FIXED if key in settings}


def versions_differ(recorded: dict[str, Any], current: dict[str, Any]) -> bool:
    """Only keys both records know count; an older record without isal is not a different version."""
    return any(recorded[key] != current[key] for key in recorded.keys() & current.keys())


def stat_digest(paths: list[Path]) -> str:
    """Size, mtime and ctime of a unit's members: change detection between analysis and conversion.

    Not an integrity check (DCM-30): committed units are always verified by SHA-256.
    """
    digest = hashlib.sha256()
    for path in sorted(paths):
        st = os.stat(path, follow_symlinks=False)
        digest.update(json.dumps([str(path), st.st_size, st.st_mtime_ns, st.st_ctime_ns]).encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class Publication:
    converted: convert.Converted
    reused: bool
    outputs: list[dict[str, Any]]
    versions: dict[str, str]  # the readers that produced the artifacts (older ones on reuse)


class _DigestReader(io.BufferedReader):
    def __init__(self, raw: Any) -> None:
        super().__init__(raw)
        self.sha = hashlib.sha256()

    def read(self, size: int | None = -1) -> bytes:
        data = super().read(size)
        self.sha.update(data)
        return data


def _image_digest(path: Path, geometry: dict[str, Any]) -> dict[str, Any]:
    with path.open("rb", buffering=0) as raw:
        before = os.fstat(raw.fileno())
        checked = _DigestReader(raw)
        with gzip.GzipFile(fileobj=checked, mode="rb") as stream:
            while stream.read(CHUNK):
                pass
        _geometry(path, geometry)
        after = os.fstat(raw.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise CommitConflict("Resume conflict: image changed during validation")
        return {"size": after.st_size, "sha256": checked.sha.hexdigest()}


def _geometry(path: Path, geometry: dict[str, Any]) -> None:
    import SimpleITK as sitk

    reader = sitk.ImageFileReader()
    reader.SetFileName(str(path))
    reader.ReadImageInformation()
    if list(reader.GetSize()) != geometry["size"]:
        raise CommitConflict("Resume conflict: output dimensions changed")
    for actual, name in [
        (reader.GetSpacing(), "spacing"),
        (reader.GetOrigin(), "origin"),
        (reader.GetDirection(), "direction"),
    ]:
        if len(actual) != len(geometry[name]) or not all(
            math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-4) for a, b in zip(actual, geometry[name], strict=True)
        ):
            raise CommitConflict("Resume conflict: output world geometry changed")


def _verify(path: Path, expected: dict[str, Any]) -> None:
    try:
        current = file_digest(path)
    except OSError:
        raise CommitConflict("Resume conflict: a required committed artifact is unavailable") from None
    if current != expected:
        raise CommitConflict("Resume conflict: committed artifact content changed")


def _publish(record: dict[str, Any], out: Path, side: Path, stage: Path, *, image_verified: bool = False) -> None:
    for name, target in [("image", out), ("sidecar", side)]:
        expected = record["artifacts"].get(name)
        if expected is None:
            continue
        candidate = stage / ("image.nii.gz" if name == "image" else "sidecar.json")
        if target.exists():
            _verify(target, expected)
        else:
            _verify(candidate, expected)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(candidate, target)
        _sync(target.parent)
    if image_verified:
        # The publish hash proves these bytes match the stream already validated in this attempt.
        _geometry(out, record["geometry"])
    else:
        _image_digest(out, record["geometry"])


def commit_series(
    series: Series,
    header: Callable[[], Any],
    out: Path,
    side: Path,
    *,
    settings: dict[str, Any],
    version: str,
    sidecars: bool,
    before_pixels: Callable[[], None] | None = None,
    verify_only: bool = False,
    expected_stat: str | None = None,
) -> Publication | None:
    """Publication only after durable commit of all artifacts.

    A fresh unit checks its members against the analysed stats, hashes them, reads the sidecar
    header and decodes, then hashes again: all of it inside one pinned window.
    """
    state = out.parent / ".checkpoints" / out.name
    if verify_only and not state.exists():
        if out.exists() or side.exists():
            raise CommitConflict("Resume conflict: existing artifacts have no verified checkpoint")
        return None
    state.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(state / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CommitConflict("Resume conflict: another writer owns this series") from None
        return _commit(
            series, header, out, side, state, settings, version, sidecars, before_pixels, verify_only, expected_stat
        )
    finally:
        os.close(lock_fd)


def _commit(
    series: Series,
    header: Callable[[], Any],
    out: Path,
    side: Path,
    state: Path,
    settings: dict[str, Any],
    version: str,
    sidecars: bool,
    before_pixels: Callable[[], None] | None,
    verify_only: bool,
    expected_stat: str | None,
) -> Publication | None:
    path = state / "commit.json"
    fixed = fixed_settings(settings)
    stage = state / "staged"
    reused = False
    if path.exists():
        try:
            record = json.loads(path.read_text())
            pinned = record["identity"]
            # Reuse needs equal inputs (hashed again) and artifact settings; versions stay provenance.
            if (
                record["version"] not in (1, 2)
                or fixed_settings(pinned["settings"]) != fixed
                or pinned["inputs"] != input_manifest(series)
            ):
                raise CommitConflict("Resume conflict: pinned inputs, settings or reader changed")
            reused = record["status"] == "committed"
            if reused:
                # Equal SHA-256 means the bytes that passed the full CRC/geometry check at commit.
                for name, target in [("image", out), ("sidecar", side)]:
                    if name in record["artifacts"]:
                        _verify(target, record["artifacts"][name])
                _geometry(out, record["geometry"])
            elif record["status"] == "prepared":
                if verify_only:
                    return None
                _publish(record, out, side, stage)
            else:
                raise CommitConflict("Resume conflict: checkpoint status is not supported")
        except (KeyError, json.JSONDecodeError, TypeError):
            raise CommitConflict("Resume conflict: checkpoint is damaged or incompatible") from None
    else:
        if out.exists() or side.exists():
            raise CommitConflict("Resume conflict: existing artifacts have no verified checkpoint")
        if verify_only:
            return None
        if expected_stat is not None and stat_digest(list(series.files)) != expected_stat:
            raise CommitConflict("Resume conflict: source changed since analysis; analyse it again")
        manifest = input_manifest(series)
        stage.mkdir(exist_ok=True)
        # Unpublished staging left before the prepared record is disposable owned scratch.
        for entry in stage.iterdir():
            if entry.is_file():
                entry.unlink()
        image = stage / "image.nii.gz"
        if before_pixels is not None:
            before_pixels()
        converted = convert.write_nifti(series, image)
        geometry = json.loads(json.dumps(asdict(converted)))
        artifacts = {"image": _image_digest(image, geometry)}
        if sidecars:
            staged_side = stage / "sidecar.json"
            sidecar.write_sidecar(header(), staged_side)
            with staged_side.open("rb") as stream:
                os.fsync(stream.fileno())
            artifacts["sidecar"] = file_digest(staged_side)
        if input_manifest(series) != manifest:
            raise CommitConflict("Resume conflict: selected inputs changed during conversion")
        record = {
            "version": 2,
            "status": "prepared",
            "identity": {"inputs": manifest, "settings": fixed, "versions": reader_versions(version)},
            "geometry": geometry,
            "artifacts": artifacts,
        }
        _sync(stage)
        _write(path, record)  # recovery can finish a crash between the individual publications
        _publish(record, out, side, stage, image_verified=True)
    if not reused:
        record["status"] = "committed"
        _write(path, record)
    # The manifest is durable before staging is removed or any progress is acknowledged.
    if stage.exists() and not verify_only:
        for entry in stage.iterdir():
            with contextlib.suppress(FileNotFoundError):
                entry.unlink()
        stage.rmdir()
        _sync(state)
    geometry = record["geometry"]
    converted = convert.Converted(
        tuple(geometry["size"]),
        tuple(geometry["spacing"]),
        tuple(geometry["origin"]),
        tuple(geometry["direction"]),
        geometry["pixel_type"],
    )
    outputs = [{"kind": "image", "path": str(out), "sha256": record["artifacts"]["image"]["sha256"]}]
    if "sidecar" in record["artifacts"]:
        outputs.append({"kind": "sidecar", "path": str(side), "sha256": record["artifacts"]["sidecar"]["sha256"]})
    return Publication(converted, reused, outputs, dict(record["identity"]["versions"]))


def restore_identity(path: Path, identity: Any) -> None:
    """Keep the original case/scan allocation, detecting conflicting later registrations."""
    if not path.exists():
        return
    try:
        record = json.loads(path.read_text())
        if record["version"] not in (1, 2):  # same identity format in both pin versions
            raise ValueError
        pinned = record["identity"]
        for name in ("template", "start", "strategy"):
            if pinned[name] != getattr(identity, name):
                raise ValueError
        for name in ("cases", "scans", "table"):
            current = getattr(identity, name)
            for key, value in pinned[name].items():
                if key in current and current[key] != value:
                    raise ValueError
                if name in ("cases", "table") and any(k != key and v == value for k, v in current.items()):
                    raise ValueError
                current[key] = value
        identity.next_index = max(identity.next_index, pinned["next_index"])
    except (KeyError, ValueError, TypeError):
        raise CommitConflict(
            "Resume conflict: pinned identity is damaged or conflicts with the current registry"
        ) from None


def pin_run(path: Path, settings: dict[str, Any], version: str, identity: Any, units: list[dict[str, Any]]) -> None:
    """The run's plan: settings, readers, identity and one stat digest per selected unit."""
    pinned = {"version": 2, "settings": settings, "versions": reader_versions(version), "units": units}
    if path.exists():
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            raise CommitConflict("Resume conflict: pinned conversion plan is unavailable or damaged") from None
        if record.get("version") != 2:
            raise CommitConflict(
                "Resume conflict: an earlier converter pinned this run; finish it with that version or start a new run"
            )
        if any(record.get(key) != value for key, value in pinned.items()):
            raise CommitConflict(
                "Resume conflict: selected inputs, settings or reader changed; refresh in a new operation"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, {**pinned, "identity": identity.as_dict()})
