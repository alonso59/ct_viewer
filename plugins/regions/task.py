"""`regions.derive`: tumor core, rim and peritumoral band of each item, as a new mask set.

Each item's label map goes to `{output_dir}/{case}/{item}_regions.nii.gz` on the source
mask's grid, and one QC row (voxel counts, volumes, flags) goes to `{output_dir}/qc.jsonl`.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from plugins.protocol import Job, Outputs, SkipItem, file_values
from plugins.regions import morphology

VERSION = "1.0.0"
QC = "qc.jsonl"
GRID_ATOL = 1e-3  # mm; the tolerance mask sets use for member affines


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "item"


def options(settings: dict[str, Any]) -> dict[str, Any]:
    """Normalized settings; raises ValueError for a band that ends before it starts."""
    opts: dict[str, Any] = {
        "regions": [r for r in morphology.VALUES if r in (settings.get("regions") or morphology.VALUES)],
        "tumor_label": str(settings.get("tumor_label") or "tumor"),
        "organ_label": str(settings.get("organ_label") or ""),
        "core_mm": float(settings.get("core_mm", 3.0)),
        "peri_inner_mm": float(settings.get("peri_inner_mm", 2.0)),
        "peri_outer_mm": float(settings.get("peri_outer_mm", 5.0)),
        "min_voxels": int(settings.get("min_voxels", 64)),
    }
    if "peri" in opts["regions"] and opts["peri_outer_mm"] <= opts["peri_inner_mm"]:
        raise ValueError("The peritumoral band must end farther from the tumor than it starts")
    return opts


def _write(path: Path, img: Any) -> None:
    """Gzip without a timestamp, so the same input gives the same bytes."""
    data = gzip.compress(img.to_bytes(), compresslevel=6, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)  # finished files are never rewritten: a new folder per run
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def derive_item(job: Job, item: dict[str, Any], opts: dict[str, Any]) -> tuple[Outputs, dict[str, Any]]:
    import nibabel as nib
    import numpy as np

    masks = item.get("masks") or {}
    if not masks:
        raise SkipItem("no mask in the selected segmentation set")
    mask = next(iter(masks.values()))
    if mask.get("format") != "nifti":
        raise SkipItem("needs a NIfTI mask")
    project_labels = {str(k): int(v) for k, v in (job.context.get("labels") or {}).items()}
    mapping = mask.get("label_mapping") or None
    tumor, _ = file_values([opts["tumor_label"]], project_labels, mapping)
    if not tumor:
        raise SkipItem(f"the label {opts['tumor_label']!r} is not in the project label map")
    organ = None
    if opts["organ_label"]:
        organ, _ = file_values([opts["organ_label"]], project_labels, mapping)

    img: Any = nib.load(mask["path"])
    if len(img.shape) != 3:
        raise ValueError(f"the mask must be 3D, it has shape {tuple(img.shape)}")
    spacing = morphology.spacing_of(img.affine)
    image = item.get("image")
    if image and image.get("format") == "nifti":
        ct: Any = nib.load(image["path"])  # header only
        if tuple(ct.shape[:3]) != tuple(img.shape):
            raise ValueError(f"mask shape {tuple(img.shape)} differs from image shape {tuple(ct.shape[:3])}")
        if not np.allclose(ct.affine, img.affine, rtol=0, atol=GRID_ATOL):
            raise ValueError("the mask affine differs from the image affine")
    labels = np.asanyarray(img.dataobj)
    n_tumor = int(np.isin(labels, tumor).sum())
    if n_tumor == 0:
        raise SkipItem("no tumor voxels in the mask")

    out = morphology.derive(
        labels,
        spacing,
        tumor,
        organ,
        core_mm=opts["core_mm"],
        peri_inner_mm=opts["peri_inner_mm"],
        peri_outer_mm=opts["peri_outer_mm"],
        regions=opts["regions"],
    )
    qc = morphology.quality(
        out,
        n_tumor,
        spacing,
        opts["regions"],
        min_voxels=opts["min_voxels"],
        core_mm=opts["core_mm"],
        peri_width_mm=opts["peri_outer_mm"] - opts["peri_inner_mm"],
    )
    if "peri" in opts["regions"] and opts["organ_label"] and not (organ and np.isin(labels, organ).any()):
        qc["flags"].append("no_organ")

    header = img.header.copy()
    header.set_data_dtype(np.uint8)
    header.set_slope_inter(None, None)
    assert job.output_dir is not None
    path = job.output_dir / _safe(str(item.get("case_id") or "case")) / f"{_safe(str(item['item_id']))}_regions.nii.gz"
    _write(path, nib.Nifti1Image(out, img.affine, header))
    labels_written = {str(morphology.VALUES[r]): morphology.NAMES[r] for r in opts["regions"]}
    row = {"item_id": item["item_id"], "case_id": item.get("case_id"), "mask": path.name, **qc}
    return [{"kind": "mask", "path": str(path), "labels": labels_written}], row


def run(job_dir: str) -> int:
    import nibabel
    import numpy
    import scipy  # type: ignore[import-untyped]

    job = Job(job_dir)
    versions = {
        "regions.derive": VERSION,
        "region_definition": morphology.DEFINITION,
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "nibabel": nibabel.__version__,
    }
    try:
        opts = options(job.settings)
    except ValueError as exc:
        job.finish(versions=versions, status="failed", error=str(exc))
        return 0
    assert job.output_dir is not None
    job.output_dir.mkdir(parents=True, exist_ok=True)
    with (job.output_dir / QC).open("a", encoding="utf-8") as qc:

        def one(job: Job, item: dict[str, Any]) -> Outputs:
            outputs, row = derive_item(job, item, opts)
            qc.write(json.dumps(row, ensure_ascii=False) + "\n")
            qc.flush()
            if row["flags"]:
                job.log(f"{item['item_id']}: {', '.join(row['flags'])}", "warning")
            return outputs

        job.run_items(one)
    job.finish(versions=versions)
    return 0
