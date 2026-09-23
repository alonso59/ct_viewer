"""Derived index store: `index/{items,cases,qc_warnings}.jsonl` + `status.json` (PRJ-10, BE-07).

Reads are cached per project (LRU of `PROJECT_CACHE_MAX`); `replace` rewrites the index
atomically and invalidates the cache. Callers must hold the project write lock for `replace`.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import NotFound
from app.core.fsio import atomic_write_json, iter_jsonl, read_json, write_jsonl_atomic
from app.ingest.models import CaseSummary, IndexStatus, Item, QcWarning

ITEMS, CASES, WARNINGS, STATUS = "items.jsonl", "cases.jsonl", "qc_warnings.jsonl", "status.json"


@dataclass
class ProjectIndex:
    items: list[Item]
    by_id: dict[str, Item]
    cases: list[CaseSummary]
    cases_by_id: dict[str, CaseSummary]
    warnings: list[QcWarning]


class IndexStore:
    def __init__(self, project_dir: Callable[[str], Path], cache_max: int = 4) -> None:
        self._project_dir = project_dir
        self._cache_max = cache_max
        self._cache: OrderedDict[str, ProjectIndex] = OrderedDict()

    def index_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "index"

    def load(self, project_id: str) -> ProjectIndex:
        hit = self._cache.get(project_id)
        if hit is not None:
            self._cache.move_to_end(project_id)
            return hit
        d = self.index_dir(project_id)
        items = [Item.model_validate(r) for r in iter_jsonl(d / ITEMS)]
        cases = [CaseSummary.model_validate(r) for r in iter_jsonl(d / CASES)]
        warnings = [QcWarning.model_validate(r) for r in iter_jsonl(d / WARNINGS)]
        idx = ProjectIndex(
            items, {i.item_id: i for i in items}, cases, {c.case_id: c for c in cases}, warnings
        )
        self._cache[project_id] = idx
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)
        return idx

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
        write_jsonl_atomic(d / ITEMS, (i.model_dump(mode="json") for i in items))
        self.invalidate(project_id)
