"""Plain causes for radiomics skips and failures (RAD-07, TSK-04, UI-18; AUD-A2-05).

A row of `errors.jsonl` carries a stable `code`, a short sentence in plain words (`error`) and,
for engine failures, the engine's own text (`detail`). Items the index already knows are not
ready (no image, no mask, a blocking IMP-08 code) are skipped at planning time, never failed.
A geometry defect is never answered with "raise `geometryTolerance`": a shifted mask would give
features of the wrong voxels.
"""

from __future__ import annotations

import re
from typing import Final

from app.selection.readiness import BLOCKING, blocking

__all__ = ["BLOCKING", "blocking", "explain", "text"]

TEXT: Final[dict[str, str]] = {
    "no_image": "The item has no image.",
    "no_mask": "The item has no mask in this segmentation set.",
    "missing_path": "A file of this item does not exist.",
    "unreadable_file": "A file of this item cannot be read.",
    "outside_root": "A file of this item is outside the data roots.",
    "missing_seg": "The item has no mask.",
    "affine_mismatch": "The mask does not line up with the image (position, spacing or direction "
    "differ). Fix or re-import the mask.",
    "shape_mismatch": "The mask and the image have a different size. Fix or re-import the mask.",
    "label_absent": "The label is not in this item's mask.",
    "label_not_in_set": "The segmentation set does not map this label.",
    "roi_too_small": "The masked region is too small for the chosen settings.",
    "input_missing": "An input file is missing or cannot be read.",
    "input_changed": "The image or mask changed since the run started. Start a new run.",
    "engine": "Feature extraction failed.",
}

_ENGINE: Final[list[tuple[re.Pattern[str], str]]] = [
    (re.compile(r"size \[|sitkImageFilter|doesn't match size|dimensions? don't match", re.I),
     "shape_mismatch"),
    (re.compile(r"geometry ?mismatch|geometryTolerance|same physical space", re.I),
     "affine_mismatch"),
    (re.compile(r"label \(?\d+\)? not present|not present in mask|no labels found", re.I),
     "label_absent"),
    (re.compile(r"\broi\b|too small|minimumROI", re.I), "roi_too_small"),
    (re.compile(r"no such file|not found|cannot (open|read)|unable to (open|read)", re.I),
     "input_missing"),
]  # fmt: skip


def text(code: str) -> str:
    return TEXT.get(code, TEXT["engine"])


def explain(raw: str) -> str:
    """Engine error text → a cause code (`engine` when nothing matches)."""
    return next((code for pat, code in _ENGINE if pat.search(raw)), "engine")
