"""Pinned IBSI feature map (`ibsi_map.json`, RADIOMICS.md §IBSI alignment).

Metadata only (never shown in the GUI). Filtered image types are outside IBSI 1, so their
features export with status `not_defined` (keeping the concept code).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.radiomics.models import IbsiInfo, IbsiStatus

MAP_PATH = Path(__file__).with_name("ibsi_map.json")


@lru_cache(maxsize=1)
def ibsi_map() -> dict[str, Any]:
    with MAP_PATH.open("rb") as fh:
        data: dict[str, Any] = json.loads(fh.read().decode("utf-8"))
    return data


def map_version() -> str:
    return str(ibsi_map()["version"])


def lookup(feature_class: str, feature: str) -> IbsiInfo:
    entry = ibsi_map()["features"].get(feature_class, {}).get(feature)
    if entry is None:
        return IbsiInfo()
    return IbsiInfo(code=entry.get("code"), status=entry.get("status", "not_defined"))


def export_info(image_type: str, feature_class: str, feature: str) -> tuple[str | None, IbsiStatus]:
    """(`ibsi_code`, `ibsi_status`) for an output row of `image_type` (e.g. `original`)."""
    info = lookup(feature_class, feature)
    in_scope = image_type in ibsi_map().get("image_types_in_scope", ["original"])
    return info.code, info.status if in_scope else "not_defined"
