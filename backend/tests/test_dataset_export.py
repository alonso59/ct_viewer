"""ADR-0025 `dataset.jsonl` (API-59 `format=jsonl`) and VAR-09 in every dataset-table format:
one line per item with the effective phase, layer columns and refs; sensitive fields only on
request."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import pyarrow.parquet as pq
from fastapi.testclient import TestClient

from tests.test_api_ingest import API
from tests.test_curation_api import HDR, proj  # noqa: F401
from tests.test_phase import Proj, other, scan_of, select


def export(c: TestClient, pid: str, **params: Any) -> Any:
    r = c.get(f"{API}/projects/{pid}/exports/dataset-table", params=params)
    assert r.status_code == 200, r.text
    return r


def test_jsonl_one_line_per_item_with_layers_and_effective_phase(
    client: TestClient,
    proj: Proj,  # noqa: F811
) -> None:
    pid, items = proj
    case_id, scan_idx, before = scan_of(items)
    new = other(before)
    assert select(client, pid, {"case_id": case_id, "scan_idx": scan_idx, "value": new}).is_success
    item = next(i for i in items if i["case_id"] == case_id and i["scan_idx"] == scan_idx)
    ev = {"item_id": item["item_id"], "target": "seg", "status": "accepted"}
    assert client.post(f"{API}/projects/{pid}/curation/events", json=ev, headers=HDR).is_success

    r = export(client, pid, format="jsonl")
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert 'filename="dataset.jsonl"' in r.headers["content-disposition"]
    lines = [json.loads(x) for x in r.text.splitlines()]
    assert len(lines) == len(items)
    assert {x["item_id"] for x in lines} == {i["item_id"] for i in items}
    row = next(x for x in lines if x["item_id"] == item["item_id"])
    # PHS-03 / ADR-0026: the effective phase, its source and the value it replaced
    assert (row["phase"], row["phase_source"], row["phase_resolved"]) == (new, "manual", before)
    assert row["curation_status@curation"] == "accepted"
    assert isinstance(row["masks"], dict) and isinstance(row["labels_present"], list)
    assert isinstance(row["refs"], dict)
    untouched = next(x for x in lines if x["case_id"] != case_id)
    assert "phase_resolved" not in untouched


def test_sensitive_fields_only_on_request_in_every_format(
    client: TestClient,
    proj: Proj,  # noqa: F811
) -> None:
    pid, items = proj
    assert any(i.get("patient_id") for i in items)
    for fmt in ("csv", "jsonl"):
        default = export(client, pid, format=fmt)
        full = export(client, pid, format=fmt, include_sensitive="true")
        if fmt == "csv":
            assert "patient_id" not in next(csv.reader(io.StringIO(default.text)))
            assert "patient_id" in next(csv.reader(io.StringIO(full.text)))
        else:
            assert all("patient_id" not in json.loads(x) for x in default.text.splitlines())
            assert any(json.loads(x).get("patient_id") for x in full.text.splitlines())


def test_uids_paths_and_raw_tags_never_leak(
    client: TestClient,
    proj: Proj,  # noqa: F811
) -> None:
    """AUD-A2-01, VAR-09 / NFR-17: UIDs and accession numbers only on request; absolute paths
    and the `raw_metadata` tag blob never, in any format."""
    pid, _ = proj
    uids = {"study_uid", "series_uid", "accession_number"}
    never = {"first_file", "raw_metadata"}

    def keys(fmt: str, **params: Any) -> set[str]:
        r = export(client, pid, format=fmt, **params)
        if fmt == "csv":
            return set(next(csv.reader(io.StringIO(r.text))))
        if fmt == "parquet":
            return set(pq.read_schema(io.BytesIO(r.content)).names)
        return {k for x in r.text.splitlines() for k in json.loads(x)}

    for fmt in ("csv", "parquet", "jsonl"):
        assert not keys(fmt) & (uids | never), fmt
        full = keys(fmt, include_sensitive="true")
        assert uids <= full and not full & never, fmt
