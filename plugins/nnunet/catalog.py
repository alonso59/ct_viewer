"""SEG-02: operator profiles are validated independently before advertising inference."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from plugins.nnunet.profile import _profiles_dir, load_profile


def catalog(*, trainer_available: Callable[[str], bool] | None = None) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in sorted(_profiles_dir().glob("*.json")):
        entry: dict[str, Any] = {"id": path.stem, "title": path.stem, "available": False}
        try:
            profile = load_profile(path.stem)
            if trainer_available is not None and not trainer_available(profile.predictors[0].trainer):
                raise ValueError("configured nnU-Net trainer is unavailable")
            entry.update(
                title=profile.title,
                available=True,
                reason=None,
                profile_sha256=profile.profile_sha256,
                artifacts_sha256=profile.artifacts_sha256,
                channels=profile.channels,
                labels=profile.labels,
                dataset=profile.dataset,
            )
        except (OSError, TypeError, ValueError) as exc:
            entry["reason"] = str(exc)
            try:
                entry["profile_sha256"] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                entry["profile_sha256"] = None
        entries.append(entry)
    generation = "sha256:" + hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    return {"generation": generation, "profiles": entries}
