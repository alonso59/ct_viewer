"""Case identity on the task side (SRC-07): the backend's `sources/identity.json` registry comes in
`job.json` and goes back in `result.json`; existing keys never change."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_BAD = re.compile(r"[^A-Za-z0-9_-]+")


def slug(value: str) -> str:
    return _BAD.sub("_", value.strip()).strip("_")[:64] or "x"


@dataclass
class Identity:
    template: str = "case_{n:05d}"
    start: int = 0
    next_index: int = 0
    cases: dict[str, int] = field(default_factory=dict)
    scans: dict[str, str] = field(default_factory=dict)
    table: dict[str, str] = field(default_factory=dict)
    strategy: str = "dicom_patient_id"

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Identity:
        d = d or {}
        return cls(
            template=str(d.get("template") or "case_{n:05d}"),
            start=int(d.get("start") or 0),
            next_index=int(d.get("next_index") or 0),
            cases={str(k): int(v) for k, v in (d.get("cases") or {}).items()},
            scans={str(k): str(v) for k, v in (d.get("scans") or {}).items()},
            table={str(k): str(v) for k, v in (d.get("table") or {}).items()},
            strategy=str(d.get("strategy") or "dicom_patient_id"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "template": self.template,
            "start": self.start,
            "next_index": self.next_index,
            "cases": self.cases,
            "scans": self.scans,
            "table": self.table,
        }

    def case_id(self, key: str) -> str:
        if key in self.table:
            return slug(self.table[key])
        n = self.cases.get(key)
        if n is None:
            n = max(self.next_index, self.start, max(self.cases.values(), default=-1) + 1)
            self.cases[key] = n
            self.next_index = n + 1
        return slug(self.template.format(n=n, key=slug(key)))

    def scan_idx(self, key: str, scan_key: str) -> str:
        k = f"{key}|{scan_key}"
        hit = self.scans.get(k)
        if hit is None:
            used = sum(1 for s in self.scans if s.startswith(f"{key}|"))
            hit = self.scans[k] = f"{used + 1:02d}"
        return hit
