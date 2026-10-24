"""D10/D12 / DCM-06/15/16: estimates consume durable header facts without pixel work."""

from __future__ import annotations

from pathlib import Path

import pytest
from plugins.dicom import convert, pipeline, scan
from plugins.dicom.identity import Identity

from app.tasks.source_inventory import SourceInventory
from tools.dicom_fixtures import write_series


def test_dry_run_reuses_inventory_without_header_rescan_or_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source"
    write_series(root / "patient" / "study" / "series", seed="cached-plan")
    db = tmp_path / "workspace" / "inventory.sqlite"
    with SourceInventory(db, root) as inventory:
        summary = inventory.scan()
        assert summary["complete"]

        def forbidden(*args: object, **kwargs: object) -> None:
            pytest.fail("Dry run must use cached facts and must not read image pixels")

        monkeypatch.setattr(scan, "discover", forbidden)
        monkeypatch.setattr(scan, "image_info", forbidden)
        monkeypatch.setattr(convert, "read_image", forbidden)
        monkeypatch.setattr(convert, "write_nifti", forbidden)
        result = pipeline.run(
            root,
            pipeline.Settings(),
            Identity(),
            nifti_dir=tmp_path / "derived" / "nifti",
            sidecar_dir=tmp_path / "derived" / "sidecars",
            ref_rel="dataset",
            ref_alias="DERIVED",
            salt="",
            previous=[],
            dry_run=True,
            cached_discover=inventory.discover,
            cached_file_total=summary["dicom"],
        )
        assert result.counts["series"] == result.counts["selected"] == 1
        assert result.plan[0]["n_files"] == 14 and result.plan[0]["action"] == "convert"
        assert result.storage["nifti_gz_estimated_bytes"] > 0
        # Settings change the plan, not the file/header inventory contract.
        warm = inventory.scan()
        assert warm["generation"] == summary["generation"] and warm["complete"]
        changed = pipeline.run(
            root,
            pipeline.Settings(convert_primary=False, convert_secondary=False),
            Identity(),
            nifti_dir=tmp_path / "derived" / "nifti",
            sidecar_dir=tmp_path / "derived" / "sidecars",
            ref_rel="dataset",
            ref_alias="DERIVED",
            salt="",
            previous=[],
            dry_run=True,
            cached_discover=inventory.discover,
            cached_file_total=warm["dicom"],
        )
        assert changed.counts["selected"] == 0 and changed.counts["skipped"] == 1
        assert changed.plan[0]["action"] == "skip"
        assert not (tmp_path / "derived").exists()
