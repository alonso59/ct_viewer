"""Task selection and preflight (TSK-03/04, API-44): which active items run, which are ready."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Final

from app.core.errors import NotFound, ValidationProblem
from app.ingest.models import Item
from app.projects.models import ProjectConfig
from app.selection import readiness
from app.tasks.models import (
    VOLUME_OUTPUTS,
    PreflightRequest,
    PreflightResult,
    Suggestion,
    TaskManifest,
    TaskSelection,
)
from app.tasks.records import TaskBase

# TSK-04 reason codes → the `missing` keys of API-44 preflight
_TEXT: Final[dict[str, str]] = {
    "no_image": "no image",
    "modality": "modality {modality}",
    "no_mask": "no mask in {seg_id}",
    "label_missing": "no {label} label in {seg_id}",
    "blocked": "{qc} in {seg_id}",
}


class SelectionBase(TaskBase):
    """Selection, readiness, suggestions and the `input: source` path."""

    async def select(self, pid: str, sel: TaskSelection) -> list[Item]:
        """Active items matching an explicit list, or an Explorer filter, or all (TSK-03)."""
        idx = self.store.load(pid)
        ids = readiness.var_ids(self.workspace, self.store, self.locks, self.bus, pid)
        items, problems = await readiness.resolve(idx.items, idx.by_id, sel, ids)
        if problems:
            errors = [{"loc": ["body", "selection", *p.loc], "msg": p.msg} for p in problems]
            raise ValidationProblem("Invalid selection", errors=errors)
        return items

    def _seg_id(self, cfg: ProjectConfig, m: TaskManifest, sel: TaskSelection) -> str | None:
        if m.requires.seg is None:
            return None
        seg_id = sel.seg_id or cfg.default_seg
        if cfg.segmentation(seg_id) is None:
            raise ValidationProblem(
                f"Unknown segmentation set {seg_id!r}",
                errors=[{"loc": ["body", "selection", "seg_id"], "msg": "unknown seg_id"}],
            )
        return seg_id

    def _not_ready(
        self, cfg: ProjectConfig, m: TaskManifest, it: Item, seg_id: str | None
    ) -> str | None:
        """Why an item can't run (TSK-04, `readiness.not_ready`) as text, or None when ready."""
        r = readiness.not_ready(
            it,
            need_image=m.input == "items",
            modalities=m.requires.modality,
            seg_id=seg_id if m.requires.seg is not None else None,
            labels=m.requires.seg.labels if m.requires.seg is not None else (),
            label_map={e.name: e.value for e in cfg.label_map},
        )
        return None if r is None else _TEXT[r.code].format(**r.params)

    def _suggest(self, m: TaskManifest, missing: dict[str, int]) -> list[Suggestion]:
        out: list[Suggestion] = []
        mask_gaps = {
            r: n for r, n in missing.items() if r.startswith("no mask") or " label in " in r
        }
        if not mask_gaps:
            return out
        for info in self.registry.tasks.values():
            t = info.manifest
            if t.id == m.id or "masks" not in t.outputs or t.test_only:
                continue
            for reason, n in mask_gaps.items():
                out.append(Suggestion(task_id=t.id, reason=f"{n} items: {reason}"))
        return out

    def _source(self, sel: TaskSelection) -> str:
        """`input: source`: a folder or file inside ALLOWED_DATA_ROOTS (DCM-01, SRC-13)."""
        if not sel.source:
            raise ValidationProblem(
                "Choose the DICOM folder or file to convert",
                errors=[{"loc": ["body", "selection", "source"], "msg": "required"}],
                actions=["choose_source"],
            )
        path = Path(sel.source)
        if not path.is_absolute():
            raise ValidationProblem("source must be an absolute path")
        real = self.workspace.guard.check(path)
        if not real.exists():
            raise NotFound("Source path not found")
        return str(real)

    async def preflight(self, pid: str, task_id: str, req: PreflightRequest) -> PreflightResult:
        m = self.registry.get(task_id).manifest
        cfg = self.workspace.get(pid)
        needs_derived = bool(VOLUME_OUTPUTS & set(m.outputs)) and cfg.derived_root() is None
        if m.input == "source":
            ok = False
            if req.selection.source:
                self._source(req.selection)
                ok = True
            return PreflightResult(
                n_selected=1 if ok else 0,
                n_ready=1 if ok else 0,
                missing={} if ok else {"no source folder": 1},
                suggestions=[],
                derived_root_required=needs_derived,
            )
        items = await self.select(pid, req.selection)
        seg_id = self._seg_id(cfg, m, req.selection)
        missing: Counter[str] = Counter()
        ready: list[str] = []
        for it in items:
            reason = self._not_ready(cfg, m, it, seg_id)
            if reason is None:
                ready.append(it.item_id)
            else:
                missing[reason] += 1
        return PreflightResult(
            n_selected=len(items),
            n_ready=len(ready),
            missing=dict(missing),
            suggestions=self._suggest(m, dict(missing)),
            derived_root_required=needs_derived,
            ready_item_ids=ready,
        )
