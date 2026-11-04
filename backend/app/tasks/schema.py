"""Task settings validation; the implementation is shared with the converter package."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rw_dicom import settings as shared
from rw_dicom.settings import check_schema, settings_hash

from app.tasks.models import SettingsIssue

__all__ = ["check_schema", "normalize", "settings_hash"]


def normalize(
    schema: Mapping[str, Any], defaults: Mapping[str, Any], settings: Mapping[str, Any]
) -> tuple[dict[str, Any], list[SettingsIssue]]:
    """Schema defaults ← manifest defaults ← given settings, then validated."""
    out, issues = shared.normalize(schema, defaults, settings)
    return out, [SettingsIssue(loc=i.loc, msg=i.msg, rule=i.rule) for i in issues]
