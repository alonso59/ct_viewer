"""Read-only, streamed source traversal shared by DICOM and mixed-format discovery."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO

EXCLUDED_DIRS = {"__pycache__", "recycle_bin", "derived"}


def excluded(name: str) -> bool:
    return name.startswith(".") or name.lower() in EXCLUDED_DIRS


def folders(root: Path, on_error: Callable[[OSError], None] | None = None) -> Iterator[tuple[Path, list[Path]]]:
    """Directory-at-a-time traversal. Never follows directory or file symlinks."""
    pending = [root]
    while pending:
        current = pending.pop()
        children: list[Path] = []
        files: list[Path] = []
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.name.startswith(".") or entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if not excluded(entry.name):
                            children.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        files.append(Path(entry.path))
        except OSError as exc:
            if on_error is not None:
                on_error(exc)
        pending.extend(sorted(children, reverse=True))
        yield current, sorted(files)


def local_file(root: Path, path: Path) -> bool:
    """Include lists cannot reach another root or traverse nested symlinks."""
    try:
        parts = path.relative_to(root).parts
        if not parts or any(p in (".", "..") or excluded(p) for p in parts[:-1]):
            return False
        current = root
        for part in parts:
            current /= part
            if current.is_symlink():
                return False
        return current.is_file()
    except (ValueError, OSError):
        return False


def open_file(path: Path, root: Path | None = None) -> BinaryIO:
    """Open a pinned chain of directory descriptors: no symlink race after discovery.

    The OCI runtime is Linux. The portable fallback rejects symlinks before opening.
    `root` is already checked by the service; workers pass it for descendant access.
    """
    anchor = root if root is not None else path.parent
    parts = path.relative_to(anchor).parts
    if not parts or any(p in (".", "..") for p in parts):
        raise OSError("Source file is outside its root")
    if not hasattr(os, "O_NOFOLLOW"):
        if not local_file(anchor, path):
            raise OSError("Source file is not a regular local file")
        return path.open("rb")
    directory = os.open(anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise OSError("Source file is not a regular local file")
    finally:
        os.close(directory)
    return os.fdopen(fd, "rb", buffering=0)
