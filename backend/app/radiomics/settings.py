"""Schema-driven settings normalization, canonical JSON and `profile_hash` (RAD-01/03/04).

Engine-agnostic: every check here is derived from the engine's `SettingsSchema` (types,
constraints, defaults, known filters/classes/features). Engine-specific rules (RADIOMICS.md
§Validation rules) live with the adapter and run on the normalized result.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.radiomics.models import Issue, OptionSpec, RadiomicsSettings, SettingsSchema

Loc = list[str | int]
SET_LIKE: frozenset[str] = frozenset({"sigma", "distances"})  # order carries no meaning


def _num_ok(spec: OptionSpec, v: float) -> bool:
    c = spec.constraints
    if c.min is not None and (v <= c.min if c.exclusive_min else v < c.min):
        return False
    return not (c.max is not None and (v >= c.max if c.exclusive_max else v > c.max))


def _range_text(spec: OptionSpec) -> str:
    c = spec.constraints
    parts = []
    if c.min is not None:
        parts.append(f"{'>' if c.exclusive_min else '≥'} {c.min:g}")
    if c.max is not None:
        parts.append(f"{'<' if c.exclusive_max else '≤'} {c.max:g}")
    return "Must be " + " and ".join(parts) if parts else "Out of range"


def _scalar(
    spec: OptionSpec, kind: str, v: Any, loc: Loc, issues: list[Issue], msg: str | None
) -> Any:
    def bad(text: str, rule: str = "type") -> None:
        issues.append(Issue(loc=loc, msg=msg if rule == "constraint" and msg else text, rule=rule))

    if kind == "bool":
        if not isinstance(v, bool):
            bad("Must be true or false")
            return None
        return v
    if kind in ("int", "float"):
        if isinstance(v, bool) or not isinstance(v, int | float):
            bad("Must be a number")
            return None
        if not math.isfinite(v):
            bad("Must be a finite number")
            return None
        if kind == "int":
            if not float(v).is_integer():
                bad("Must be a whole number")
                return None
            v = int(v)
        else:
            v = float(v)
        if not _num_ok(spec, float(v)):
            bad(_range_text(spec), "constraint")
            return None
        return v
    if not isinstance(v, str):
        bad("Must be text")
        return None
    enum = spec.constraints.enum
    if enum is not None and v not in enum:
        bad(f"Must be one of: {', '.join(enum)}", "constraint")
        return None
    return v


def coerce(
    spec: OptionSpec, value: Any, loc: Loc, issues: list[Issue], msg: str | None = None
) -> Any:
    """Type-check + constrain one option value; appends issues and returns the coerced value."""
    if value is None:
        if not spec.nullable:
            issues.append(Issue(loc=loc, msg="A value is required", rule="type"))
        return None
    if spec.type in ("float_list", "int_list"):
        if isinstance(value, int | float) and not isinstance(value, bool):
            value = [value]  # a single number is accepted as a one-element list
        if not isinstance(value, list):
            issues.append(Issue(loc=loc, msg="Must be a list of numbers", rule="type"))
            return None
        kind = "int" if spec.type == "int_list" else "float"
        n = len(issues)
        out = [_scalar(spec, kind, x, [*loc, i], issues, msg) for i, x in enumerate(value)]
        if len(issues) > n:
            return None
        c = spec.constraints
        if (c.min_items is not None and len(out) < c.min_items) or (
            c.max_items is not None and len(out) > c.max_items
        ):
            count = (
                f"exactly {c.min_items}"
                if c.min_items == c.max_items
                else f"{c.min_items or 0}..{c.max_items if c.max_items is not None else '∞'}"
            )
            issues.append(Issue(loc=loc, msg=msg or f"Needs {count} values", rule="constraint"))
            return None
        if spec.name in SET_LIKE:
            out = sorted(set(out))
        return out
    return _scalar(spec, spec.type, value, loc, issues, msg)


def _options(
    specs: Sequence[OptionSpec],
    raw: Mapping[str, Any] | None,
    loc: Loc,
    issues: list[Issue],
    messages: Mapping[str, str],
) -> dict[str, Any]:
    by_name = {s.name: s for s in specs}
    raw = raw or {}
    for k in raw:
        if k not in by_name:
            issues.append(Issue(loc=[*loc, k], msg="Unknown option", rule="unknown"))
    out: dict[str, Any] = {}
    for s in specs:
        v = raw.get(s.name, s.default)
        out[s.name] = coerce(s, v, [*loc, s.name], issues, messages.get(s.name))
    return out


def normalize(
    schema: SettingsSchema,
    raw: RadiomicsSettings | None,
    messages: Mapping[str, str] | None = None,
) -> tuple[RadiomicsSettings | None, list[Issue]]:
    """Fill defaults, coerce, sort features. Returns (None, issues) if any value is unusable."""
    raw = raw or RadiomicsSettings()
    msgs = messages or {}
    issues: list[Issue] = []
    filters = {f.name: f for f in schema.filters}
    classes = {c.name: c for c in schema.feature_classes}

    image_types: dict[str, dict[str, Any]] = {}
    src_types = (
        raw.image_types
        if raw.image_types is not None
        else {f.name: {} for f in schema.filters if f.default_enabled}
    )
    for name, params in src_types.items():
        f = filters.get(name)
        if f is None:
            issues.append(Issue(loc=["image_types", name], msg="Unknown filter", rule="unknown"))
            continue
        if not f.available:
            issues.append(
                Issue(
                    loc=["image_types", name],
                    msg=f"Filter not available: {f.unavailable_reason or 'engine'}",
                    rule="unavailable",
                )
            )
            continue
        if params is not None and not isinstance(params, dict):
            issues.append(Issue(loc=["image_types", name], msg="Must be an object", rule="type"))
            continue
        image_types[name] = _options(f.params, params, ["image_types", name], issues, msgs)

    features: dict[str, list[str] | None] = {}
    src_features = (
        raw.features
        if raw.features is not None
        else {c.name: None for c in schema.feature_classes if c.default_enabled}
    )
    for cname, names in src_features.items():
        c = classes.get(cname)
        if c is None:
            issues.append(
                Issue(loc=["features", cname], msg="Unknown feature class", rule="unknown")
            )
            continue
        known = {f.name for f in c.features}
        if names is None:
            chosen = {f.name for f in c.features if f.default_enabled}
        else:
            if not isinstance(names, list):
                issues.append(
                    Issue(loc=["features", cname], msg="Must be a list of features", rule="type")
                )
                continue
            chosen = set()
            for i, n in enumerate(names):
                if n not in known:
                    issues.append(
                        Issue(loc=["features", cname, i], msg="Unknown feature", rule="unknown")
                    )
                else:
                    chosen.add(n)
        if chosen:
            features[cname] = sorted(chosen)

    options = _options(schema.options, raw.settings, ["settings"], issues, msgs)
    norm = RadiomicsSettings(image_types=image_types, features=features, settings=options)
    blocking = [i for i in issues if i.severity == "error"]
    return (None if blocking else norm), issues


# -- canonical JSON + hash (RAD-03) -------------------------------------------------------


def _canon(v: Any) -> Any:
    if v is None or isinstance(v, bool | str):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("non-finite numbers are not allowed in settings")
        if v.is_integer() and abs(v) < 2**53:
            return int(v)  # 25 == 25.0; also folds -0.0 into 0
        return v
    if isinstance(v, Mapping):
        return {str(k): _canon(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    if isinstance(v, list | tuple):
        return [_canon(x) for x in v]
    raise TypeError(f"not JSON-serializable: {type(v).__name__}")


def canonical_json(obj: Any) -> str:
    """Sorted keys, no whitespace, integral floats as ints, shortest float repr."""
    return json.dumps(
        _canon(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def profile_hash(settings: RadiomicsSettings, engine_name: str, engine_major: str) -> str:
    """`sha256:` of canonical JSON of normalized settings + engine name + major (RAD-03)."""
    payload = {
        "engine": {"name": engine_name, "major": engine_major},
        "settings": settings.model_dump(mode="json"),
    }
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def engine_major(version: str) -> str:
    head = version.split(".", 1)[0]
    return "".join(ch for ch in head if ch.isdigit()) or head
