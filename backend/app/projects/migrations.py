"""`project.json` forward migrations (PRJ-11).

`MIGRATIONS[v]` turns a raw v`v` document into v`v+1` (PROJECT_FORMAT.md §Migration).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, get_args

from app.core.errors import FormatVersionUnsupported
from app.projects.models import FORMAT, FORMAT_VERSION, IMPORTED_SEG, Layout
from app.projects.presets import get_pack, pack_fields

Migration = Callable[[dict[str, Any]], dict[str, Any]]


def _v1_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """Roots get `role: source`; one `imported` segmentation set; no active annotations.

    Item `mask` → `masks.imported` happens when the (derived) index is read or rebuilt.
    """
    raw["path_roots"] = [{**r, "role": r.get("role", "source")} for r in raw.get("path_roots", [])]
    if "segmentations" not in raw:
        labels = raw.get("label_map")
        values = [int(e["value"]) for e in labels] if isinstance(labels, list) else [1, 2, 3]
        raw["segmentations"] = [
            {
                "seg_id": IMPORTED_SEG,
                "kind": "imported",
                "producer": None,
                "label_mapping": {str(v): v for v in values},
                "created_at": raw.get("created_at", ""),
            }
        ]
    raw.setdefault("default_seg", IMPORTED_SEG)
    raw.setdefault("annotation_sources", {})
    return raw


def _layout(v2: object) -> str:
    """v2 `viewer_defaults.layout` → a v3 layout id (unknown values fall back to four-up)."""
    known = get_args(Layout)
    v = {"one-up": "one-up-axial"}.get(str(v2), str(v2))
    return v if v in known else "four-up"


def _v2_to_v3(raw: dict[str, Any]) -> dict[str, Any]:
    """ADR-0019: `preset` → `packs`, `viewer_defaults` → `display`, default modality CT.

    Files without `preset` predate presets and meant ccRCC; fields a v2 file left to the old
    (ccRCC) model defaults are filled from that pack so nothing changes meaning.
    """
    preset = raw.pop("preset", "ccrcc")
    raw["packs"] = [] if preset in (None, "none") else [str(preset)]
    pack = get_pack(str(preset)) if preset not in (None, "none") else None
    if pack is not None:
        for key, value in pack_fields(pack).items():
            raw.setdefault(key, value)
    raw.setdefault("default_modality", "CT")
    vd = raw.pop("viewer_defaults", None) or {}
    raw.setdefault(
        "display",
        {
            "layout": _layout(vd.get("layout")),
            "wl": {"CT": {"ww": vd.get("ww", 400), "wl": vd.get("wl", 50)}, "MR": "percentile"},
        },
    )
    raw.setdefault("view_token", None)
    return raw


MIGRATIONS: dict[int, Migration] = {1: _v1_to_v2, 2: _v2_to_v3}


def check_version(raw: object) -> int:
    """Return the document's format_version; raise unless it is ours and not newer."""
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise FormatVersionUnsupported(f"Not a {FORMAT} document")
    version = raw.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise FormatVersionUnsupported("format_version must be an integer")
    if version > FORMAT_VERSION:
        raise FormatVersionUnsupported(
            f"project.json format_version {version} is newer than supported {FORMAT_VERSION}"
        )
    return version


def migrate(raw: dict[str, Any], version: int) -> dict[str, Any]:
    """Apply migrations from `version` up to FORMAT_VERSION."""
    while version < FORMAT_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise FormatVersionUnsupported(f"No migration from format_version {version}")
        raw = step(dict(raw))
        version += 1
        raw["format_version"] = version
    return raw
