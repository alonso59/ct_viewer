"""`voi.extract`: crop one VOI (image + mask) per organ side from each item's mask, and measure
the lesions in each crop as written.

Items run on a thread pool: reading gzip NIfTI and the numpy work release the GIL.
Outputs go to the run's `output_dir` (a derived root) with a `voi_catalog.jsonl`; next to each
crop, `…_hu.json` holds the foreground intensity histogram. At the end, from the whole catalog
(earlier attempts included), the run writes the training files (`lesion_catalog.jsonl`,
`sampling_profile.json`, `dataset_fingerprint.json`) and declares the `lesions` analysis table.
"""

from __future__ import annotations

import json
import os
import re
import traceback
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from plugins.protocol import Job, Outputs, SkipItem, file_values, write_json_atomic
from plugins.voi import engine, lesions, profile

VERSION = "1.1.0"
SWAP = {"L": "R", "R": "L"}
CATALOG = "voi_catalog.jsonl"
# The analysis table columns (the backend checks them when it registers the table).
TABLE_SCHEMA = pa.schema(
    [
        ("item_id", pa.string()),
        ("case_id", pa.string()),
        ("scan_idx", pa.string()),
        ("scope", pa.string()),
        ("side", pa.string()),
        ("phase", pa.string()),
        ("label", pa.int64()),
        ("instance", pa.string()),
        ("group", pa.string()),
        ("name", pa.string()),
        ("value", pa.float64()),
    ]
)
# name, group, unit, description, value of (catalog row, lesion); crops are RAS, so box axes are
# right–left, anterior–posterior and superior–inferior.
COLUMNS: list[tuple[str, str, str, str, Any]] = [
    ("volume_ml", "size", "mL", "Lesion volume", lambda r, x: x["volume_mm3"] / 1000),
    ("max_extent_mm", "size", "mm", "Longest side of the lesion's box", lambda r, x: x["max_extent_mm"]),
    ("extent_rl_mm", "size", "mm", "Box size right–left", lambda r, x: x["bbox_size_mm"][0]),
    ("extent_ap_mm", "size", "mm", "Box size anterior–posterior", lambda r, x: x["bbox_size_mm"][1]),
    ("extent_si_mm", "size", "mm", "Box size superior–inferior", lambda r, x: x["bbox_size_mm"][2]),
    (
        "organ_contact_ratio",
        "position",
        "",
        "Share of the shell around the lesion that is organ",
        lambda r, x: x["organ_contact_ratio"],
    ),
    ("lesions_in_voi", "count", "", "Lesions in the same VOI", lambda r, x: len(r["lesions"])),
]


def _hu(key: str) -> Any:
    return lambda r, x: x["hu"][key]


HU_COLUMNS = [
    (f"hu_{k}", "intensity", "HU", f"Lesion intensity, {d}", _hu(k))
    for k, d in (
        ("mean", "mean"),
        ("std", "standard deviation"),
        ("p5", "5th percentile"),
        ("p50", "median"),
        ("p95", "95th percentile"),
    )
]


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


def lesion_settings(settings: dict[str, Any], region: str, protect: list[str]) -> tuple[list[str], list[str], int]:
    """Lesion and organ label names and the smallest lesion in voxels; no lesion names when
    measuring is off (by default the lesions are the region's protected labels)."""
    if not settings.get("measure_lesions", True):
        return [], [], 0
    names = list(settings.get("lesion_labels") or protect)
    organ = list(settings.get("organ_labels") or engine.REGIONS[region]["organ"])
    return names, organ, int(settings.get("min_lesion_voxels", 10))


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
    values, _ = file_values(labels, project_labels, mapping, organ)
    protect_values, _ = file_values(protect, project_labels, mapping)
    lesion_names, organ_names, min_voxels = lesion_settings(job.settings, region, protect)
    lesion_values, _ = file_values(lesion_names, project_labels, mapping)
    organ_values, _ = file_values(organ_names, project_labels, mapping)
    if not values:
        raise SkipItem(f"none of the labels {labels} is in the project label map")
    hints = engine.side_hints(labels, lambda n: file_values(n, project_labels, mapping)[0])
    anatomy = {
        v: side for organ, side in engine.ANATOMY.items() for v in file_values([organ], project_labels, mapping)[0]
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
        hu_out = case_dir / f"{base}_{suffix}_hu.json"
        written = engine.extract(
            image["path"],
            mask["path"],
            c,
            values,
            str(img_out),
            str(msk_out),
            resample_mm=resample,
            keep_labels=keep,
        )
        hist = lesions.hu_histogram(written.image, np.isin(written.labels, values))
        hu_out.write_text(json.dumps(hist), encoding="utf-8")
        found, below_min = (
            lesions.measure(written.labels, written.image, written.affine, lesion_values, organ_values, min_voxels)
            if lesion_values
            else ([], 0)
        )
        for les in found:  # the project's value of the lesion's label, for analysis tables
            les["label"] = (
                int(mapping.get(str(les["label_value"]), les["label_value"])) if mapping else les["label_value"]
            )
        outputs += [
            {"kind": "image", "path": str(img_out)},
            {"kind": "sidecar", "path": str(msk_out)},
            {"kind": "sidecar", "path": str(hu_out)},
        ]
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
                **written.geo,
                "source_crop": c.to_json()["crop"],
                "tight_size_mm": c.to_json()["tight_size_mm"],
                "crop_size_mm": c.to_json()["crop_size_mm"],
                "volume_ml": round(c.volume_ml, 2),
                "warnings": c.warnings,
                "side_confidence": "reviewer" if ov.get("swap") and c.side in SWAP else c.confidence,
                "hu_histogram": str(hu_out.relative_to(job.output_dir)),
                "lesion_labels": lesion_names if lesion_values else [],
                "lesions": found,
                "lesions_below_min": below_min,
            }
        )
    if not rows:
        raise SkipItem("every VOI of this item was excluded")
    return outputs, rows


def _write_lines(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, path)


def lesion_table(rows: list[dict[str, Any]]) -> tuple[pa.Table, dict[str, Any]]:
    """One row per lesion and column; a scan's lesions are numbered over its VOIs, largest first,
    so lesion 1 is the scan's largest whichever side it is on."""
    columns = COLUMNS + (HU_COLUMNS if any("hu" in x for r in rows for x in r["lesions"]) else [])
    by_item: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for r in rows:
        for x in r["lesions"]:
            by_item[str(r["item_id"])].append((r, x))
    data: dict[str, list[Any]] = {n: [] for n in TABLE_SCHEMA.names}
    for pairs in by_item.values():
        pairs.sort(key=lambda p: (-p[1]["volume_mm3"], str(p[0].get("side")), p[1]["lesion"]))
        for rank, (r, x) in enumerate(pairs, start=1):
            for name, group, _, _, value in columns:
                if name.startswith("hu_") and "hu" not in x:
                    continue
                for key, v in (
                    ("item_id", r["item_id"]),
                    ("case_id", r.get("case_id") or ""),
                    ("scan_idx", str(r.get("scan_idx") or "")),
                    ("scope", "complete"),
                    ("side", r.get("side") or "-"),
                    ("phase", r.get("phase") or ""),
                    ("label", x["label"]),
                    ("instance", str(rank)),
                    ("group", group),
                    ("name", name),
                    ("value", float(value(r, x))),
                ):
                    data[key].append(v)
    spec = {
        "kind": "voi_lesions",
        "title": "VOI lesions",
        "grain": "instance",
        "instance_name": "lesion",
        "columns": [{"name": n, "group": g, "unit": u, "description": d} for n, g, u, d, _ in columns],
        "roles": {"volume": "volume_ml"},
    }
    return pa.Table.from_pydict(data, schema=TABLE_SCHEMA), spec


def training_files(job: Job) -> None:
    """From the whole catalog: the lesion catalog, sampling profile and dataset fingerprint in the
    output folder, and the `lesions` analysis table."""
    assert job.output_dir is not None
    out = job.output_dir
    path = out / CATALOG
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = profile.latest_rows(json.loads(line) for line in lines if line.strip())
    for r in rows:  # rows written before lesions were measured
        r.setdefault("lesions", [])
    spacing = profile.shared_spacing(rows)
    found = profile.lesion_rows(rows)
    prof, bins = profile.build_profile(found, job.settings, spacing)
    for les, b in zip(found, bins, strict=True):
        les["size_bin"] = b
    _write_lines(out / "lesion_catalog.jsonl", found)
    write_json_atomic(out / "sampling_profile.json", prof)
    hists = (json.loads((out / r["hu_histogram"]).read_text(encoding="utf-8")) for r in rows if r.get("hu_histogram"))
    write_json_atomic(out / "dataset_fingerprint.json", profile.build_fingerprint(rows, hists, job.settings, spacing))
    if found:
        table, spec = lesion_table(rows)
        dest = job.dir / "tables" / "lesions.parquet"
        dest.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, dest)
        job.table("lesions", dest, spec)


def run(job_dir: str) -> int:
    job = Job(job_dir)
    profile.profile_settings(job.settings)  # an invalid profile fails the run before any crop
    overrides = {str(o.get("item_id")): o for o in job.settings.get("overrides") or []}
    workers = max(1, int(job.settings.get("workers", 4)))
    todo = [it for it in job.items if str(it["item_id"]) not in job.skip]
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
                    # Written before the item is ok, so a crash never leaves an ok item without
                    # its rows (an item extracted again adds rows; the last ones count).
                    if job.output_dir is not None:
                        with (job.output_dir / CATALOG).open("a", encoding="utf-8") as fh:
                            fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
                    job.item(iid, "ok", outputs)
    if job.output_dir is not None and not job.cancelled():
        training_files(job)
    import nibabel
    import scipy  # type: ignore[import-untyped]

    job.finish(
        versions={
            "voi.extract": VERSION,
            "nibabel": nibabel.__version__,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
        }
    )
    return 0
