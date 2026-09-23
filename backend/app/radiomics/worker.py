"""Radiomics work units (RAD-06/07, BE-06/12). Runs in job worker processes.

Workers receive absolute paths resolved in the API process (BE-02); the engine opens them
read-only (BE-03, R1). The only files a worker writes are its own part under
`radiomics/runs/{run_id}/parts/` (temp file + rename). Diagnostics travel in the part's
parquet schema metadata, so one atomic file marks the unit done (RAD-08).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.radiomics import ibsi
from app.radiomics.engine import get_engine

PARTS = "parts"
DIAG_META = b"radiomics.diagnostics"
ITEM_COLS = ("case_id", "scan_idx", "scope", "side", "phase")
FEATURE_SCHEMA = pa.schema(
    [
        ("run_id", pa.string()),
        ("item_id", pa.string()),
        ("case_id", pa.string()),
        ("scan_idx", pa.string()),
        ("scope", pa.string()),
        ("side", pa.string()),
        ("phase", pa.string()),
        ("label", pa.int64()),
        ("image_type", pa.string()),
        ("feature_class", pa.string()),
        ("feature", pa.string()),
        ("value", pa.float64()),
        ("ibsi_code", pa.string()),
        ("ibsi_status", pa.string()),
    ]
)


def unit_key(item_id: str, label: int) -> str:
    return f"{item_id}__{int(label)}"


def part_path(run_dir: Path, key: str) -> Path:
    return run_dir / PARTS / f"{key}.parquet"


def _write_part(run_dir: Path, key: str, table: pa.Table) -> None:
    dst = part_path(run_dir, key)
    if dst.parent != run_dir / PARTS:
        raise ValueError("part output must live under the run's parts/ folder")
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=dst.parent)
    os.close(fd)
    try:
        pq.write_table(table, tmp)
        os.replace(tmp, dst)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _extract(task: dict[str, Any]) -> tuple[pa.Table, dict[str, Any]]:
    engine = get_engine(task["engine"])
    res = engine.extract(task["image_path"], task["mask_path"], task["label"], task["settings"])
    item = task["item"]
    rows: dict[str, list[Any]] = {n: [] for n in FEATURE_SCHEMA.names}
    for f in res.features:
        code, status = ibsi.export_info(f.image_type, f.feature_class, f.feature)
        rows["run_id"].append(task["run_id"])
        rows["item_id"].append(item["item_id"])
        for c in ITEM_COLS:
            rows[c].append(item[c])
        rows["label"].append(int(task["label"]))
        rows["image_type"].append(f.image_type)
        rows["feature_class"].append(f.feature_class)
        rows["feature"].append(f.feature)
        rows["value"].append(f.value)
        rows["ibsi_code"].append(code)
        rows["ibsi_status"].append(status)
    table = pa.Table.from_pydict(rows, schema=FEATURE_SCHEMA)
    return table, res.diagnostics


def extract_unit(task: dict[str, Any]) -> dict[str, Any]:
    """Work unit: one (item, label). Never raises for per-item failures (RAD-07)."""
    t0 = time.perf_counter()
    base = {"key": task["key"], "item_id": task["item"]["item_id"], "label": task["label"]}
    try:
        table, diag = _extract(task)
        meta = {DIAG_META: json.dumps(diag, sort_keys=True).encode("utf-8")}
        table = table.replace_schema_metadata(meta)
        _write_part(Path(task["run_dir"]), task["key"], table)
    except Exception as exc:
        return {**base, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": time.perf_counter() - t0}  # fmt: skip
    return {**base, "ok": True, "n_features": table.num_rows,
            "elapsed_s": time.perf_counter() - t0}  # fmt: skip


def estimate_sample(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """RAD-11: time extractions of a small sample; writes nothing."""
    out = []
    for task in tasks:
        t0 = time.perf_counter()
        error = None
        try:
            _extract(task)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        out.append(
            {
                "item_id": task["item"]["item_id"],
                "label": task["label"],
                "elapsed_s": time.perf_counter() - t0,
                "error": error,
            }
        )
    return out


def read_diagnostics(path: Path) -> dict[str, Any]:
    meta = pq.read_schema(path).metadata or {}
    raw = meta.get(DIAG_META)
    data: dict[str, Any] = json.loads(raw.decode("utf-8")) if raw else {}
    return data
