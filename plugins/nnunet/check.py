#!/usr/bin/env python3
"""Runner startup diagnostics for the production nnU-Net profile."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.nnunet.profile import load_profile


def main() -> int:
    try:
        profile = load_profile("kits2023-dataset220")
        missing = [
            command
            for command in ("nnUNetv2_predict", "nnUNetv2_apply_postprocessing")
            if shutil.which(command) is None
        ]
        if missing:
            raise ValueError(f"missing commands: {', '.join(missing)}")
        gpus = [value.strip() for value in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",") if value.strip()]
        if not 2 <= len(gpus) <= 4 or len(set(gpus)) != len(gpus) or "-1" in gpus:
            raise ValueError("CUDA_VISIBLE_DEVICES must expose 2 to 4 distinct GPUs")
    except (OSError, TypeError, ValueError) as exc:
        print(f"segment.nnunet unavailable: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "task": "segment.nnunet",
                "profile": profile.id,
                "dataset": profile.dataset,
                "gpus": gpus,
                "artifacts_sha256": profile.artifacts_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
