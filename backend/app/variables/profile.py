"""Value parsing and type inference (VAR-01..03, VARIABLES.md §Type inference rules).

Pure functions over one variable's values at its level (one value per case or per scan).
`None` is missing; the empty string is missing too (callers normalize with `as_text`).
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.variables.models import Profile, ValueCount, VarType

CONTINUOUS_MIN_DISTINCT = 10
CATEGORICAL_MAX_DISTINCT = 20
CATEGORICAL_MAX_SHARE = 0.05
NUMERIC_SHARE = 0.95
DATE_SHARE = 0.95
IDENTIFIER_SHARE = 0.95
REVIEW_BELOW = 0.8
TOP_N = 20

_YYYYMMDD = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")
_AGE = re.compile(r"^(\d{1,3})\s*([DWMY]?)$", re.IGNORECASE)
_AGE_UNIT_YEARS = {"": 1.0, "Y": 1.0, "M": 1 / 12, "W": 7 / 365.25, "D": 1 / 365.25}


def as_text(value: Any) -> str | None:
    """Canonical string form of a raw JSON scalar; None for missing and for blobs."""
    if value is None or isinstance(value, (dict, list)):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return str(int(value)) if value.is_integer() else repr(value)
    s = f"{value}".strip()
    return s or None


def as_number(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        v = float(text)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def as_date(text: str | None) -> str | None:
    """ISO date/datetime or `YYYYMMDD` → ISO date(time) string; None if not a valid date."""
    if text is None:
        return None
    m = _YYYYMMDD.match(text)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            return None
    if _ISO.match(text):
        try:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return text
    return None


def parse_age_years(text: str | None) -> float | None:
    """DICOM AS (`045Y`, `006M`, `012W`, `030D`) or a bare number → years (VAR-08)."""
    if text is None:
        return None
    m = _AGE.match(text.strip())
    if not m:
        return None
    return round(int(m[1]) * _AGE_UNIT_YEARS[m[2].upper()], 4)


@dataclass(frozen=True)
class Inference:
    type: VarType
    confidence: float
    review: bool


def _sequential_ints(nums: Sequence[float]) -> bool:
    if not all(float(n).is_integer() for n in nums):
        return False
    span = max(nums) - min(nums) + 1
    return span <= 1.5 * len(nums)


def infer_type(values: Sequence[str | None]) -> Inference:
    """VARIABLES.md §Type inference rules, applied to non-missing values in this order:
    constant → date → numeric (continuous / numeric-discrete / sequential-integer identifier)
    → categorical → identifier → text."""
    present = [v for v in values if v is not None]
    n = len(present)
    distinct = set(present)
    if len(distinct) <= 1:
        return Inference("constant", 1.0, False)
    date_share = sum(as_date(v) is not None for v in present) / n
    if date_share >= DATE_SHARE:
        return Inference("date", date_share, date_share < REVIEW_BELOW)
    nums = [x for x in (as_number(v) for v in present) if x is not None]
    num_share = len(nums) / n
    if num_share >= NUMERIC_SHARE:
        n_distinct = len({x for x in nums})
        if n_distinct < CONTINUOUS_MIN_DISTINCT:
            return Inference("numeric-discrete", 0.5, True)
        if n_distinct == n and n >= CONTINUOUS_MIN_DISTINCT and _sequential_ints(nums):
            return Inference("identifier", 0.6, True)
        conf = num_share
        return Inference("continuous", conf, conf < 1.0)
    if len(distinct) <= CATEGORICAL_MAX_DISTINCT or len(distinct) <= CATEGORICAL_MAX_SHARE * n:
        # Mostly-numeric columns that failed the numeric rule deserve a second look.
        conf = 0.7 if num_share >= 0.5 else 1.0
        return Inference("categorical", conf, conf < REVIEW_BELOW)
    if len(distinct) >= IDENTIFIER_SHARE * n:
        return Inference("identifier", 0.9, False)
    return Inference("text", 0.9, False)


def profile(values: Sequence[str | None]) -> Profile:
    present = [v for v in values if v is not None]
    n_units = len(values)
    n_missing = n_units - len(present)
    counts = Counter(present)
    top = [ValueCount(value=v, n=c) for v, c in sorted(counts.items(), key=lambda t: (-t[1], t[0]))]
    nums = [x for x in (as_number(v) for v in present) if x is not None]
    out = Profile(
        n_units=n_units,
        n_missing=n_missing,
        missing_pct=round(100.0 * n_missing / n_units, 2) if n_units else 0.0,
        distinct=len(counts),
        top=top[:TOP_N],
        examples=[t.value for t in top[:5]],
        numeric_pct=round(100.0 * len(nums) / len(present), 2) if present else 0.0,
    )
    if nums:
        out.min, out.max, out.median = min(nums), max(nums), float(statistics.median(nums))
    return out
