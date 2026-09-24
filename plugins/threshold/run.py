"""`segment.threshold`: one mask per item, `image > threshold` → `label` (TST-14).

Runs under both runtimes: builtin (`plugins.threshold.run:run`) and external
(`python run.py <job_dir>` in the runner's env). Needs numpy + nibabel only.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

try:
    from plugins.protocol import Job, Outputs, SkipItem
except ImportError:  # external runtime: plugin dir is the cwd, the repo root is two levels up
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from plugins.protocol import Job, Outputs, SkipItem

VERSION = "0.1.0"


def _segment(job: Job, item: dict[str, Any]) -> Outputs:
    import nibabel as nib
    import numpy as np

    image = item.get("image")
    if not image or image.get("format") != "nifti":
        raise SkipItem("needs a NIfTI image")
    delay = float(job.settings.get("delay_s", 0))
    if delay:
        time.sleep(delay)
    assert job.output_dir is not None
    img: Any = nib.load(image["path"])
    data = np.asanyarray(img.dataobj)
    label = int(job.settings.get("label", 1))
    mask = (data > float(job.settings.get("threshold", 0))).astype(np.uint8) * np.uint8(label)
    out = job.output_dir / f"{item['item_id']}.nii.gz"
    job.output_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp.nii.gz")
    nib.save(nib.Nifti1Image(mask, img.affine), tmp)
    tmp.replace(out)  # finished files are never rewritten (ADR-0014): a new path per run
    return [{"kind": "mask", "path": str(out), "labels": {str(label): "foreground"}}]


def run(job_dir: str) -> int:
    import nibabel
    import numpy

    job = Job(job_dir)
    job.run_items(_segment)
    job.finish(
        versions={
            "segment.threshold": VERSION,
            "numpy": numpy.__version__,
            "nibabel": nibabel.__version__,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]) if len(sys.argv) == 2 else 2)
