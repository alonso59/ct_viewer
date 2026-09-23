"""TST-01: normalizer, indexer units, validator, case summaries over the synthetic fixtures.

No workspace/job manager: `PathResolver` + `PathGuard` are built directly over `data_root`,
and `indexer.probe_batch` is called in-process (IMP-05..08/10/11).
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest

from app.core.paths import PathGuard, PathResolver
from app.ingest import indexer
from app.ingest.cases import build_cases
from app.ingest.models import Item, QcWarning
from app.ingest.normalize import Draft, build_drafts
from app.ingest.parsers import ParsedInputs, parse_inputs
from app.ingest.validator import finalize, probes_for

IMPORT = "01JIMPORT0000000000000000A"


def load_inputs(root: Path) -> ParsedInputs:
    return parse_inputs(
        {
            "metadata": (root / "metadata.jsonl").read_bytes(),
            "phase": (root / "phase.json").read_bytes(),
            "voi_catalog": (root / "voi/voi_catalog.jsonl").read_bytes(),
        }
    )


def resolver_for(root: Path) -> PathResolver:
    return PathResolver({"DATA": root}, PathGuard([root]))


def run_index(
    drafts: list[Draft], previous: dict[str, Item] | None = None
) -> tuple[list[Item], list[QcWarning]]:
    results = {}
    for batch in indexer.batches(probes_for(drafts)):
        for r in indexer.probe_batch(batch):
            results[r.item_id] = r
    return finalize(drafts, results, previous or {}, IMPORT)


@pytest.fixture
def indexed(data_root: Path) -> tuple[dict[str, Item], list[QcWarning]]:
    drafts = build_drafts(load_inputs(data_root), resolver_for(data_root), "DATA")
    items, warnings = run_index(drafts)
    return {i.item_id: i for i in items}, warnings


def codes_of(warnings: list[QcWarning], case_id: str) -> set[str]:
    return {w.code for w in warnings if w.case_id == case_id}


def test_expected_defects_present(
    fixtures_copy: Path, indexed: tuple[dict[str, Item], list[QcWarning]]
) -> None:
    items, warnings = indexed
    expected = json.loads((fixtures_copy / "expected.json").read_text())
    for d in expected["defects"]:
        if d["code"] == "fingerprint_changed":
            continue
        assert d["code"] in codes_of(warnings, d["case_id"]), d
    for w in warnings:
        assert w.item_id in items and w.detected_at.endswith("Z")
        assert w.code in items[w.item_id].warning_codes
    for case_id in ("case_00001", "case_00002", "case_00003"):
        assert codes_of(warnings, case_id) == set()


def test_healthy_items(indexed: tuple[dict[str, Item], list[QcWarning]]) -> None:
    items, _ = indexed
    it = items["case_00001.01.complete.-"]
    assert it.status == "active" and it.phase.canonical == "NC" and it.phase.source == "phase"
    assert it.image is not None and it.image.ref == "DATA:nifti/01_case_00001_0000.nii.gz"
    assert it.mask is not None and it.mask.ref == "DATA:seg/01_case_00001.nii.gz"
    assert it.image.fp and it.mask.fp
    assert it.geometry is not None and it.geometry.shape == [64, 64, 48]
    assert it.geometry.orientation == "RAS"
    assert it.labels_present == [1, 2, 3]
    assert it.extra["series_uid"] and "relative_path" not in it.extra
    assert items["case_00001.02.complete.-"].phase.canonical == "CMP"
    assert items["case_00001.03.complete.-"].phase.raw == "VEN"
    override = items["case_00003.02.complete.-"].phase
    assert (override.canonical, override.source) == ("EP", "phase.json")
    voi = items["case_00001.03.voi.L"]
    assert voi.scope == "voi" and voi.phase == items["case_00001.03.complete.-"].phase
    assert voi.patient_id == "P001" and "group" not in voi.extra and voi.geometry is not None
    assert voi.geometry.shape == [32, 32, 32] and voi.labels_present


def test_defect_items(indexed: tuple[dict[str, Item], list[QcWarning]]) -> None:
    items, warnings = indexed
    assert items["case_00010.01.complete.-"].status == "missing"
    outside = items["case_00012.01.complete.-"]
    assert outside.status == "missing" and outside.image is None
    assert items["case_00013.01.complete.-"].mask is None
    assert items["case_00014.01.voi.L"].status == "missing"
    assert items["case_00014.01.voi.R"].mask is None
    assert items["case_00015.01.complete.-"].geometry is not None
    assert items["case_00019.01.voi.-"].side == "-"
    dup = items["case_00020.01.complete.-"]
    assert dup.phase.canonical == "NP"  # first row kept
    assert [w.code for w in warnings if w.item_id == dup.item_id] == ["duplicate_row_identity"]
    assert items["case_00011.01.complete.-"].image is not None  # exists but unreadable
    unreadable = [w for w in warnings if w.code == "unreadable_file"]
    assert unreadable and unreadable[0].field == "image" and unreadable[0].path_ref


def test_excluded_upstream_and_npy(indexed: tuple[dict[str, Item], list[QcWarning]]) -> None:
    items, warnings = indexed
    ex = items["case_00022.01.complete.-"]
    assert ex.status == "excluded_upstream" and ex.image is None
    assert codes_of(warnings, "case_00022") == set()
    npy = items["case_00023.01.voi.L"]
    assert npy.image is not None and npy.image.format == "npy" and npy.image.fp
    assert npy.geometry is not None and npy.geometry.spacing == [0.8, 0.8, 1.5]
    assert npy.labels_present == [1, 2, 3]
    assert "missing_affine" not in npy.warning_codes


def test_cases_summary(indexed: tuple[dict[str, Item], list[QcWarning]]) -> None:
    items, warnings = indexed
    cases = {c.case_id: c for c in build_cases(list(items.values()), warnings)}
    c1 = cases["case_00001"]
    assert c1.phases == ["NC", "CMP", "NP"] and c1.n_scans == 3 and c1.n_items == 5
    assert c1.has_seg and c1.has_voi_L and c1.has_voi_R and c1.n_warnings == 0
    assert c1.patient_id == "P001" and c1.curation_status == "not_reviewed"
    assert cases["case_00022"].n_items == 0
    assert cases["case_00013"].has_seg is False
    assert cases["case_00010"].n_warnings >= 1


def test_probe_batch_is_picklable(data_root: Path) -> None:
    drafts = build_drafts(load_inputs(data_root), resolver_for(data_root), "DATA")
    batch = indexer.batches(probes_for(drafts))[0]
    assert len(batch) == indexer.BATCH_SIZE
    out = pickle.loads(pickle.dumps(indexer.probe_batch(pickle.loads(pickle.dumps(batch)))))
    assert [r.item_id for r in out] == [p.item_id for p in batch]


def _write(path: Path, data: Any, affine: Any = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, np.eye(4) if affine is None else affine), path)


def _rows(*rows: dict[str, Any]) -> bytes:
    return "".join(json.dumps(r) + "\n" for r in rows).encode()


def test_path_rules_and_ambiguity(tmp_path: Path) -> None:
    root = tmp_path / "root"
    vol = np.zeros((8, 8, 8), dtype=np.int16)
    _write(root / "nifti/01_case_00001_0000.nii.gz", vol)
    _write(root / "legacy/02_case_00001_0000.nii.gz", vol)
    _write(root / "voi/a.nii.gz", vol)
    meta = _rows(
        {"case_id": "case_00001", "scan_idx": "01", "filename": "01_case_00001_0000.nii.gz",
         "curated_phase": "ART", "phase": "VEN", "seg_path": "seg/missing.nii.gz"},
        {"case_id": "case_00001", "scan_idx": "02",
         "nifti_file": str(root / "legacy/02_case_00001_0000.nii.gz"), "phase": "NP"},
        {"case_id": "case_00001", "scan_idx": "03", "nifti_file": "/elsewhere/x.nii.gz"},
    )  # fmt: skip
    cat = _rows(
        {"case_id": "case_00001", "scan_idx": "01", "side": "left", "image_path": "voi/a.nii.gz"},
        {"case_id": "case_00001", "scan_idx": "01", "side": "_R", "image_path": "voi/a.nii.gz",
         "mask_path": "voi/none.nii.gz"},
        {"case_id": "case_00002", "scan_idx": "01", "side": "L", "image_path": "voi/a.nii.gz",
         "phase": "delayed"},
    )  # fmt: skip
    parsed = parse_inputs({"metadata": meta, "voi_catalog": cat})
    items_l, warnings = run_index(build_drafts(parsed, resolver_for(root), "DATA"))
    items = {i.item_id: i for i in items_l}
    by = {(w.item_id, w.code, w.field) for w in warnings}
    s1 = "case_00001.01.complete.-"
    img1 = items[s1].image
    assert img1 is not None and img1.ref == "DATA:nifti/01_case_00001_0000.nii.gz"
    assert (s1, "ambiguous_phase", "phase") in by
    assert (s1, "missing_path", "mask") in by and (s1, "missing_seg", "mask") in by
    s2 = items["case_00001.02.complete.-"]
    assert s2.image and s2.image.ref == "DATA:legacy/02_case_00001_0000.nii.gz"  # relativized
    assert ("case_00001.03.complete.-", "outside_root", "image") in by
    for side in ("L", "R"):
        assert (f"case_00001.01.voi.{side}", "ambiguous_side", "side") in by
    assert ("case_00001.01.voi.L", "missing_voi_mask", "mask") in by
    assert ("case_00001.01.voi.R", "missing_voi_mask", "mask") in by
    orphan = items["case_00002.01.voi.L"]
    assert (orphan.phase.canonical, orphan.phase.source) == ("EP", "catalog")


def test_metadata_only_mode(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write(root / "nifti/01_case_00001_0000.nii.gz", np.zeros((4, 4, 4), dtype=np.int16))
    meta = _rows(
        {"case_id": "case_00001", "scan_idx": "01", "filename": "01_case_00001_0000.nii.gz"}
    )
    items, warnings = run_index(
        build_drafts(parse_inputs({"metadata": meta}), resolver_for(root), "DATA")
    )
    assert [i.status for i in items] == ["active"]
    assert {w.code for w in warnings} == {"missing_seg", "ambiguous_phase"}


def test_fingerprint_changed(data_root: Path, fixtures_copy: Path) -> None:
    expected = json.loads((fixtures_copy / "expected.json").read_text())
    defect = next(d for d in expected["defects"] if d["code"] == "fingerprint_changed")
    parsed, res = load_inputs(data_root), resolver_for(data_root)
    first, _ = run_index(build_drafts(parsed, res, "DATA"))
    target = data_root / defect["mutate_after_index"]
    img: Any = nib.load(target)
    _write(target, np.asanyarray(img.dataobj) + 1, img.affine)
    _, warnings = run_index(build_drafts(parsed, res, "DATA"), {i.item_id: i for i in first})
    fp = [w for w in warnings if w.code == "fingerprint_changed"]
    assert [(w.case_id, w.field) for w in fp] == [(defect["case_id"], "image")]


def test_workers_open_sources_read_only(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """BE-03: probing never opens a source path for writing."""
    import builtins

    real_open = builtins.open
    root = str(data_root.resolve())
    bad: list[str] = []

    def guarded(file: Any, mode: str = "r", *a: Any, **k: Any) -> Any:
        under = isinstance(file, (str, Path)) and str(Path(file).resolve()).startswith(root)
        if under and any(c in mode for c in "wax+"):
            bad.append(str(file))
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded)
    run_index(build_drafts(load_inputs(data_root), resolver_for(data_root), "DATA"))
    assert bad == []
