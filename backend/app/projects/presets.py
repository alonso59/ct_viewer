"""Study presets (PRJ-12): label map, phase vocabulary, phase mapping and priority.

A preset only seeds `project.json` at creation; every value stays editable afterwards.
`none` keeps raw phase values (open vocabulary) and starts with an empty label map, which
the first index fills with auto-named `label_{value}` entries (PRJ-07).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PresetName = Literal["ccrcc", "generic-ct", "none"]
PRESET_NAMES: tuple[PresetName, ...] = ("ccrcc", "generic-ct", "none")
DEFAULT_PRESET: PresetName = "ccrcc"
UNKNOWN_PHASE = "UNK"
# Raw values that always mean "no phase" (INPUT_METADATA.md §Phase resolution, last row).
MISSING_PHASE_VALUES = frozenset({"", "UNDEFINED", "UNKNOWN", "N/A", "NONE"})


def _aliases(table: dict[str, tuple[str, ...]]) -> dict[str, str]:
    return {raw: code for code, raws in table.items() for raw in raws}


@dataclass(frozen=True)
class LabelSeed:
    value: int
    name: str
    color: str
    opacity: float
    visible: bool = True


@dataclass(frozen=True)
class Preset:
    name: PresetName
    label_map: tuple[LabelSeed, ...]
    phase_vocabulary: tuple[str, ...]
    phase_mapping: dict[str, str] = field(default_factory=dict)  # RAW (upper) -> canonical
    phase_priority: tuple[str, ...] = ()


PRESETS: dict[PresetName, Preset] = {
    "ccrcc": Preset(
        "ccrcc",
        (
            LabelSeed(1, "kidney", "#00FFFF", 0.15),
            LabelSeed(2, "tumor", "#FFFF00", 0.20),
            LabelSeed(3, "cyst", "#FF00FF", 0.15, visible=False),
        ),
        ("NC", "CMP", "NP", "EP", "UNK"),
        _aliases(
            {
                "NC": ("NC", "NONCONTRAST", "NON-CONTRAST"),
                "CMP": ("ART", "ARTERIAL", "CMP", "CORTICOMEDULLARY"),
                "NP": ("VEN", "VENOUS", "NP", "NEPHROGRAPHIC", "PORTAL"),
                "EP": ("EP", "DELAY", "DELAYED", "EXC", "EXCRETORY"),
            }
        ),
        ("NP", "CMP", "NC", "EP", "UNK"),
    ),
    "generic-ct": Preset(
        "generic-ct",
        (),
        ("NC", "ART", "PV", "DELAYED", "UNK"),
        _aliases(
            {
                "NC": ("NC", "NONCONTRAST", "NON-CONTRAST"),
                "ART": ("ART", "ARTERIAL", "CMP", "CORTICOMEDULLARY"),
                "PV": ("PV", "VEN", "VENOUS", "PORTAL", "NP", "NEPHROGRAPHIC"),
                "DELAYED": ("DELAYED", "DELAY", "EP", "EXC", "EXCRETORY"),
            }
        ),
        ("PV", "ART", "NC", "DELAYED", "UNK"),
    ),
    "none": Preset("none", (), (), {}, (UNKNOWN_PHASE,)),
}


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
