"""TST-11: synthetic fixtures are deterministic and cover every IMP-08 code."""

import json
from pathlib import Path

import nibabel as nib

from app.ingest.codes import QcCode
from tools.make_fixtures import DATASET, generate, tree_digest


def test_every_qc_code_has_a_fixture(tmp_path: Path) -> None:
    generate(tmp_path / "fx")
    expected = json.loads((tmp_path / "fx/expected.json").read_text())
    covered = {d["code"] for d in expected["defects"]}
    assert covered == {c.value for c in QcCode}


def test_fixtures_are_deterministic(tmp_path: Path) -> None:
    generate(tmp_path / "a")
    generate(tmp_path / "b")
    assert tree_digest(tmp_path / "a") == tree_digest(tmp_path / "b")


def test_healthy_scan_is_valid_nifti_with_matching_seg(tmp_path: Path) -> None:
    generate(tmp_path / "fx")
    root = tmp_path / "fx" / DATASET
    img = nib.load(root / "nifti/01_case_00001_0000.nii.gz")
    seg = nib.load(root / "seg/01_case_00001.nii.gz")
    assert img.shape == seg.shape
    assert set(seg.get_fdata().astype(int).ravel().tolist()) == {0, 1, 2, 3}
