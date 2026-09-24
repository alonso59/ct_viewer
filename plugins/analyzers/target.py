"""`analyzer.target` (organ focus, ANZ-*): profile term lists → `target_match`."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from plugins.analyzers import Annotation, annotation, row_key
from plugins.text import normalized_text

RULES_VERSION = "target-1"
KEYS = ("body_part", "study_description", "series_description", "protocol_name", "image_type")


@dataclass(frozen=True)
class Profile:
    name: str
    strong: tuple[str, ...] = ()
    compatible: tuple[str, ...] = ()
    weak: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


PROFILES: dict[str, Profile] = {
    "generic": Profile("generic"),
    "pancreas": Profile(
        "pancreas",
        strong=("PANCREAS",),
        compatible=(
            "ABDOMEN",
            "ABDOMINAL",
            "UPPER ABDOMEN",
            "THORAX ABDOMEN",
            "CHEST ABDOMEN",
            "THORACOABDOMINAL",
            "ABDOMEN PELVIS",
            "LIVER",
            "HEPATO",
            "BILIARY",
            "GALLBLADDER",
            "STOMACH",
            "DUODENUM",
            "RETROPERITONEUM",
        ),
        weak=("CHEST", "THORAX", "TORSO"),
        exclude=(
            "HEAD",
            "BRAIN",
            "NECK",
            "LEG",
            "LEGS",
            "LOWER EXTREMITY",
            "KNEE",
            "FOOT",
            "ARM",
            "SHOULDER",
            "LUNG",
            "HRCT",
            "PULMONARY",
            "CTA CHEST",
            "PE PROTOCOL",
        ),
    ),
    "lung": Profile(
        "lung",
        strong=("LUNG", "CHEST", "THORAX", "HRCT", "PULMONARY"),
        compatible=("CTA CHEST", "PE PROTOCOL", "RESPIRATORY"),
        exclude=("HEAD", "BRAIN", "LEG", "KNEE", "FOOT", "ARM", "ABDOMEN ONLY"),
    ),
    "brain": Profile(
        "brain",
        strong=("BRAIN", "HEAD", "CRANIUM", "SKULL", "CEREBRAL"),
        compatible=("NEURO",),
        exclude=("CHEST", "THORAX", "ABDOMEN", "LEG", "KNEE", "FOOT", "ARM"),
    ),
    "heart": Profile(
        "heart",
        strong=("HEART", "CARDIAC", "CORONARY", "CTA HEART", "CCTA"),
        compatible=("CHEST", "THORAX", "MEDIASTINUM"),
        exclude=("HEAD", "BRAIN", "ABDOMEN ONLY", "LEG", "KNEE", "FOOT", "ARM"),
    ),
    "kidneys": Profile(
        "kidneys",
        strong=("KIDNEY", "KIDNEYS", "RENAL"),
        compatible=("ABDOMEN", "UROGRAM", "URINARY", "RETROPERITONEUM"),
        exclude=("HEAD", "BRAIN", "CHEST ONLY", "LUNG", "LEG", "KNEE", "FOOT", "ARM"),
    ),
}


def profile(name: str | None) -> Profile:
    key = (name or "generic").strip().lower()
    if key not in PROFILES:
        raise ValueError(
            f"Unknown target profile {name!r}; available: {', '.join(sorted(PROFILES))}"
        )
    return PROFILES[key]


def _first(text: str, terms: tuple[str, ...]) -> str:
    import re

    for term in terms:
        t = re.sub(r"[^A-Z0-9]+", " ", term.upper()).strip()
        if t and (
            (" " in t and t in text) or (" " not in t and re.search(rf"\b{re.escape(t)}\b", text))
        ):
            return term
    return ""


def match(row: dict[str, Any], p: Profile) -> tuple[str, str]:
    """(`strong` | `compatible` | `weak` | `excluded` | `none`, evidence)."""
    if p.name == "generic":
        return "strong", "generic profile"
    text = normalized_text(row, KEYS)
    if not text:
        return "none", "insufficient metadata"
    for level, terms in (
        ("strong", p.strong),
        ("compatible", p.compatible),
        ("excluded", p.exclude),
        ("weak", p.weak),
    ):
        term = _first(text, terms)
        if term:
            return level, f"{level} term {term!r} ({p.name})"
    return "none", f"no {p.name} terms"


CONFIDENCE = {
    "strong": "high",
    "compatible": "medium",
    "excluded": "high",
    "weak": "low",
    "none": "unknown",
}


def analyze(rows: Sequence[dict[str, Any]], config: dict[str, Any]) -> list[Annotation]:
    p = profile(config.get("target_profile"))
    out: list[Annotation] = []
    for row in rows:
        level, evidence = match(row, p)
        out.append(
            annotation(
                row_key(row), "target_match", level, CONFIDENCE[level], evidence, RULES_VERSION
            )
        )
    return out
