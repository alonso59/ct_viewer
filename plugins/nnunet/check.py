#!/usr/bin/env python3
"""Runner startup diagnostics for independently registered nnU-Net profiles."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.nnunet.catalog import catalog


def trainer_available(name: str) -> bool:
    try:
        nnunetv2 = importlib.import_module("nnunetv2")
        finder = importlib.import_module("nnunetv2.utilities.find_class_by_name")
        package_file = nnunetv2.__file__
        if package_file is None:
            return False

        return (
            finder.recursive_find_python_class(
                str(Path(package_file).parent / "training/nnUNetTrainer"),
                name,
                "nnunetv2.training.nnUNetTrainer",
            )
            is not None
        )
    except (ImportError, AttributeError):
        return False


def main() -> int:
    try:
        snapshot = catalog(trainer_available=trainer_available)
        if not any(profile["available"] for profile in snapshot["profiles"]):
            raise ValueError("no compatible validated model profile: " + json.dumps(snapshot["profiles"]))
        missing = [
            command
            for command in ("nnUNetv2_predict", "nnUNetv2_apply_postprocessing")
            if shutil.which(command) is None
        ]
        if missing:
            raise ValueError(f"missing commands: {', '.join(missing)}")
        gpus = [value.strip() for value in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",") if value.strip()]
        if not 1 <= len(gpus) <= 7 or len(set(gpus)) != len(gpus) or "-1" in gpus:
            raise ValueError("CUDA_VISIBLE_DEVICES must expose 1 to 7 distinct approved pool devices")
    except (OSError, TypeError, ValueError) as exc:
        print(f"segment.nnunet unavailable: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "task": "segment.nnunet",
                "gpus": gpus,
                "model_catalog": snapshot,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
