"""Relink verification on a sample of items via quick fingerprint (PRJ-05, API-05)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from app.core.errors import NotFound, PathOutsideRoot, ValidationProblem
from app.core.paths import PathResolver
from app.imaging.fingerprint import quick_fingerprint
from app.ingest.models import Item, VolumeRef

SAMPLE_MAX = 20
VerifyStatus = Literal["matched", "mismatched", "missing"]


class VerifySample(BaseModel):
    item_id: str
    ref: str
    status: VerifyStatus


class VerifyReport(BaseModel):
    sampled: int = 0
    matched: int = 0
    mismatched: int = 0
    missing: int = 0
    samples: list[VerifySample] = Field(default_factory=list)


def _alias_of(ref: str) -> str | None:
    alias, sep, _ = ref.partition(":")
    return alias if sep else None


def _candidate(item: Item, alias: str) -> VolumeRef | None:
    for vol in item.volumes():
        if vol is not None and vol.fp and _alias_of(vol.ref) == alias:
            return vol
    return None


def evenly_spaced[T](seq: Sequence[T], n: int) -> list[T]:
    if len(seq) <= n:
        return list(seq)
    return [seq[i * len(seq) // n] for i in range(n)]


def check_ref(resolver: PathResolver, vol: VolumeRef) -> VerifyStatus:
    try:
        path = resolver.resolve(vol.ref)
        if not path.is_file():
            return "missing"
        return "matched" if quick_fingerprint(path) == vol.fp else "mismatched"
    except (PathOutsideRoot, NotFound, ValidationProblem, OSError):
        return "missing"


def verify_root(
    resolver: PathResolver, items: Sequence[Item], alias: str, sample: int = SAMPLE_MAX
) -> VerifyReport:
    """Resolve up to `sample` fingerprinted refs under `alias` and compare fingerprints."""
    pairs = [(it.item_id, vol) for it in items if (vol := _candidate(it, alias)) is not None]
    report = VerifyReport()
    for item_id, vol in evenly_spaced(pairs, sample):
        status = check_ref(resolver, vol)
        report.samples.append(VerifySample(item_id=item_id, ref=vol.ref, status=status))
        setattr(report, status, getattr(report, status) + 1)
    report.sampled = len(report.samples)
    return report
