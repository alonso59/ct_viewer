"""Quick and full fingerprints (PROJECT_FORMAT.md §Path aliases, IMP-09).

Quick fingerprint = `{size}-{sha256(first 64 KiB + last 64 KiB)[:32]}`; it is also the ETag (BE-04).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.paths import open_source

CHUNK = 64 * 1024


def quick_fingerprint(path: Path) -> str:
    with open_source(path) as fh:
        fh.seek(0, 2)
        size = fh.tell()
        h = hashlib.sha256()
        fh.seek(0)
        h.update(fh.read(CHUNK))
        if size > CHUNK:
            fh.seek(max(CHUNK, size - CHUNK))
            h.update(fh.read(CHUNK))
    return f"{size}-{h.hexdigest()[:32]}"


def full_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open_source(path) as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
