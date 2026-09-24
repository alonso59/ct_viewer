"""`analyzer.phase` (ANZ-*): text terms first, contrast timing second; conflicts → UNK."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from plugins.analyzers import Annotation, annotation, row_key
from plugins.text import matches_any, normalized_text, parse_time_of_day, value_to_text

RULES_VERSION = "phase-1"
TEXT_KEYS = (
    "series_description",
    "protocol_name",
    "study_description",
    "image_type",
    "body_part",
    "scan_options",
)
PHASE_KEYS = ("study_description", "series_description", "protocol_name")
# Canonical guesses → vocabulary candidates, first one in the project vocabulary wins (ANZ-05/06)
VOCAB = {"NC": ("NC",), "CMP": ("CMP", "ART"), "NP": ("NP", "PV"), "EX": ("EP", "DELAYED")}
UNKNOWN = "UNK"


def text_guess(row: dict[str, Any]) -> tuple[str, str, str, bool]:
    """(canonical, confidence, evidence, weak) from descriptions; weak = arterial without CMP."""
    text = normalized_text(row, TEXT_KEYS)
    phase_text = normalized_text(row, PHASE_KEYS)
    if not text:
        return "", "", "", False
    if matches_any(
        text,
        (
            "NONCONTRAST",
            "NON CONTRAST",
            "NO CONTRAST",
            "WITHOUT CONTRAST",
            "W O CONTRAST",
            "WO CONTRAST",
            "PRECONTRAST",
            "PRE CONTRAST",
            "UNENHANCED",
            "NATIVE",
            "PLAIN",
        ),
    ):
        return "NC", "high", "non-contrast text", False
    if matches_any(text, ("CORTICOMEDULLARY", "CORTICO MEDULLARY", "CMP")):
        return "CMP", "high", "corticomedullary text", False
    if matches_any(text, ("NEPHROGRAPHIC", "NP", "PARENCHYMAL", "RENAL PARENCHYMAL")):
        return "NP", "high", "nephrographic text", False
    if matches_any(text, ("EXCRETORY", "UROGRAM", "UROGRAPHIC", "PYELOGRAPHIC")):
        return "EX", "high", "excretory text", False
    if matches_any(phase_text, ("DELAYED", "LATE")):
        return "EX", "high", "delayed phase text", False
    if matches_any(text, ("VENOUS", "PORTAL VENOUS")) and matches_any(
        text,
        (
            "ABDOMEN",
            "ABDOMINAL",
            "KIDNEY",
            "KIDNEYS",
            "RENAL",
            "UROGRAM",
            "URINARY",
            "RETROPERITONEUM",
            "PELVIS",
        ),
    ):
        return "NP", "high", "venous abdominal/renal text", False
    if matches_any(text, ("ARTERIAL", "EARLY ARTERIAL", "ANGIO", "CTA")):
        return "CMP", "low", "arterial text without explicit CMP", True
    return "", "", "", False


def contrast_delay(row: dict[str, Any]) -> tuple[int | None, str]:
    start = parse_time_of_day(row.get("contrast_start_time", ""))
    if start is None:
        return None, ""
    keys = ["acquisition_time", "series_time", "content_time"]
    if row.get("scan_datetime_source") != "study":
        keys.append("scan_time")
    for key in keys:
        t = parse_time_of_day(row.get(key, ""))
        if t is None:
            continue
        delay = (t.hour * 3600 + t.minute * 60 + t.second) - (
            start.hour * 3600 + start.minute * 60 + start.second
        )
        if delay < 0:
            if delay + 24 * 3600 > 6 * 3600:
                continue
            delay += 24 * 3600
        return delay, key
    return None, ""


def timing_guess(row: dict[str, Any], delay: int | None, source: str) -> tuple[str, str, str, bool]:
    if value_to_text(row.get("modality", "")).upper() != "CT" or delay is None:
        return "", "", "", False
    evidence = f"delay {delay} s ({source})"
    if 15 <= delay <= 24 or 46 <= delay <= 60:
        return "CMP", "low", evidence, True
    if 25 <= delay <= 45:
        if matches_any(
            normalized_text(row, TEXT_KEYS), ("CORTICOMEDULLARY", "CORTICO MEDULLARY", "CMP")
        ):
            return "CMP", "medium", evidence, False
        return "CMP", "low", evidence, True
    if 70 <= delay <= 130:
        return "NP", "medium", evidence, False
    if delay >= 180:
        return "EX", "medium", evidence, False
    return "", "", "", False


def _has_contrast(row: dict[str, Any]) -> bool:
    keys = (
        "contrast_agent",
        "contrast_route",
        "contrast_volume",
        "contrast_start_time",
        "contrast_stop_time",
        "contrast_flow_rate",
        "contrast_flow_duration",
    )
    return any(value_to_text(row.get(k, "")).strip() for k in keys)


def to_vocabulary(canonical: str, vocabulary: Sequence[str]) -> str:
    """ANZ-06: a vocabulary value or UNK; an empty (open) vocabulary keeps the canonical code."""
    if not canonical:
        return UNKNOWN
    if not vocabulary:
        return canonical
    return next((v for v in VOCAB.get(canonical, ()) if v in vocabulary), UNKNOWN)


def guess(row: dict[str, Any], vocabulary: Sequence[str]) -> tuple[str, str, str, dict[str, Any]]:
    """(value, confidence, evidence, extras with contrast_delay_*)."""
    t_phase, t_conf, t_ev, t_weak = text_guess(row)
    delay, source = contrast_delay(row)
    g_phase, g_conf, g_ev, g_weak = timing_guess(row, delay, source)
    extras = {"contrast_delay_seconds": delay, "contrast_delay_source": source}
    if t_phase:
        if g_phase and g_phase != t_phase:
            return UNKNOWN, "low", f"text/timing conflict: {t_ev} vs {g_ev}", extras
        if t_weak:  # compound guess ("CMP; unknown") → UNK, low (ANZ-06)
            return UNKNOWN, "low", f"{t_ev} (possible {to_vocabulary(t_phase, vocabulary)})", extras
        value = to_vocabulary(t_phase, vocabulary)
        return value, t_conf if value != UNKNOWN else "low", t_ev, extras
    if g_phase:
        if g_weak:
            return UNKNOWN, "low", f"{g_ev} (possible {to_vocabulary(g_phase, vocabulary)})", extras
        value = to_vocabulary(g_phase, vocabulary)
        return value, g_conf if value != UNKNOWN else "low", g_ev, extras
    if _has_contrast(row):
        return UNKNOWN, "unknown", "contrast without phase evidence", extras
    return UNKNOWN, "unknown", "no phase evidence", extras


def analyze(rows: Sequence[dict[str, Any]], config: dict[str, Any]) -> list[Annotation]:
    vocabulary = list(config.get("phase_vocabulary") or [])
    out: list[Annotation] = []
    for row in rows:
        value, confidence, evidence, _ = guess(row, vocabulary)
        out.append(annotation(row_key(row), "phase", value, confidence, evidence, RULES_VERSION))
    return out
