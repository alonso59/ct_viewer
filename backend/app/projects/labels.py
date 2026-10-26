from __future__ import annotations

from collections.abc import Sequence

from app.projects.models import LabelEntry
from app.projects.presets import AUTO_LABEL_COLORS, auto_label_name


def match_labels(
    names: dict[str, str], label_map: Sequence[LabelEntry]
) -> tuple[dict[str, int], list[int], list[LabelEntry]]:
    """Match set labels by name; unmatched values get new project label entries."""
    by_name = {e.name.lower(): e.value for e in label_map}
    used = {e.value for e in label_map}
    free = [c for c in AUTO_LABEL_COLORS if c.upper() not in {e.color.upper() for e in label_map}]
    colors = free or list(AUTO_LABEL_COLORS)
    mapping: dict[str, int] = {}
    unmatched: list[int] = []
    new: list[LabelEntry] = []
    for key, name in sorted(names.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        if not key.isdigit():
            continue
        target = by_name.get(name.lower())
        if target is None:
            value = int(key)
            target = value if value not in used else max(used | {0}) + 1
            used.add(target)
            unmatched.append(int(key))
            new.append(
                LabelEntry(
                    value=target,
                    name=name or auto_label_name(target),
                    color=colors[len(new) % len(colors)],
                    opacity=0.2,
                )
            )
        mapping[key] = target
    return mapping, unmatched, new
