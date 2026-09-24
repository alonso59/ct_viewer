"""DICOM value → text helpers shared by the converter and the analyzers (stdlib only)."""

from __future__ import annotations

import re
from datetime import date, time
from typing import Any


def value_to_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, list | tuple):
        return [value_to_json(item) for item in value]
    if hasattr(value, "__iter__"):
        try:
            return [value_to_json(item) for item in value]
        except TypeError:
            pass
    return str(value)


def value_to_text(value: Any) -> str:
    converted = value_to_json(value)
    if converted is None:
        return ""
    if isinstance(converted, list):
        return "\\".join(value_to_text(item) for item in converted)
    return str(converted)


def split_multi_value(value: Any) -> list[str]:
    return [part.strip() for part in value_to_text(value).split("\\") if part.strip()]


def int_or_none(value: Any) -> int | None:
    text = value_to_text(value)
    if not text:
        return None
    try:
        return int(float(text.split("\\")[0]))
    except ValueError:
        return None


def parse_dicom_date(value: Any) -> date | None:
    text = value_to_text(value).replace("-", "")
    if len(text) < 8 or not text[:8].isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def format_dicom_date(value: Any) -> str:
    parsed = parse_dicom_date(value)
    return parsed.isoformat() if parsed else ""


def format_dicom_time(value: Any) -> str:
    text = value_to_text(value).strip()
    if not text:
        return ""
    main, dot, fraction = text.partition(".")
    main = re.sub(r"\D", "", main)
    if len(main) < 2:
        return ""
    main = main.ljust(6, "0")[:6]
    formatted = f"{main[0:2]}:{main[2:4]}:{main[4:6]}"
    if dot and fraction:
        fraction = re.sub(r"\D", "", fraction)[:6]
        if fraction:
            formatted += f".{fraction}"
    return formatted


def parse_time_of_day(value: Any) -> time | None:
    formatted = format_dicom_time(value)
    if not formatted:
        return None
    try:
        return time.fromisoformat(formatted)
    except ValueError:
        return None


def combine_date_time(date_value: Any, time_value: Any) -> str:
    date_text = format_dicom_date(date_value)
    time_text = format_dicom_time(time_value)
    if not date_text:
        return ""
    return f"{date_text}T{time_text}" if time_text else date_text


def normalized_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Upper-case words of the given fields, punctuation folded to spaces."""
    text = " ".join(value_to_text(row.get(key, "")) for key in keys).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def matches_term(text: str, term: str) -> bool:
    normalized = re.sub(r"[^A-Z0-9]+", " ", term.upper()).strip()
    if not normalized:
        return False
    return re.search(rf"\b{re.escape(normalized)}\b", text) is not None


def matches_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(matches_term(text, term) for term in terms)


def geometry_codes(row: dict[str, Any]) -> set[str]:
    raw = row.get("geometry_warning_codes", "")
    if isinstance(raw, list):
        return {str(c) for c in raw if c}
    return {c.strip() for c in value_to_text(raw).split(";") if c.strip()}
