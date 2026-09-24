"""VW-22 backend half: the DICOM header window in Open mode and in converter rows, and header
info (DICOM tags) for an Open-mode DICOM item."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.test_contract import assert_problem
from tests.test_dicom import convert, dc, project, src  # noqa: F401  (fixtures)
from tools.dicom_fixtures import write_series

API = "/api/v1"


def test_open_dicom_window_and_tags(
    dc: TestClient,  # noqa: F811
    src: tuple[Path, dict[str, Any]],  # noqa: F811
) -> None:
    root = src[0]
    window = {"WindowCenter": "40\\60", "WindowWidth": "400\\500"}
    write_series(root / "P003" / "win", patient_id="P003", extra=window)
    s = dc.post(f"{API}/open", json={"path": str(root / "P003" / "win")}).json()
    item = s["items"][0]
    assert item["format"] == "dicom" and item["window"] == [400.0, 40.0]
    tags = dc.get(f"{API}/open/{s['sid']}/items/0/dicom-tags").json()
    assert tags["00280010"]["vr"] == "US" and "7FE00010" not in tags  # rows, no PixelData
    assert tags["00281050"]["Value"][0] == 40
    nifti = dc.post(f"{API}/open", json={"path": str(root / "P001" / "ct")}).json()
    assert nifti["items"][0]["window"] is None  # the fixture series carries no window


def test_converter_rows_carry_the_header_window(
    dc: TestClient,  # noqa: F811
    src: tuple[Path, dict[str, Any]],  # noqa: F811
    tmp_path: Path,
) -> None:
    root = src[0]
    window = {"WindowCenter": "40", "WindowWidth": "400"}
    write_series(root / "P003" / "win", patient_id="P003", extra=window)
    pid = project(dc, tmp_path)
    run = convert(dc, pid, root)
    path = tmp_path / "derived" / pid / "dicom.convert" / "runs" / run["run_id"] / "metadata.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    p3 = next(r for r in rows if r["patient_id"] == "P003")
    assert (p3["window_center"], p3["window_width"]) == ("40", "400")


def test_open_tags_refused_for_nifti(dc: TestClient, tmp_path: Path) -> None:  # noqa: F811
    assert_problem(dc.get(f"{API}/open/01JAAAAAAAAAAAAAAAAAAAAAAA/items/0/dicom-tags"), "not-found")
