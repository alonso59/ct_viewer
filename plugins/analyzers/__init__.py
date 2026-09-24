"""Metadata analyzers (ANALYZERS.md, ADR-0017): `analyze(rows, config) → annotations`.

Pure and deterministic; rows only (no pixels, no files). Ported from `legacy/convert/policy.py`
and the phase rules of `legacy/convert/metadata.py` (reference only, R9).
An annotation is `{key, field, value, confidence, evidence, rules_version}` (ANZ-01).
"""

from __future__ import annotations

from typing import Any

Annotation = dict[str, Any]


def annotation(
    key: str, field: str, value: Any, confidence: str, evidence: str, version: str
) -> Annotation:
    return {
        "key": key,
        "field": field,
        "value": value,
        "confidence": confidence,  # high | medium | low | unknown (ANZ-03)
        "evidence": evidence,
        "rules_version": version,
    }


def row_key(row: dict[str, Any]) -> str:
    """`item_id` in a project; `(case identity key, series_uid)` inside the converter (ANZ-01)."""
    iid = row.get("item_id")
    if iid:
        return str(iid)
    return f"{row.get('case_identity_key', '')}|{row.get('series_uid', '')}"
