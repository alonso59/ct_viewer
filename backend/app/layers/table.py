"""Dataset table (ADR-0020 §4, API-59): the indexed rows joined with the active layers.

`metadata.jsonl` is never regenerated with plugin columns; this table is the merged view, built
on demand. Layer columns are named `{field}@{layer id}`; Parquet also carries the provenance of
every layer column in the schema metadata (`layers`). `dataset.jsonl` (ADR-0025) is the same
merge as one JSON object per item: values keep their JSON shape, and per-file records (a DICOM
sidecar, an analyzer run's annotations) are references under `refs`, never inlined. Sensitive
fields (VAR-09) are left out of every format unless asked for.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from typing import Any, Final

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


def rows(
    items: Sequence[Item], layers: Sequence[Layer], drop: frozenset[str] = frozenset()
) -> tuple[list[str], list[dict[str, Any]]]:
    """`drop`: field names left out (the sensitive ones, VAR-09), base, extra or layer."""
    layers = [layer for layer in layers if layer.field not in drop]
    layer_fields = {layer.field for layer in layers}
    # an input field named like a base column (e.g. the raw `phase`) must not overwrite it
    skip = layer_fields | set(BASE) | drop
    extra_keys = sorted({k for i in items for k in i.extra if k not in skip})
    header = [*(b for b in BASE if b not in drop), *extra_keys, *(layer.column for layer in layers)]
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


REF_FIELDS: Final = ("dicom_sidecar",)  # per-file records, kept as references (ADR-0025)


def to_jsonl(
    items: Sequence[Item],
    layers: Sequence[Layer],
    annotation_refs: dict[str, str],
    drop: frozenset[str] = frozenset(),
) -> bytes:
    """ADR-0025 `dataset.jsonl`: one line per item, flat like the table, JSON values kept.

    `annotation_refs`: active annotation field → `tasks/runs/{run_id}/annotations.jsonl`.
    """
    layers = [layer for layer in layers if layer.field not in drop]
    skip = {layer.field for layer in layers} | set(BASE) | set(REF_FIELDS) | drop
    lines: list[str] = []
    for i in items:
        rec: dict[str, Any] = {
            "item_id": i.item_id, "case_id": i.case_id, "patient_id": i.patient_id,
            "scan_idx": i.scan_idx, "scope": i.scope, "side": i.side, "modality": i.modality,
            "phase": i.phase.canonical, "phase_raw": i.phase.raw, "phase_source": i.phase.source,
            "status": i.status, "image": i.image.ref if i.image else None,
        }  # fmt: skip
        for k in drop:
            rec.pop(k, None)
        if i.phase.resolved is not None:  # PHS-03: a selection keeps the value it replaced
            rec["phase_resolved"] = i.phase.resolved.canonical
        rec["masks"] = {seg: v.ref for seg, v in i.masks.items()}
        rec["labels_present"] = i.labels_present
        rec["warning_codes"] = list(i.warning_codes)
        rec["geometry"] = i.geometry.model_dump(mode="json") if i.geometry else None
        for k in sorted(i.extra):
            if k not in skip:
                rec[k] = i.extra[k]
        for layer in layers:
            key = {"case": i.case_id, "scan": f"{i.case_id}.{i.scan_idx}"}.get(
                layer.level, i.item_id
            )
            rec[layer.column] = layer.values.get(key)
        refs = {k: i.extra[k] for k in REF_FIELDS if i.extra.get(k) and k not in drop}
        refs.update({f"annotations:{f}": ref for f, ref in sorted(annotation_refs.items())})
        rec["refs"] = refs
        lines.append(json.dumps(rec, ensure_ascii=False, default=str))
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


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
