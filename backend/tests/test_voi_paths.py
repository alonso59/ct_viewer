"""IMP-16: normalize legacy VOI catalogs without changing source files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.paths import PathGuard, PathResolver
from app.ingest.parsers import parse_voi_catalog


def parse(root: Path, **fields: Any) -> tuple[Any, Any]:
    data = json.dumps({"case_id": "case_00001", "scan_idx": "01", "side": "L", **fields}).encode()
    return parse_voi_catalog(
        data, resolver=PathResolver({"SRC": root}, PathGuard([root])), alias="SRC"
    )


@pytest.mark.parametrize("prefix", ["", "voi/", "voi\\"])
def test_legacy_paths_root_or_catalog_relative(tmp_path: Path, prefix: str) -> None:
    for part in ("images", "mask"):
        path = tmp_path / "voi" / part / "crop.npy"
        path.parent.mkdir(parents=True)
        path.touch()
    rows, errors = parse(
        tmp_path, voi_image_path=f"{prefix}images/crop.npy", voi_mask_path=f"{prefix}mask/crop.npy"
    )
    assert not errors and len(rows) == 1
    assert rows[0].text("image_path") == "voi/images/crop.npy"
    assert rows[0].text("mask_path") == "voi/mask/crop.npy"


def test_legacy_dataset_relative_and_absolute_paths(tmp_path: Path) -> None:
    path = tmp_path / "custom/crop.npy"
    path.parent.mkdir()
    path.touch()
    for raw in ("custom/crop.npy", str(path)):
        rows, errors = parse(tmp_path, voi_image_path=raw)
        assert not errors
        assert rows[0].text("image_path") == "custom/crop.npy"


def test_canonical_paths_take_precedence_and_empty_fields_fall_back(tmp_path: Path) -> None:
    rows, errors = parse(
        tmp_path,
        image_path="explicit.npy",
        voi_image_path="old.npy",
        mask_path="",
        voi_mask_path="mask.npy",
    )
    assert not errors
    assert rows[0].text("image_path") == "explicit.npy"
    assert rows[0].text("mask_path") == "mask.npy"


def test_ambiguous_paths_are_not_selected(tmp_path: Path) -> None:
    (tmp_path / "voi").mkdir()
    (tmp_path / "crop.npy").touch()
    (tmp_path / "voi/crop.npy").touch()
    rows, errors = parse(tmp_path, voi_image_path="crop.npy")
    assert not rows and len(errors) == 1
    assert errors[0].line == 1 and errors[0].field == "voi_image_path"
    assert "both" in errors[0].message and "image_path/mask_path" in errors[0].message
    rows, errors = parse(tmp_path, image_path="voi/crop.npy", voi_image_path="crop.npy")
    assert len(rows) == 1 and not errors


@pytest.mark.parametrize("raw", ["../crop.npy", "/elsewhere/crop.npy", "../voi/crop.npy"])
def test_unsafe_paths_cannot_be_rescued_by_catalog_prefix(tmp_path: Path, raw: str) -> None:
    rows, errors = parse(tmp_path, voi_image_path=raw)
    assert not rows and len(errors) == 1


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    root.mkdir()
    outside = tmp_path / "outside.npy"
    outside.touch()
    (root / "crop.npy").symlink_to(outside)
    rows, errors = parse(root, voi_image_path="crop.npy")
    assert not rows and len(errors) == 1


def test_no_match_keeps_reference_for_missing_path_qc(tmp_path: Path) -> None:
    rows, errors = parse(tmp_path, voi_image_path="missing.npy")
    assert not errors and rows[0].text("image_path") == "missing.npy"
