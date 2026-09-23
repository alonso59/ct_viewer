"""External case-keyed tables, CSV or TSV (VAR-07)."""

from __future__ import annotations

import csv
import io
from typing import Literal

from app.core.errors import ValidationProblem
from app.variables.profile import as_text

KeyName = Literal["case_id", "patient_id"]
KEYS: tuple[KeyName, ...] = ("case_id", "patient_id")
MAX_BYTES = 20 * 1024 * 1024


def _bad(msg: str, loc: str = "file") -> ValidationProblem:
    return ValidationProblem(msg, errors=[{"loc": ["body", loc], "msg": msg}])


def parse_table(
    data: bytes, filename: str, key: KeyName | None = None
) -> tuple[KeyName, list[str], dict[str, dict[str, str | None]], list[str], int]:
    """→ (key, value columns, rows by key, duplicate keys, n_rows). The first duplicate wins."""
    if len(data) > MAX_BYTES:
        raise _bad(f"table larger than {MAX_BYTES // (1024 * 1024)} MiB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _bad("table is not valid UTF-8") from None
    first = text.split("\n", 1)[0]
    delim = "\t" if filename.lower().endswith(".tsv") or "\t" in first else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        raise _bad("table is empty") from None
    if len(set(header)) != len(header) or any(not h for h in header):
        raise _bad("header has empty or duplicate column names")
    if key is None:
        key = next((k for k in KEYS if k in header), None)
        if key is None:
            raise _bad("no case_id or patient_id column", "key")
    elif key not in header:
        raise _bad(f"column {key!r} not in header", "key")
    k_idx = header.index(key)
    columns = [h for h in header if h not in KEYS]
    rows: dict[str, dict[str, str | None]] = {}
    dups: list[str] = []
    n_rows = 0
    for rec in reader:
        if not any(c.strip() for c in rec):
            continue
        n_rows += 1
        rec = rec + [""] * (len(header) - len(rec))
        k = rec[k_idx].strip()
        if not k:
            continue
        if k in rows:
            dups.append(k)
            continue
        rows[k] = {h: as_text(rec[i]) for i, h in enumerate(header) if h in columns}
    return key, columns, rows, dups, n_rows
