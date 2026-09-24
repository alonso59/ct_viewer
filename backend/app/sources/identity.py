"""Case identity registry `sources/identity.json` (SRC-07, SOURCES.md §Identity).

Assignments are append-only: an identity key keeps its case index forever, so incremental
imports never renumber. The API process is the only writer (under the project lock).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.fsio import atomic_write_json, read_json

Strategy = Literal["dicom_patient_id", "filename_pattern", "table"]
IDENTITY = "identity.json"
DEFAULT_TEMPLATE = "case_{n:05d}"
_SLUG_BAD = re.compile(r"[^A-Za-z0-9_-]+")


def slug(value: str, max_len: int = 64) -> str:
    """SRC-08: `[A-Za-z0-9_-]{1,64}`; other characters become `_` (never empty)."""
    s = _SLUG_BAD.sub("_", value.strip()).strip("_")[:max_len]
    return s or "x"


class IdentityRegistry(BaseModel):
    strategy: Strategy = "filename_pattern"
    template: str = DEFAULT_TEMPLATE
    start: int = 0
    next_index: int = 0
    cases: dict[str, int] = Field(default_factory=dict)  # identity key → case index
    scans: dict[str, str] = Field(default_factory=dict)  # "key|series_uid or file" → scan_idx
    table: dict[str, str] = Field(default_factory=dict)  # `table` strategy: key → case_id

    def case_index(self, key: str) -> int:
        n = self.cases.get(key)
        if n is None:
            n = max(self.next_index, self.start)
            self.cases[key] = n
            self.next_index = n + 1
        return n

    def case_id(self, key: str) -> str:
        """`table` entries win; else the template (`{n}` = case index, `{key}` = key slug)."""
        if key in self.table:
            return slug(self.table[key])
        return slug(self.template.format(n=self.case_index(key), key=slug(key)))

    def scan_idx(self, key: str, scan_key: str) -> str:
        """Scan index within a case: `01`, `02`, … in first-seen order, never reused."""
        k = f"{key}|{scan_key}"
        hit = self.scans.get(k)
        if hit is None:
            used = sum(1 for s in self.scans if s.startswith(f"{key}|"))
            hit = self.scans[k] = f"{used + 1:02d}"
        return hit

    def merge(self, other: IdentityRegistry) -> IdentityRegistry:
        """Append-only merge of a task's returned registry (existing keys never change)."""
        out = self.model_copy(deep=True)
        for k, n in other.cases.items():
            out.cases.setdefault(k, n)
        for k, v in other.scans.items():
            out.scans.setdefault(k, v)
        out.next_index = max(
            out.next_index, other.next_index, max(out.cases.values(), default=-1) + 1
        )
        return out


def load(sources_dir: Path) -> IdentityRegistry:
    p = sources_dir / IDENTITY
    if not p.is_file():
        return IdentityRegistry()
    raw: Any = read_json(p)
    return IdentityRegistry.model_validate(raw)


def save(sources_dir: Path, reg: IdentityRegistry) -> None:
    atomic_write_json(sources_dir / IDENTITY, reg.model_dump(mode="json"))
