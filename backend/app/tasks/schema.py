"""Settings validation for the manifest's JSON Schema subset (TSK-02; TASKS.md §Manifest).

Supported: `object` with `properties` / `required` / `additionalProperties` (default false),
`boolean`, `integer`, `number` (`minimum`, `maximum`), `string` (`enum`, `minLength`,
`maxLength`, `pattern`), `array` (`items`, `minItems`, `maxItems`); `default` everywhere.
UI hints `x-group`, `x-help`, `x-advanced` are ignored here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from app.tasks.models import SettingsIssue

Loc = list[str | int]
TYPES = {"object", "boolean", "integer", "number", "string", "array"}


def check_schema(schema: Mapping[str, Any], loc: str = "settings_schema") -> None:
    """Raise ValueError when the schema uses anything outside the subset (invalid manifest)."""
    t = schema.get("type")
    if t not in TYPES:
        raise ValueError(f"{loc}: type must be one of {sorted(TYPES)}")
    if t == "object":
        props = schema.get("properties", {})
        if not isinstance(props, dict):
            raise ValueError(f"{loc}.properties must be an object")
        for name, sub in props.items():
            if not isinstance(sub, dict):
                raise ValueError(f"{loc}.properties.{name} must be an object")
            check_schema(sub, f"{loc}.properties.{name}")
        req = schema.get("required", [])
        if not isinstance(req, list) or any(r not in props for r in req):
            raise ValueError(f"{loc}.required must list defined properties")
    elif t == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise ValueError(f"{loc}.items must be an object")
        check_schema(items, f"{loc}.items")
    if "pattern" in schema:
        re.compile(str(schema["pattern"]))


def _defaults(schema: Mapping[str, Any]) -> Any:
    if "default" in schema:
        return schema["default"]
    if schema.get("type") == "object":
        out = {}
        for name, sub in schema.get("properties", {}).items():
            d = _defaults(sub)
            if d is not None:
                out[name] = d
        return out
    return None


def _check(value: Any, schema: Mapping[str, Any], loc: Loc, issues: list[SettingsIssue]) -> Any:
    t = schema.get("type")

    def bad(msg: str, rule: str = "type") -> None:
        issues.append(SettingsIssue(loc=loc, msg=msg, rule=rule))

    if t == "object":
        if not isinstance(value, dict):
            bad("Must be an object")
            return value
        props: dict[str, Any] = schema.get("properties", {})
        out: dict[str, Any] = {}
        for name, v in value.items():
            if name not in props:
                if schema.get("additionalProperties", False):
                    out[name] = v
                else:
                    issues.append(
                        SettingsIssue(loc=[*loc, name], msg="Unknown setting", rule="unknown")
                    )
                continue
            out[name] = _check(v, props[name], [*loc, name], issues)
        for name in schema.get("required", []):
            if name not in out:
                issues.append(SettingsIssue(loc=[*loc, name], msg="Required", rule="required"))
        return out
    if t == "boolean":
        if not isinstance(value, bool):
            bad("Must be true or false")
        return value
    if t in ("integer", "number"):
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        if t == "integer" and ok and isinstance(value, float):
            ok = value.is_integer()
            value = int(value) if ok else value
        if not ok:
            bad("Must be an integer" if t == "integer" else "Must be a number")
            return value
        if "minimum" in schema and value < schema["minimum"]:
            bad(f"Must be ≥ {schema['minimum']}", "range")
        if "maximum" in schema and value > schema["maximum"]:
            bad(f"Must be ≤ {schema['maximum']}", "range")
        return value
    if t == "string":
        if not isinstance(value, str):
            bad("Must be text")
            return value
        if "enum" in schema and value not in schema["enum"]:
            bad(f"Must be one of {schema['enum']}", "enum")
        if len(value) < schema.get("minLength", 0):
            bad(f"At least {schema['minLength']} characters", "range")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            bad(f"At most {schema['maxLength']} characters", "range")
        if "pattern" in schema and not re.search(str(schema["pattern"]), value):
            bad("Does not match the expected pattern", "pattern")
        return value
    if t == "array":
        if not isinstance(value, list):
            bad("Must be a list")
            return value
        if len(value) < schema.get("minItems", 0):
            bad(f"At least {schema['minItems']} entries", "range")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            bad(f"At most {schema['maxItems']} entries", "range")
        return [_check(v, schema["items"], [*loc, i], issues) for i, v in enumerate(value)]
    return value


def normalize(
    schema: Mapping[str, Any], defaults: Mapping[str, Any], settings: Mapping[str, Any]
) -> tuple[dict[str, Any], list[SettingsIssue]]:
    """Schema defaults ← manifest defaults ← given settings, then validated."""
    base = _defaults(schema)
    merged = {**(base if isinstance(base, dict) else {}), **defaults, **settings}
    issues: list[SettingsIssue] = []
    out = _check(merged, schema, [], issues)
    return (out if isinstance(out, dict) else {}), issues


def settings_hash(task_id: str, version: str, settings: Mapping[str, Any]) -> str:
    """Content hash of normalized settings for one task version (TSK-10)."""
    blob = json.dumps(
        {"task": task_id, "version": version, "settings": settings},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()
