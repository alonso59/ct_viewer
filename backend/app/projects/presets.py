"""Study packs (PRJ-16, ADR-0019) and the phase helpers they configure.

A pack is a first-party plugin contribution (`plugins/<id>/pack.json`, PLG-02 `packs`): label
map, phase vocabulary + aliases + priority, organ profile for `analyzer.target` (ANZ-05) and an
optional radiomics profile. Applying one to a project never deletes data (PRJ-16). With no pack,
phases stay raw (open vocabulary) and labels are auto-named `label_{value}` (PRJ-07).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

UNKNOWN_PHASE = "UNK"
# Raw values that always mean "no phase" (INPUT_METADATA.md §Phase resolution, last row).
MISSING_PHASE_VALUES = frozenset({"", "UNDEFINED", "UNKNOWN", "N/A", "NONE"})
# Shipped plugins (`plugins/` next to `backend/`, `/app/plugins` in the image), as config.py.
BUILTIN_PLUGINS = Path(__file__).resolve().parents[3] / "plugins"
CCRCC = "ccrcc"


@dataclass(frozen=True)
class LabelSeed:
    value: int
    name: str
    color: str
    opacity: float
    visible: bool = True


@dataclass(frozen=True)
class Pack:
    id: str
    title: str
    label_map: tuple[LabelSeed, ...]
    phase_vocabulary: tuple[str, ...]
    phase_mapping: dict[str, str] = field(default_factory=dict)  # RAW (upper) -> canonical
    phase_priority: tuple[str, ...] = ()
    description: str = ""
    plugin: str = ""
    target_profile: str = "generic"  # ANZ-05
    radiomics_profile: dict[str, Any] | None = None


def parse_pack(raw: dict[str, Any], plugin: str) -> Pack:
    """`pack.json` → Pack; raises ValueError (KeyError/TypeError wrapped) on a bad file."""
    try:
        aliases: dict[str, list[str]] = raw.get("phase_aliases") or {}
        return Pack(
            id=str(raw["id"]),
            title=str(raw["title"]),
            description=str(raw.get("description", "")),
            label_map=tuple(LabelSeed(**e) for e in raw.get("label_map") or []),
            phase_vocabulary=tuple(raw.get("phase_vocabulary") or ()),
            phase_mapping={a.upper(): code for code, raws in aliases.items() for a in raws},
            phase_priority=tuple(raw.get("phase_priority") or (UNKNOWN_PHASE,)),
            plugin=plugin,
            target_profile=str(raw.get("target_profile") or "generic"),
            radiomics_profile=raw.get("radiomics_profile"),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid pack: {exc}") from None


@lru_cache(maxsize=8)
def load_packs(root: Path = BUILTIN_PLUGINS) -> dict[str, Pack]:
    """Every pack contributed by a `plugin.json` under `root` (file `pack.json` next to it)."""
    out: dict[str, Pack] = {}
    for manifest in sorted(root.glob("*/plugin.json")) if root.is_dir() else []:
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            ids = (m.get("contributes") or {}).get("packs") or []
            if not ids:
                continue
            pack = parse_pack(json.loads((manifest.parent / "pack.json").read_text()), m["id"])
        except (OSError, ValueError, KeyError, TypeError):
            continue  # the plugin registry reports invalid manifests (API-49)
        if pack.id in ids:
            out[pack.id] = pack
    return out


def get_pack(pack_id: str) -> Pack | None:
    return load_packs().get(pack_id)


def pack_fields(pack: Pack) -> dict[str, Any]:
    """`project.json` fields a pack sets (PRJ-16); the caller merges the label map."""
    return {
        "label_map": [
            {"value": s.value, "name": s.name, "color": s.color, "opacity": s.opacity,
             "visible": s.visible}
            for s in pack.label_map
        ],
        "phase_vocabulary": list(pack.phase_vocabulary),
        "phase_mapping": dict(pack.phase_mapping),
        "phase_priority": list(pack.phase_priority),
    }  # fmt: skip


def target_profile(packs: list[str]) -> str:
    """ANZ-05: the first applied pack with an organ profile, else `generic`."""
    for pid in packs:
        p = get_pack(pid)
        if p is not None and p.target_profile != "generic":
            return p.target_profile
    return "generic"


def normalize_phase_value(raw: str | None, vocabulary: list[str], mapping: dict[str, str]) -> str:
    """Raw phase → canonical code with the project's vocabulary + mapping.

    Case-insensitive. An empty vocabulary is open (`none` preset): the stripped raw value is
    kept. With a vocabulary, anything neither in it nor in the mapping becomes `UNK`.
    """
    text = (raw or "").strip()
    key = text.upper()
    if key in MISSING_PHASE_VALUES:
        return UNKNOWN_PHASE
    if key in mapping:
        return mapping[key]
    upper_vocab = {v.upper(): v for v in vocabulary}
    if key in upper_vocab:
        return upper_vocab[key]
    return text if not vocabulary else UNKNOWN_PHASE


def auto_label_name(value: int) -> str:
    return f"label_{value}"


# Categorical palette for auto-named labels (PRJ-07); cycles past its length.
AUTO_LABEL_COLORS = (
    "#00FFFF", "#FFFF00", "#FF00FF", "#00FF00", "#FF8000", "#0080FF", "#FF0000", "#8000FF",
)  # fmt: skip
