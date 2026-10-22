"""Validate queued identity in the configured environment before reserving a GPU."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.nnunet.profile import load_profile
from plugins.runner.identity import verify_job


def verify(spec: dict[str, Any], manifest: Path) -> None:
    profile = load_profile(str(spec.get("settings", {}).get("profile", "")))
    verify_job(
        spec,
        manifest,
        {
            "id": profile.id,
            "profile_sha256": profile.profile_sha256,
            "artifacts_sha256": profile.artifacts_sha256,
        },
    )


if __name__ == "__main__":
    try:
        verify(json.loads((Path(sys.argv[1]) / "job.json").read_text()), Path(__file__).with_name("task.json"))
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"Inference admission refused: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
