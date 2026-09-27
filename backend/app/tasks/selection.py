"""Task selection and preflight (TSK-03/04, API-44): which active items run, which are ready."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from app.core.errors import NotFound, ValidationProblem
from app.ingest.models import Item
from app.projects.models import ProjectConfig
from app.tasks.models import (
    VOLUME_OUTPUTS,
    PreflightRequest,
    PreflightResult,
    Suggestion,
    TaskManifest,
    TaskSelection,
)
from app.tasks.records import TaskBase
from app.variables.service import VariableService


class SelectionBase(TaskBase):
    """Selection, readiness, suggestions and the `input: source` path."""

    async def select(self, pid: str, sel: TaskSelection) -> list[Item]:
        """Active items matching an explicit list, or an Explorer filter, or all (TSK-03)."""
        errors: list[dict[str, Any]] = []
        if sel.item_ids is not None and sel.filter is not None:
            errors.append(
                {"loc": ["body", "selection", "filter"], "msg": "Use either item_ids or filter"}
            )
        idx = self.store.load(pid)
        items = [i for i in idx.items if i.status == "active"]
        if sel.item_ids is not None:
            for n, iid in enumerate(sel.item_ids):
                it = idx.by_id.get(iid)
                if it is None:
                    errors.append(
                        {"loc": ["body", "selection", "item_ids", n], "msg": "Unknown item"}
                    )
                elif it.status != "active":
                    errors.append(
                        {"loc": ["body", "selection", "item_ids", n], "msg": f"Item is {it.status}"}
                    )
            wanted = set(sel.item_ids)
            items = [i for i in items if i.item_id in wanted]
        f = sel.filter
        if f is not None:
            if f.phase:
                items = [i for i in items if i.phase.canonical in f.phase]
            if f.side:
                items = [i for i in items if i.side in f.side]
            if f.var:
                vs = VariableService(self.workspace, self.store, self.locks, self.bus)
                ok_ids = (await vs.filter_ids(pid, f.var))["items"]
                items = [i for i in items if i.item_id in ok_ids]
        if sel.scope is not None:
            items = [i for i in items if i.scope == sel.scope]
        if errors:
            raise ValidationProblem("Invalid selection", errors=errors)
        return sorted(items, key=lambda i: i.item_id)

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
        """Why an item can't run (TSK-04), or None when it is ready."""
        if m.input == "items" and it.image is None:
            return "no image"
        mods = m.requires.modality
        if mods and it.modality is not None and it.modality not in mods:
            return f"modality {it.modality}"
        if m.requires.seg is not None and seg_id is not None:
            if seg_id not in it.masks:
                return f"no mask in {seg_id}"
            names = m.requires.seg.labels
            if names and seg_id == "imported" and it.labels_present:
                by_name = {e.name: e.value for e in cfg.label_map}
                for name in names:
                    if by_name.get(name) not in it.labels_present:
                        return f"no {name} label in {seg_id}"
        return None

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
