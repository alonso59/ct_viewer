"""Dataset table (ADR-0020 §4, API-59): the indexed rows joined with the active layers.

`metadata.jsonl` is never regenerated with plugin columns; this table is the merged view, built
on demand. Layer columns are named `{field}@{layer id}`; Parquet also carries the provenance of
every layer column in the schema metadata (`layers`).
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.ingest.models import Item
from app.layers.model import Layer

BASE = ("item_id", "case_id", "patient_id", "scan_idx", "scope", "side", "modality",
        "phase", "phase_raw", "phase_source", "status", "image")  # fmt: skip


def _cell(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return json.dumps(v, ensure_ascii=False, default=str)


def rows(items: Sequence[Item], layers: Sequence[Layer]) -> tuple[list[str], list[dict[str, Any]]]:
    layer_fields = {layer.field for layer in layers}
    # an input field named like a base column (e.g. the raw `phase`) must not overwrite it
    skip = layer_fields | set(BASE)
    extra_keys = sorted({k for i in items for k in i.extra if k not in skip})
    header = [*BASE, *extra_keys, *(layer.column for layer in layers)]
    out: list[dict[str, Any]] = []
    for i in items:
        r: dict[str, Any] = {
            "item_id": i.item_id, "case_id": i.case_id, "patient_id": i.patient_id,
            "scan_idx": i.scan_idx, "scope": i.scope, "side": i.side, "modality": i.modality,
            "phase": i.phase.canonical, "phase_raw": i.phase.raw, "phase_source": i.phase.source,
            "status": i.status, "image": i.image.ref if i.image else None,
        }  # fmt: skip
        for k in extra_keys:
            r[k] = _cell(i.extra.get(k))
        for layer in layers:
            key = {"case": i.case_id, "scan": f"{i.case_id}.{i.scan_idx}"}.get(
                layer.level, i.item_id
            )
            r[layer.column] = _cell(layer.values.get(key))
        out.append(r)
    return header, out


def to_csv(header: list[str], data: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(data)
    return buf.getvalue().encode("utf-8")


def to_parquet(header: list[str], data: list[dict[str, Any]], layers: Sequence[Layer]) -> bytes:
    cols = {h: [None if r.get(h) is None else str(r[h]) for r in data] for h in header}
    table = pa.table({h: pa.array(v, type=pa.string()) for h, v in cols.items()})
    meta = {b"layers": json.dumps([layer.describe() for layer in layers]).encode()}
    table = table.replace_schema_metadata(meta)
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()
