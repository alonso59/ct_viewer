"""Task outputs and their registration (TSK-09): masks → a segmentation set, volumes → the
derived ledger, identity / annotations / metadata → an import.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.fsio import iter_jsonl, write_jsonl_atomic
from app.core.ids import utc_now
from app.core.paths import is_within, realpath
from app.imaging.fingerprint import quick_fingerprint
from app.projects.models import LabelEntry, SegmentationSet, SegProducer
from app.projects.presets import AUTO_LABEL_COLORS, auto_label_name
from app.sources import identity as identity_store
from app.tasks.estimate import EstimateBase
from app.tasks.models import TaskRunOutput
from app.tasks.records import ANNOTATIONS, Live, default_seg_id, sha256_file


class RegistrationBase(EstimateBase):
    """Validates and registers what a run wrote (TSK-09, ADR-0014/0015)."""

    async def _item_outputs(
        self, live: Live, item_id: str, outputs: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Validate volume outputs (inside `output_dir`, ADR-0014) → `masks.jsonl` rows."""
        rows: list[dict[str, Any]] = []
        for o in outputs:
            kind = o.get("kind")
            if kind in ("image", "sidecar"):
                await self._volume_output(live, item_id, str(kind), o)
                continue
            if kind != "mask":
                continue
            if "masks" not in live.manifest.outputs:
                raise ValueError("task declared no mask outputs")
            rec = self.runs.read(live.run_dir)
            if rec.output_dir is None:
                raise ValueError("run has no output_dir")
            path = realpath(Path(str(o.get("path", ""))))
            out_dir = realpath(Path(rec.output_dir))
            if not is_within(path, out_dir) or not path.is_file():
                raise ValueError("mask is not a file inside the run's output_dir")
            root = self.workspace.derived_root(live.pid)
            rel = path.relative_to(realpath(Path(root.path))).as_posix()
            fp = await asyncio.to_thread(quick_fingerprint, path)
            ref = f"{root.alias}:{rel}"
            sha = o.get("sha256") or await asyncio.to_thread(sha256_file, path)
            rows.append(
                {
                    "item_id": item_id,
                    "ref": ref,
                    "format": "nifti",
                    "fp": fp,
                    "labels": o.get("labels"),
                }
            )
            live.outputs.append(
                TaskRunOutput(
                    kind="mask",
                    item_id=item_id,
                    ref=ref,
                    seg_id=self._target_seg(live),
                    sha256=str(sha),
                )
            )
        return rows

    async def _volume_output(self, live: Live, item_id: str, kind: str, o: dict[str, Any]) -> None:
        """A converted volume or sidecar: inside `output_dir` or `dataset/` → the ledger."""
        if "images" not in live.manifest.outputs:
            raise ValueError("task declared no image outputs")
        path = realpath(Path(str(o.get("path", ""))))
        roots = [
            realpath(Path(p))
            for p in (self.runs.read(live.run_dir).output_dir, live.dataset_dir)
            if p
        ]
        if not path.is_file() or not any(is_within(path, r) for r in roots):
            raise ValueError(f"{kind} is not a file inside the run's output_dir or dataset/")
        root = self.workspace.derived_root(live.pid)
        ref = f"{root.alias}:{path.relative_to(realpath(Path(root.path))).as_posix()}"
        sha = o.get("sha256") or await asyncio.to_thread(sha256_file, path)
        live.outputs.append(TaskRunOutput(kind=kind, item_id=item_id, ref=ref, sha256=str(sha)))

    def _target_seg(self, live: Live) -> str:
        rec_settings = self.runs.read(live.run_dir).settings
        s = rec_settings.get("seg_id")
        return s if isinstance(s, str) and s else default_seg_id(live.manifest.id, live.rid)

    async def _register_set(self, live: Live, masks: Sequence[dict[str, Any]]) -> None:
        """TSK-09: the segmentation set is created at the first `ok` item (ADR-0015).

        Label values come from what the run wrote (`progress.jsonl` output `labels`), else
        from the manifest's names (AUD-A5-12); new labels are appended to the label map
        under the project lock, so a concurrent Labels edit is not lost.
        """
        m = live.manifest
        rec = self.runs.read(live.run_dir)
        names = _written_labels(masks)
        if not names and m.labels and isinstance(m.labels.get("names"), dict):
            names = {str(k): str(v) for k, v in m.labels["names"].items()}
        mapping: dict[str, int] = {}
        unmatched: list[int] = []

        def edit(label_map: list[LabelEntry]) -> list[LabelEntry]:
            nonlocal mapping, unmatched
            mapping, unmatched, new_labels = _match_labels(names, label_map)
            return [*label_map, *new_labels]

        await self.workspace.edit_label_map(live.pid, edit)
        seg = SegmentationSet(
            seg_id=self._target_seg(live),
            name=rec.name,
            kind="task",
            producer=SegProducer(
                task_id=m.id, version=m.version, run_id=live.rid, settings_hash=rec.settings_hash
            ),
            label_mapping=mapping,
            unmatched=unmatched,
            created_at=utc_now(),
        )
        await self.workspace.put_segmentation(live.pid, seg)
        live.registered = True
        self.bus.publish(live.pid, "project.updated", {"fields": ["segmentations"]})

    async def _register_tabular(self, live: Live, result: dict[str, Any]) -> None:
        """TSK-09: identity (SRC-07), annotations (ANZ-04), images + metadata → an import."""
        from app.ingest.service import IngestService

        pid, rid, m = live.pid, live.rid, live.manifest
        pdir = self.workspace.project_dir(pid)
        ingest = IngestService(self.workspace, self.store, self.jobs, self.bus, self.locks)
        if isinstance(result.get("identity"), dict):
            returned = identity_store.IdentityRegistry.model_validate(result["identity"])
            async with self.locks(pid):
                merged = identity_store.load(pdir / "sources").merge(returned)
                identity_store.save(pdir / "sources", merged)
        manifest = [o for o in result.get("outputs_manifest") or [] if isinstance(o, dict)]
        new_outputs: list[TaskRunOutput] = []
        activated = False
        for o in manifest:
            if o.get("kind") == "annotations" and "annotations" in m.outputs:
                src = (live.job_dir / str(o.get("path", ""))).resolve()
                if not src.is_file() or not src.is_relative_to(live.job_dir.resolve()):
                    continue
                rows = [r for r in iter_jsonl(src) if r.get("item_id") and r.get("field")]
                async with self.locks(pid):
                    write_jsonl_atomic(live.run_dir / ANNOTATIONS, rows)
                fields = sorted({str(r["field"]) for r in rows})
                cfg = self.workspace.get(pid)
                for f in fields:  # ANZ-04: a new run is active only where none is
                    if not cfg.annotation_sources.get(f):
                        await self.workspace.set_annotation_source(pid, f, rid)
                        activated = True
                new_outputs.append(
                    TaskRunOutput(
                        kind="annotations",
                        ref=f"tasks/runs/{rid}/{ANNOTATIONS}",
                        detail=",".join(fields),
                    )
                )
        imported = False
        try:
            for o in manifest:
                if o.get("kind") != "metadata" or "metadata" not in m.outputs:
                    continue
                path = realpath(Path(str(o.get("path", ""))))
                out_dir = self.runs.read(live.run_dir).output_dir
                if out_dir is None or not is_within(path, realpath(Path(out_dir))):
                    raise ValueError("metadata.jsonl must be inside the run's output_dir")
                root = self.workspace.derived_root(pid)
                data = await asyncio.to_thread(path.read_bytes)
                commit = await ingest.import_generated(
                    pid, data, root=root.path, alias=root.alias, source_key=f"task:{m.id}"
                )
                imported = True
                new_outputs.append(
                    TaskRunOutput(kind="import", ref=commit.import_id, detail=commit.job_id)
                )
        finally:
            if new_outputs:
                async with self.locks(pid):
                    rec = self.runs.read(live.run_dir)
                    rec.outputs = [*rec.outputs, *new_outputs]
                    self.runs.write(live.run_dir, rec)
        if activated and not imported:
            await ingest.reindex(pid)
        if activated:
            self.bus.publish(pid, "project.updated", {"fields": ["annotation_sources"]})

    async def _reindex_masks(self, pid: str) -> None:
        from app.ingest.service import IngestService

        ingest = IngestService(self.workspace, self.store, self.jobs, self.bus, self.locks)
        await ingest.reapply_segmentations(pid)


def _written_labels(masks: Sequence[dict[str, Any]]) -> dict[str, str]:
    """Mask values → names from the outputs' `labels` (a `{value: name}` map or a value list)."""
    out: dict[str, str] = {}
    for row in masks:
        labels = row.get("labels")
        if isinstance(labels, dict):
            out.update({str(k): str(v) for k, v in labels.items() if str(k).isdigit()})
        elif isinstance(labels, list):
            out.update({str(v): "" for v in labels if isinstance(v, int) and v > 0})
    return {k: v for k, v in out.items() if k != "0"}


def _match_labels(
    names: dict[str, str], label_map: Sequence[LabelEntry]
) -> tuple[dict[str, int], list[int], list[LabelEntry]]:
    """ADR-0015 §4: match set labels by name; unmatched → new `label_{value}` entries."""
    by_name = {e.name.lower(): e.value for e in label_map}
    used = {e.value for e in label_map}
    free = [c for c in AUTO_LABEL_COLORS if c.upper() not in {e.color.upper() for e in label_map}]
    colors = free or list(AUTO_LABEL_COLORS)  # skip palette colours already in use
    mapping: dict[str, int] = {}
    unmatched: list[int] = []
    new: list[LabelEntry] = []
    for key, name in sorted(names.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        if not key.isdigit():
            continue
        target = by_name.get(name.lower())
        if target is None:
            value = int(key)
            target = value if value not in used else max(used | {0}) + 1
            used.add(target)
            unmatched.append(int(key))
            new.append(
                LabelEntry(
                    value=target,
                    name=name or auto_label_name(target),
                    color=colors[len(new) % len(colors)],
                    opacity=0.2,
                )
            )
        mapping[key] = target
    return mapping, unmatched, new
