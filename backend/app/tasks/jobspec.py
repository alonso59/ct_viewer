"""`job.json` of a task attempt: items, rows, context, output dirs."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.errors import JobConflict, Problem
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import is_ulid
from app.imaging import maskset, npy_convert
from app.imaging.fingerprint import quick_fingerprint
from app.ingest.models import Item
from app.jobs.types import JobHandle
from app.projects.presets import target_profile
from app.sources import identity as identity_store
from app.tasks.models import VOLUME_OUTPUTS, TaskManifest
from app.tasks.selection import SelectionBase


def _inventory_binding(workspace: Path, binding: dict[str, Any]) -> dict[str, Any]:
    operation = binding.get("operation_id")
    generation = binding.get("generation")
    if (
        not isinstance(operation, str)
        or not is_ulid(operation)
        or not isinstance(generation, str)
        or not is_ulid(generation)
    ):
        raise JobConflict("Source inventory binding is incompatible")
    path = workspace / "plugins" / "dicom" / "operations" / operation / "inventory.sqlite"
    if binding.get("path") != str(path):
        raise JobConflict("Source inventory must remain in its managed operation directory")
    return binding


def bind_inventory(run: Path, workspace: Path, binding: dict[str, Any] | None) -> None:
    if binding is None:
        return
    value = _inventory_binding(workspace, binding)
    path = run / "source-inventory.json"
    if path.exists() and read_json(path) != value:
        raise JobConflict("Logical conversion is already pinned to a different source plan")
    atomic_write_json(path, value)


def inventory_spec(run: Path, workspace: Path) -> dict[str, Any]:
    path = run / "source-inventory.json"
    return (
        {"source_inventory": _inventory_binding(workspace, read_json(path))}
        if path.exists()
        else {}
    )


class JobSpecBase(SelectionBase):
    """Builds the job spec a task reads (items or rows, `output_dir`, `dataset/`, identity)."""

    def source_estimate_spec(
        self,
        pid: str,
        task_id: str,
        source: str,
        settings: dict[str, Any],
        scratch: Path,
    ) -> dict[str, Any]:
        manifest = self.registry.get(task_id).manifest
        normalized, _ = self._settings(manifest, settings)
        return self._job_spec(
            pid,
            manifest,
            settings=normalized,
            items=[],
            seg_id=None,
            source=source,
            output_dir=str(scratch / "out"),
            scratch=scratch,
        )

    def _job_items(
        self, pid: str, items: Sequence[Item], seg_id: str | None
    ) -> list[dict[str, Any]]:
        resolver = self.workspace.resolver(pid)
        cfg = self.workspace.get(pid)
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
                segmentation = cfg.segmentation(sid)
                if segmentation is None:
                    continue
                with contextlib.suppress(Problem):
                    masks[sid] = {"path": str(resolver.resolve(vol.ref)), "format": vol.format}
                    if seg_id is not None and segmentation.removed_labels:
                        masks[sid]["removed_labels"] = segmentation.removed_labels
                    if vol.labels:  # a mask set folder: member name → value
                        masks[sid]["labels"] = vol.labels
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

    async def _prepare_mask_inputs(
        self, pid: str, spec: dict[str, Any], handle: JobHandle | None = None
    ) -> None:
        project_dir = self.workspace.project_dir(pid)
        runner = handle if handle is not None else self.jobs
        for item in spec["items"]:
            for mask in item["masks"].values():
                if handle is not None and handle.stopped:
                    return
                removed = mask.pop("removed_labels", [])
                if not removed:
                    continue
                src = Path(mask["path"])
                fp = await asyncio.to_thread(quick_fingerprint, src)
                if mask["format"] == "nifti_dir":
                    path = await maskset.ensure_composed(
                        runner, project_dir, src, fp, mask["labels"], removed
                    )
                else:
                    if mask["format"] == "npy":
                        order = (
                            npy_convert.axis_order_of(item["meta"]["extra"].get("axis_order"))
                            or "xyz"
                        )
                        spacing = (
                            item["geometry"]["spacing"] if item["geometry"] else [1.0, 1.0, 1.0]
                        )
                        dst = npy_convert.cache_path(project_dir, fp, order)
                        src = await npy_convert.ensure_nifti(runner, src, dst, spacing, order)
                        fp = await asyncio.to_thread(quick_fingerprint, src)
                    path = await maskset.ensure_filtered(runner, project_dir, src, fp, removed)
                mask.update({"path": str(path), "format": "nifti"})
                mask.pop("labels", None)

    def _output_dir(self, pid: str, m: TaskManifest, rid: str) -> Path | None:
        if not VOLUME_OUTPUTS & set(m.outputs):
            return None
        root = self.workspace.derived_root(pid)  # task outputs go only into a derived root
        return Path(root.path) / pid / m.id / "runs" / rid

    def _dataset(self, pid: str, m: TaskManifest) -> tuple[Path, str] | None:
        """The task's append-only `dataset/` and its `ALIAS:rel`."""
        if not VOLUME_OUTPUTS & set(m.outputs):
            return None
        root = self.workspace.derived_root(pid)
        return Path(root.path) / pid / m.id / "dataset", f"{root.alias}:{pid}/{m.id}/dataset"

    def _rows(self, items: Sequence[Item]) -> list[dict[str, Any]]:
        """`input: rows` (analyzers): item metadata only."""
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
        """`scratch`: an estimate's disposable dir (no derived root needed)."""
        cfg = self.workspace.get(pid)
        spec: dict[str, Any] = {
            "task": {"id": m.id, "version": m.version},
            "settings": settings,
            # the project's study packs configure the analyzers
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
        if m.id == "dicom.convert":
            timing_root = cfg.derived_root()
            spec["timing_destination"] = timing_root.path if timing_root else None
        if "metadata" in m.outputs:
            reg = identity_store.load(self.workspace.project_dir(pid) / "sources")
            if not reg.cases:
                reg.strategy = "dicom_patient_id"
            spec["identity"] = reg.model_dump(mode="json")
            spec["previous_metadata"] = self._previous_metadata(pid, m.id)
        return spec

    def _previous_metadata(self, pid: str, task_id: str) -> str | None:
        """The last completed run's `metadata.jsonl` of this task."""
        for run_dir in self.runs.run_dirs(pid):
            rec = self.runs.read(run_dir)
            if rec.task.id != task_id or rec.status not in ("completed", "completed_with_errors"):
                continue
            if rec.output_dir and (Path(rec.output_dir) / "metadata.jsonl").is_file():
                return str(Path(rec.output_dir) / "metadata.jsonl")
        return None
