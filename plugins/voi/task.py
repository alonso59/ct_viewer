"""`voi.extract`: crop one VOI (image + mask) per organ side from each item's mask.

Items run on a thread pool: reading gzip NIfTI and the numpy work release the GIL.
Outputs go to the run's `output_dir` (a derived root) with a `voi_catalog.jsonl`.
"""

from __future__ import annotations

import json
import re
import traceback
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from plugins.protocol import Job, Outputs, SkipItem
from plugins.voi import engine

VERSION = "1.0.0"
SWAP = {"L": "R", "R": "L"}


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "item"


def settings_for(settings: dict[str, Any]) -> tuple[str, list[str], list[str], float, list[float]]:
    region = str(settings.get("region") or "kidney")
    preset = engine.REGIONS[region]
    labels = list(settings.get("labels") or preset["labels"])
    protect = [p for p in preset["protect"] if p in labels]
    margin = float(settings.get("margin_mm", preset["margin_mm"]))
    min_size = [float(v) for v in (settings.get("min_size_mm") or preset["min_size_mm"])]
    if len(min_size) != 3:
        raise ValueError("min_size_mm needs three values (x, y, z)")
    return region, labels, protect, margin, min_size


def _extract(
    job: Job, item: dict[str, Any], overrides: dict[str, dict[str, Any]]
) -> tuple[Outputs, list[dict[str, Any]]]:
    region, labels, protect, margin, min_size = settings_for(job.settings)
    image = item.get("image")
    masks = item.get("masks") or {}
    if not image or image.get("format") != "nifti":
        raise SkipItem("needs a NIfTI image")
    if not masks:
        raise SkipItem("no mask in the selected segmentation set")
    mask = next(iter(masks.values()))
    if mask.get("format") != "nifti":
        raise SkipItem("needs a NIfTI mask")
    project_labels = {str(k): int(v) for k, v in (job.context.get("labels") or {}).items()}
    mapping = mask.get("label_mapping") or None
    organ = [] if job.settings.get("labels") else engine.REGIONS[region]["organ"]
    values, _ = engine.file_values(labels, project_labels, mapping, organ)
    protect_values, _ = engine.file_values(protect, project_labels, mapping)
    if not values:
        raise SkipItem(f"none of the labels {labels} is in the project label map")
    hints = engine.side_hints(labels, lambda n: engine.file_values(n, project_labels, mapping)[0])
    anatomy = {
        v: side
        for organ, side in engine.ANATOMY.items()
        for v in engine.file_values([organ], project_labels, mapping)[0]
    }
    analysis = engine.analyze(image["path"], mask["path"], values, protect_values, region, hints, anatomy)
    cands = engine.reframe(analysis, margin, min_size)
    if not cands:
        raise SkipItem("the mask holds none of the target labels")
    ov = overrides.get(str(item["item_id"]), {})
    excluded = {str(x) for x in ov.get("exclude") or []}
    assert job.output_dir is not None
    meta = item.get("meta") or {}
    base = _safe(str(item["item_id"]))
    case_dir = job.output_dir / _safe(str(item.get("case_id") or "case"))
    case_dir.mkdir(parents=True, exist_ok=True)
    resample = float(job.settings.get("resample_mm") or 0) or None
    keep = bool(job.settings.get("keep_labels", True))
    outputs: Outputs = []
    rows: list[dict[str, Any]] = []
    for c in cands:
        if c.cid in excluded:
            continue
        side = SWAP.get(c.side, c.side) if ov.get("swap") else c.side
        suffix = side or c.cid
        img_out = case_dir / f"{base}_{suffix}_image.nii.gz"
        msk_out = case_dir / f"{base}_{suffix}_mask.nii.gz"
        geo = engine.extract(
            image["path"],
            mask["path"],
            c,
            values,
            str(img_out),
            str(msk_out),
            resample_mm=resample,
            keep_labels=keep,
        )
        outputs += [{"kind": "image", "path": str(img_out)}, {"kind": "sidecar", "path": str(msk_out)}]
        rows.append(
            {
                "item_id": item["item_id"],
                "case_id": item.get("case_id"),
                "patient_id": meta.get("patient_id"),
                "scan_idx": meta.get("scan_idx"),
                "phase": meta.get("phase"),
                "side": side,
                "candidate": c.cid,
                "side_swapped": bool(ov.get("swap")) and c.side in SWAP,
                "region": region,
                "labels": labels,
                "label_values": values if keep else [1],  # as stored in the mask crop
                "image": str(img_out.relative_to(job.output_dir)),
                "mask": str(msk_out.relative_to(job.output_dir)),
                "format": "nifti",
                "orientation": "RAS",
                **geo,
                "source_crop": c.to_json()["crop"],
                "tight_size_mm": c.to_json()["tight_size_mm"],
                "crop_size_mm": c.to_json()["crop_size_mm"],
                "volume_ml": round(c.volume_ml, 2),
                "warnings": c.warnings,
                "side_confidence": "reviewer" if ov.get("swap") and c.side in SWAP else c.confidence,
            }
        )
    if not rows:
        raise SkipItem("every VOI of this item was excluded")
    return outputs, rows


def run(job_dir: str) -> int:
    job = Job(job_dir)
    overrides = {str(o.get("item_id")): o for o in job.settings.get("overrides") or []}
    workers = max(1, int(job.settings.get("workers", 4)))
    todo = [it for it in job.items if str(it["item_id"]) not in job.skip]
    catalog: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending: dict[Future[tuple[Outputs, list[dict[str, Any]]]], str] = {}
        queue = list(todo)
        while queue or pending:
            while queue and len(pending) < workers * 2 and not job.cancelled():
                it = queue.pop(0)
                pending[pool.submit(_extract, job, it, overrides)] = str(it["item_id"])
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                iid = pending.pop(fut)
                job.counts["items"] += 1
                try:
                    outputs, rows = fut.result()
                except SkipItem as exc:
                    job.item(iid, "skipped", message=str(exc))
                except Exception as exc:  # noqa: BLE001 - per-item failures don't stop the run
                    job.item(iid, "failed", message=f"{type(exc).__name__}: {exc}")
                    job.log(traceback.format_exc(limit=5), "debug")
                else:
                    catalog += rows
                    job.item(iid, "ok", outputs)
    if job.output_dir is not None and catalog:
        with (job.output_dir / "voi_catalog.jsonl").open("a", encoding="utf-8") as fh:
            for row in catalog:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    import nibabel
    import numpy
    import scipy  # type: ignore[import-untyped]

    job.finish(
        versions={
            "voi.extract": VERSION,
            "nibabel": nibabel.__version__,
            "numpy": numpy.__version__,
            "scipy": scipy.__version__,
        }
    )
    return 0
