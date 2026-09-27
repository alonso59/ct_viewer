"""Shared selection + preflight (TSK-03/04, RAD-05): `app.tasks.readiness`."""

from __future__ import annotations

import asyncio
from typing import Any

from app.ingest.codes import QcCode
from app.ingest.models import Item, PhaseInfo, VolumeRef
from app.radiomics.service import _not_ready as rad_not_ready
from app.selection import readiness
from app.selection.readiness import NotReady, not_ready
from app.tasks.models import TaskSelection, TaskSelectionFilter

V = VolumeRef(ref="SRC:x.nii.gz")


def item(iid: str = "a", **kw: Any) -> Item:
    base: dict[str, Any] = {
        "item_id": iid,
        "case_id": iid,
        "scan_idx": "01",
        "scope": "complete",
        "side": "-",
        "phase": PhaseInfo(canonical="NP"),
        "import_id": "I",
        "image": V,
        "masks": {"imported": V},
    }
    return Item(**{**base, **kw})


def test_ready() -> None:
    assert not_ready(item(), seg_id="imported") is None
    assert not_ready(item(image=None), need_image=False) is None


def test_no_image() -> None:
    assert not_ready(item(image=None)) == NotReady("no_image")


def test_modality() -> None:
    assert not_ready(item(modality="MR"), modalities=["CT"]) == NotReady(
        "modality", {"modality": "MR"}
    )
    assert not_ready(item(modality=None), modalities=["CT"]) is None


def test_no_mask() -> None:
    r = not_ready(item(masks={}), seg_id="nn")
    assert r == NotReady("no_mask", {"seg_id": "nn"})
    assert rad_not_ready(item(masks={}), "imported") == "missing_seg"  # RAD-05 codes kept
    assert rad_not_ready(item(masks={}), "nn") == "no_mask"


def test_label_missing_imported_only() -> None:
    it = item(labels_present=[1], masks={"imported": V, "nn": V})
    lm = {"kidney": 1, "tumor": 2}
    r = not_ready(it, seg_id="imported", labels=["tumor"], label_map=lm)
    assert r == NotReady("label_missing", {"seg_id": "imported", "label": "tumor"})
    assert not_ready(it, seg_id="imported", labels=["kidney"], label_map=lm) is None
    assert not_ready(it, seg_id="nn", labels=["tumor"], label_map=lm) is None


def test_blocked_imported_only() -> None:
    it = item(warning_codes=[QcCode.AFFINE_MISMATCH], masks={"imported": V, "nn": V})
    r = not_ready(it, seg_id="imported")
    assert r == NotReady("blocked", {"seg_id": "imported", "qc": "affine_mismatch"})
    assert rad_not_ready(it, "imported") == "affine_mismatch"
    assert not_ready(it, seg_id="nn") is None
    assert not_ready(it) is None  # no mask read, no QC block


def test_resolve() -> None:
    a, b, c = item("a"), item("b", status="missing"), item("c", side="L", scope="voi")
    items = [c, b, a]
    by_id = {i.item_id: i for i in items}
    got, probs = asyncio.run(readiness.resolve(items, by_id, TaskSelection()))
    assert [i.item_id for i in got] == ["a", "c"] and probs == []
    sel = TaskSelection(item_ids=["a", "b", "z"])
    got, probs = asyncio.run(readiness.resolve(items, by_id, sel))
    assert [i.item_id for i in got] == ["a"]
    assert [(p.loc, p.rule) for p in probs] == [
        (["item_ids", 1], "inactive"),
        (["item_ids", 2], "unknown"),
    ]
    sel = TaskSelection(filter=TaskSelectionFilter(side=["L"]))
    got, _ = asyncio.run(readiness.resolve(items, by_id, sel))
    assert [i.item_id for i in got] == ["c"]
    got, _ = asyncio.run(readiness.resolve(items, by_id, TaskSelection(scope="complete")))
    assert [i.item_id for i in got] == ["a"]

    async def var_ids(var: dict[str, list[str]]) -> list[str]:
        return ["c"]

    sel = TaskSelection(filter=TaskSelectionFilter(var={"x": ["1"]}))
    got, _ = asyncio.run(readiness.resolve(items, by_id, sel, var_ids))
    assert [i.item_id for i in got] == ["c"]
    sel = TaskSelection(item_ids=["a"], filter=TaskSelectionFilter())
    _, probs = asyncio.run(readiness.resolve(items, by_id, sel))
    assert probs[0].rule == "conflict"
