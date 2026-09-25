"""IMP-15 / ADR-0025 §2: opt-in reconstructed DICOM sidecars for `metadata-v1` imports, written
to the derived root only, marked partial, never over a real one."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ingest.sidecars import json_model
from app.main import create_app
from tests.test_api_ingest import wait
from tests.test_contract import assert_problem
from tests.test_format_v2 import derived_settings
from tools.make_fixtures import DATASET

API = "/api/v1"


@pytest.fixture
def env(tmp_path: Path, fixtures_copy: Path) -> Iterator[TestClient]:
    (tmp_path / "derived").mkdir()
    s = derived_settings(tmp_path, fixtures_copy / DATASET, tmp_path / "derived")
    with TestClient(create_app(s, inline_jobs=True)) as c:
        yield c


def project(c: TestClient) -> str:
    return str(
        c.post(f"{API}/projects", json={"name": "s", "packs": ["ccrcc"]}).json()["project_id"]
    )


def import_with(c: TestClient, pid: str, root: Path, **options: Any) -> None:
    r = c.post(
        f"{API}/projects/{pid}/imports/preview", json={"root": str(root), "options": options}
    )
    assert r.status_code == 200, r.text
    r = c.post(f"{API}/projects/{pid}/imports", json={"preview_id": r.json()["preview_id"]})
    assert r.status_code == 202, r.text
    assert wait(c, r.json()["job_id"]).status == "succeeded"


def items(c: TestClient, pid: str) -> list[dict[str, Any]]:
    """Every item as a `dataset.jsonl` line (ADR-0025): `refs.dicom_sidecar` is the item's ref."""
    r = c.get(f"{API}/projects/{pid}/exports/dataset-table", params={"format": "jsonl"})
    return [json.loads(x) for x in r.text.splitlines()]


def test_json_model_maps_row_fields_and_marks_partial() -> None:
    row = {"kvp": "140", "acquisition_date": "20210209", "study_uid": "1.2.3",
           "patient_id": "P001", "scan_date": "2021-02-09"}  # fmt: skip
    m = json_model(row, "2026-09-25T00:00:00Z")
    assert m is not None
    assert m["00180060"] == {"vr": "DS", "Value": [140]}
    assert m["00080022"] == {"vr": "DA", "Value": ["20210209"]}
    assert m["0020000D"] == {"vr": "UI", "Value": ["1.2.3"]}
    assert m["_provenance"] == {"source": "metadata-v1-import", "fidelity": "partial",
                                "generated_at": "2026-09-25T00:00:00Z"}  # fmt: skip
    assert "00100020" not in m  # patient fields are never reconstructed
    assert json_model({"patient_id": "P001"}, "t") is None


def test_opt_in_writes_partial_sidecars_to_the_derived_root(
    env: TestClient, data_root: Path, tmp_path: Path
) -> None:
    pid = project(env)
    # DCM-05: only into a derived root, so the option needs one
    body = {"root": str(data_root), "options": {"reconstruct_sidecars": True}}
    r = env.post(f"{API}/projects/{pid}/imports/preview", json=body)
    assert_problem(r, "derived-root-required")
    derived = tmp_path / "derived"
    put = env.put(
        f"{API}/projects/{pid}/roots/DERIVED", json={"path": str(derived), "role": "derived"}
    )
    assert put.status_code == 200, put.text
    import_with(env, pid, data_root, reconstruct_sidecars=True)

    got = items(env, pid)
    with_ref = [i for i in got if i["refs"].get("dicom_sidecar")]
    assert with_ref and all(i["refs"]["dicom_sidecar"].startswith("DERIVED:") for i in with_ref)
    it = next(i for i in with_ref if i["scope"] == "complete")
    tags = env.get(f"{API}/projects/{pid}/items/{it['item_id']}/dicom-tags").json()
    assert tags["_provenance"]["fidelity"] == "partial" and "00180060" in tags
    assert list(derived.rglob("*.dicom.json"))
    assert not list(data_root.rglob("*.dicom.json"))  # R1: nothing next to the sources


def test_off_by_default(env: TestClient, data_root: Path) -> None:
    pid = project(env)
    import_with(env, pid, data_root)
    assert not any(i["refs"].get("dicom_sidecar") for i in items(env, pid))
