"""Derived index store: `index/{items,cases,qc_warnings}.jsonl` + `status.json`.

Reads are cached per project (LRU of `PROJECT_CACHE_MAX`); `replace` rewrites the index
atomically and invalidates the cache. Callers must hold the project write lock for `replace`.
`load` joins native phase selections on top at read time (re-joined whenever
`events/phase.jsonl` changes); writers start from `load_resolved`, and `replace` never stores
the join.
"""

from __future__ import annotations

import zlib
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, overload

from app.core.errors import NotFound
from app.core.fsio import atomic_write_json, iter_jsonl_lines, read_json, write_jsonl_atomic
from app.ingest.hashing import load_hashes
from app.ingest.models import CaseSummary, IndexStatus, Item, QcWarning
from app.phase import state as phase_state

ITEMS, CASES, WARNINGS, STATUS = "items.jsonl", "cases.jsonl", "qc_warnings.jsonl", "status.json"


class WarningRows(Sequence[QcWarning]):
    def __init__(self, compressed: bytes) -> None:
        self._rows = zlib.decompress(compressed).splitlines()

    def __len__(self) -> int:
        return len(self._rows)

    @overload
    def __getitem__(self, key: int) -> QcWarning: ...

    @overload
    def __getitem__(self, key: slice) -> list[QcWarning]: ...

    def __getitem__(self, key: int | slice) -> QcWarning | list[QcWarning]:
        if isinstance(key, slice):
            return [QcWarning.model_validate_json(row) for row in self._rows[key]]
        return QcWarning.model_validate_json(self._rows[key])


@dataclass
class ProjectIndex:
    items: list[Item]
    by_id: dict[str, Item]
    cases: list[CaseSummary]
    cases_by_id: dict[str, CaseSummary]
    warnings_zlib: bytes

    @property
    def warnings(self) -> Sequence[QcWarning]:
        return WarningRows(self.warnings_zlib)


@dataclass
class _Entry:
    resolved: ProjectIndex  # as indexed
    joined: ProjectIndex | None = None  # with the phase selections
    phase_sig: tuple[int, int, int] | None = None


class IndexStore:
    def __init__(
        self,
        project_dir: Callable[[str], Path],
        cache_max: int,
        default_seg: Callable[[str], str],
        phase_vocabulary: Callable[[str], Sequence[str]],
    ) -> None:
        self._project_dir = project_dir
        self._cache_max = cache_max
        self._default_seg = default_seg
        self._phase_vocabulary = phase_vocabulary
        self._cache: OrderedDict[str, _Entry] = OrderedDict()

    def index_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "index"

    def load(self, project_id: str) -> ProjectIndex:
        """The index with the effective phase: native selection, else the resolved value."""
        entry = self._entry(project_id)
        sig = phase_state.signature(self._project_dir(project_id))
        if entry.joined is None or entry.phase_sig != sig:
            entry.joined = self._join(project_id, entry.resolved)
            entry.phase_sig = sig
        return entry.joined

    def effective_phases(self, project_id: str) -> dict[str, str]:
        """Item id → effective phase, for consumers of run outputs."""
        return {it.item_id: it.phase.canonical for it in self.load(project_id).items}

    def load_resolved(self, project_id: str) -> ProjectIndex:
        """The index as indexed, without the phase join: the base for index writers."""
        return self._entry(project_id).resolved

    def _join(self, project_id: str, idx: ProjectIndex) -> ProjectIndex:
        selected = phase_state.selections(self._project_dir(project_id))
        if not selected:
            return idx
        items, cases = phase_state.apply(
            idx.items, idx.cases, selected, self._phase_vocabulary(project_id)
        )
        return ProjectIndex(
            items, {i.item_id: i for i in items}, cases, {c.case_id: c for c in cases},
            idx.warnings_zlib,
        )  # fmt: skip

    def _entry(self, project_id: str) -> _Entry:
        hit = self._cache.get(project_id)
        if hit is not None:
            self._cache.move_to_end(project_id)
            return hit
        d = self.index_dir(project_id)
        items = [Item.model_validate_json(r) for r in iter_jsonl_lines(d / ITEMS)]
        default = self._default_seg(project_id)
        for it in items:
            it.mask = it.masks.get(default)  # deprecated alias
        hashes = load_hashes(d).files
        if hashes:
            for vol in (v for it in items for v in it.volumes()):
                h = hashes.get(vol.ref)
                vol.sha256 = h.sha256 if h is not None and h.fp == vol.fp else None
        cases = [CaseSummary.model_validate_json(r) for r in iter_jsonl_lines(d / CASES)]
        rows = list(iter_jsonl_lines(d / WARNINGS))
        for row in rows:
            QcWarning.model_validate_json(row)
        warnings = zlib.compress(b"\n".join(rows), level=1)
        idx = ProjectIndex(
            items, {i.item_id: i for i in items}, cases, {c.case_id: c for c in cases}, warnings
        )
        entry = _Entry(idx)
        self._cache[project_id] = entry
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)
        return entry

    def invalidate(self, project_id: str) -> None:
        self._cache.pop(project_id, None)

    def get_item(self, project_id: str, item_id: str) -> Item:
        item = self.load(project_id).by_id.get(item_id)
        if item is None:
            raise NotFound(f"Item {item_id!r} not found")
        return item

    def get_case(self, project_id: str, case_id: str) -> CaseSummary:
        case = self.load(project_id).cases_by_id.get(case_id)
        if case is None:
            raise NotFound(f"Case {case_id!r} not found")
        return case

    def status(self, project_id: str) -> IndexStatus:
        p = self.index_dir(project_id) / STATUS
        return IndexStatus.model_validate(read_json(p)) if p.exists() else IndexStatus()

    def write_status(self, project_id: str, status: IndexStatus) -> None:
        atomic_write_json(self.index_dir(project_id) / STATUS, status.model_dump(mode="json"))

    def replace(
        self,
        project_id: str,
        items: Sequence[Item],
        cases: Sequence[CaseSummary],
        warnings: Sequence[QcWarning],
    ) -> None:
        d = self.index_dir(project_id)
        write_jsonl_atomic(d / WARNINGS, (w.model_dump(mode="json") for w in warnings))
        write_jsonl_atomic(d / CASES, (c.model_dump(mode="json") for c in cases))
        write_jsonl_atomic(d / ITEMS, item_rows(items))
        self.invalidate(project_id)


def item_rows(items: Sequence[Item]) -> list[dict[str, Any]]:
    """Persist resolved phases and alias refs; full hashes stay in hashes.json."""
    rows = []
    for i in items:
        row = i.model_dump(mode="json", exclude={"mask"})
        row["phase"] = (i.phase.resolved or i.phase).model_dump(mode="json", exclude={"resolved"})
        for vol in (row.get("image"), *row["masks"].values()):
            if vol is not None:
                vol.pop("sha256", None)
        rows.append(row)
    return rows
