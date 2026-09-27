"""`job.json` of a task attempt (TASKS.md §Run protocol): items, rows, context, output dirs."""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.errors import Problem
from app.ingest.models import Item
from app.projects.presets import target_profile
from app.sources import identity as identity_store
from app.tasks.models import VOLUME_OUTPUTS, TaskManifest
from app.tasks.selection import SelectionBase


class JobSpecBase(SelectionBase):
    """Builds the job spec a task reads (items or rows, `output_dir`, `dataset/`, identity)."""

    def _job_items(
        self, pid: str, items: Sequence[Item], seg_id: str | None
    ) -> list[dict[str, Any]]:
        resolver = self.workspace.resolver(pid)
        out: list[dict[str, Any]] = []
        for it in items:
            image = None
            if it.image is not None:
                with contextlib.suppress(Problem):
                    image = {"path": str(resolver.resolve(it.image.ref)), "format": it.image.format}
            masks: dict[str, dict[str, Any]] = {}
            for sid, vol in it.masks.items():
                if seg_id is not None and sid != seg_id:
                    continue
                with contextlib.suppress(Problem):
                    masks[sid] = {"path": str(resolver.resolve(vol.ref)), "format": vol.format}
            out.append(
                {
                    "item_id": it.item_id,
                    "case_id": it.case_id,
                    "image": image,
                    "masks": masks,
                    "geometry": it.geometry.model_dump() if it.geometry else None,
                    "meta": {
                        "scan_idx": it.scan_idx,
                        "scope": it.scope,
                        "side": it.side,
                        "modality": it.modality,
                        "phase": it.phase.canonical,
                        "phase_raw": it.phase.raw,
                        "patient_id": it.patient_id,
                        "labels_present": it.labels_present,
                        "extra": it.extra,
                    },
                }
            )
        return out

    def _output_dir(self, pid: str, m: TaskManifest, rid: str) -> Path | None:
        if not VOLUME_OUTPUTS & set(m.outputs):
            return None
        root = self.workspace.derived_root(pid)  # derived-root-required (PRJ-13)
        return Path(root.path) / pid / m.id / "runs" / rid

    def _dataset(self, pid: str, m: TaskManifest) -> tuple[Path, str] | None:
        """The task's append-only `dataset/` and its `ALIAS:rel` (ADR-0014 §4)."""
        if not VOLUME_OUTPUTS & set(m.outputs):
            return None
        root = self.workspace.derived_root(pid)
        return Path(root.path) / pid / m.id / "dataset", f"{root.alias}:{pid}/{m.id}/dataset"

    def _rows(self, items: Sequence[Item]) -> list[dict[str, Any]]:
        """`input: rows` (analyzers, ANZ-02): metadata only, never files."""
        return [
            {
                **it.extra,
                "item_id": it.item_id,
                "case_id": it.case_id,
                "scan_idx": it.scan_idx,
                "modality": it.modality,
            }
            for it in items
        ]

    def _job_spec(
        self,
        pid: str,
        m: TaskManifest,
        *,
        settings: dict[str, Any],
        items: Sequence[Item],
        seg_id: str | None,
        output_dir: str | None,
        source: str | None,
        scratch: Path | None = None,
    ) -> dict[str, Any]:
        """`scratch`: an estimate's disposable dir (no derived root needed, TSK-05)."""
        cfg = self.workspace.get(pid)
        spec: dict[str, Any] = {
            "task": {"id": m.id, "version": m.version},
            "settings": settings,
            # ANZ-05: the project's study packs configure the analyzers
            "context": {
                "phase_vocabulary": list(cfg.phase_vocabulary),
                "packs": list(cfg.packs),
                "target_profile": target_profile(cfg.packs),
            },
            "items": self._job_items(pid, items, seg_id) if m.input == "items" else [],
            "rows": self._rows(items) if m.input == "rows" else [],
            "output_dir": output_dir,
            "project_id": pid,
        }
        if scratch is not None:
            if VOLUME_OUTPUTS & set(m.outputs):
                spec["dataset_dir"], spec["dataset_ref"] = (
                    str(scratch / "dataset"),
                    "SCRATCH:dataset",
                )
        else:
            ds = self._dataset(pid, m)
            if ds is not None:
                spec["dataset_dir"], spec["dataset_ref"] = str(ds[0]), ds[1]
        if source is not None:
            spec["source"] = {"path": source}
        if "metadata" in m.outputs:  # SRC-07 registry + DCM-07 previous rows
            reg = identity_store.load(self.workspace.project_dir(pid) / "sources")
            if not reg.cases:
                reg.strategy = "dicom_patient_id"
            spec["identity"] = reg.model_dump(mode="json")
            spec["previous_metadata"] = self._previous_metadata(pid, m.id)
        return spec

    def _previous_metadata(self, pid: str, task_id: str) -> str | None:
        """The last completed run's `metadata.jsonl` of this task (DCM-07)."""
        for run_dir in self.runs.run_dirs(pid):
            rec = self.runs.read(run_dir)
            if rec.task.id != task_id or rec.status not in ("completed", "completed_with_errors"):
                continue
            if rec.output_dir and (Path(rec.output_dir) / "metadata.jsonl").is_file():
                return str(Path(rec.output_dir) / "metadata.jsonl")
        return None
