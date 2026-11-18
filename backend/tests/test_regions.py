"""RAD-15: the `regions.derive` task (tumor core, rim, peritumoral band), read by radiomics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from plugins.protocol import SkipItem
from plugins.regions import morphology as m
from plugins.regions import task

from tests.test_tasks import API, ITEMS, finish, with_derived
from tests.test_tasks import env as env
from tests.test_tasks import plugins_root as plugins_root
from tests.test_tasks import proj as proj

TASK = "regions.derive"
WHO = {"X-Reviewer": "T"}
KIDNEY, TUMOR = 1, 2


def ellipsoid(shape: tuple[int, int, int], spacing: tuple[float, ...], radius_mm: float) -> Any:
    """Kidney box around a tumor ball of `radius_mm`, centred, on a grid of `spacing`."""
    grid = np.indices(shape).astype(float)
    centre = (np.array(shape)[:, None, None, None] - 1) / 2
    dist = np.sqrt((((grid - centre) * np.array(spacing)[:, None, None, None]) ** 2).sum(axis=0))
    labels = np.ones(shape, dtype=np.uint8) * KIDNEY
    labels[dist <= radius_mm] = TUMOR
    return labels


def coords(mask: Any, spacing: tuple[float, ...]) -> Any:
    return np.argwhere(mask) * np.array(spacing)


def min_dist(points: Any, others: Any) -> Any:
    """For each point, the distance in mm to the nearest of `others` (brute force)."""
    return np.min(np.linalg.norm(points[:, None, :] - others[None, :, :], axis=2), axis=1)


def derive(
    labels: Any, spacing: tuple[float, ...], organ: list[int] | None = None, **kw: Any
) -> Any:
    opts = {"core_mm": 3.0, "peri_inner_mm": 2.0, "peri_outer_mm": 5.0, **kw}
    return m.derive(labels, spacing, [TUMOR], [KIDNEY] if organ is None else organ, **opts)


def test_RAD15_distances_are_millimetres_on_an_anisotropic_grid() -> None:
    spacing = (0.7, 0.7, 3.0)
    labels = ellipsoid((40, 40, 12), spacing, 9.0)
    out = derive(labels, spacing)
    tumor, outside = labels == TUMOR, labels != TUMOR
    core, rim = out == m.VALUES["core"], out == m.VALUES["rim"]
    assert core.any() and rim.any()
    far = min_dist(coords(core, spacing), coords(outside, spacing))
    near = min_dist(coords(rim, spacing), coords(outside, spacing))
    assert far.min() > 3.0 and near.max() <= 3.0
    assert not (core & rim).any() and np.array_equal(core | rim, tumor)
    # The same scan stored with its axes in another order gives the same regions
    order = (2, 0, 1)
    permuted = derive(labels.transpose(order), tuple(spacing[i] for i in order))
    assert np.array_equal(permuted, out.transpose(order))


def test_RAD15_peritumoral_band_stays_in_the_organ_and_outside_the_tumor() -> None:
    spacing = (1.0, 1.0, 1.0)
    labels = ellipsoid((24, 24, 24), spacing, 5.0)
    labels[:, :, :6] = 0  # not organ
    out = derive(labels, spacing)
    peri = out == m.VALUES["peri"]
    dist = min_dist(coords(peri, spacing), coords(labels == TUMOR, spacing))
    assert peri.any() and dist.min() > 2.0 and dist.max() <= 5.0
    assert not (peri & (labels == TUMOR)).any() and (labels[peri] == KIDNEY).all()
    unrestricted = m.derive(
        labels, spacing, [TUMOR], None, core_mm=3.0, peri_inner_mm=2.0, peri_outer_mm=5.0
    )
    assert (unrestricted == m.VALUES["peri"]).sum() > peri.sum()


@pytest.mark.parametrize(
    ("spacing", "expected"),
    [((1.0, 1.0, 1.0), (216, 1512, 4904)), ((0.7, 0.8, 2.5), (240, 1488, 4952))],
)
def test_RAD15_matches_the_research_pipeline(
    spacing: tuple[float, ...], expected: tuple[int, int, int]
) -> None:
    """Counts of the research `compute_derived_masks` on the same single-lesion volume."""
    labels = np.zeros((32, 32, 32), np.uint8)
    labels[2:30, 2:30, 2:30] = KIDNEY
    labels[8:20, 9:21, 10:22] = TUMOR
    out = derive(labels, spacing)
    assert tuple(int((out == m.VALUES[r]).sum()) for r in ("core", "rim", "peri")) == expected


def test_RAD15_affine_geometry() -> None:
    rotation = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    oblique = np.eye(4)
    oblique[:3, :3] = rotation @ np.diag([0.7, 0.8, 2.5])
    assert np.allclose(m.spacing_of(oblique), [0.7, 0.8, 2.5])
    sheared = np.eye(4)
    sheared[0, 1] = 0.5
    with pytest.raises(ValueError, match="sheared"):
        m.spacing_of(sheared)
    with pytest.raises(ValueError, match="voxel size"):
        m.spacing_of(np.diag([1.0, 0.0, 1.0, 1.0]))


def test_RAD15_quality_flags_small_empty_and_coarse_regions() -> None:
    spacing = (1.0, 1.0, 1.0)
    labels = ellipsoid((20, 20, 20), spacing, 2.5)
    regions = ["core", "rim", "peri"]
    out = derive(labels, spacing)
    qc = m.quality(
        out, int((labels == TUMOR).sum()), spacing, regions,
        min_voxels=64, core_mm=3.0, peri_width_mm=3.0,
    )  # fmt: skip
    assert qc["voxels"]["core"] == 0 and "empty_core" in qc["flags"]
    assert "too_small_rim" in qc["flags"] and "coarse_spacing" not in qc["flags"]
    assert qc["volume_ml"]["tumor"] == pytest.approx(qc["voxels"]["tumor"] / 1000)
    thick = m.quality(
        out, 1, (0.8, 0.8, 5.0), ["peri"], min_voxels=0, core_mm=3.0, peri_width_mm=3.0
    )
    assert thick["flags"] == ["coarse_spacing"]
    with pytest.raises(ValueError, match="band"):
        task.options({"peri_inner_mm": 5, "peri_outer_mm": 2})


def fake_job(tmp_path: Path, labels: dict[str, int]) -> Any:
    return cast(Any, SimpleNamespace(context={"labels": labels}, output_dir=tmp_path / "out"))


def item_with(
    tmp_path: Path, mask: Any, affine: Any, image_affine: Any | None = None
) -> dict[str, Any]:
    nib.save(nib.Nifti1Image(mask, affine), tmp_path / "mask.nii.gz")
    ct_affine = affine if image_affine is None else image_affine
    nib.save(nib.Nifti1Image(np.zeros(mask.shape, np.int16), ct_affine), tmp_path / "ct.nii.gz")
    return {
        "item_id": "i.1",
        "case_id": "c",
        "image": {"path": str(tmp_path / "ct.nii.gz"), "format": "nifti"},
        "masks": {"s": {"path": str(tmp_path / "mask.nii.gz"), "format": "nifti"}},
    }


def test_RAD15_item_refusals_are_explicit(tmp_path: Path) -> None:
    opts = task.options({})
    labels = ellipsoid((16, 16, 16), (1.0, 1.0, 1.0), 4.0)
    shifted = np.eye(4)
    shifted[0, 3] = 5.0
    item = item_with(tmp_path, labels, np.eye(4), shifted)
    job = fake_job(tmp_path, {"kidney": 1, "tumor": 2})
    with pytest.raises(ValueError, match="affine differs"):
        task.derive_item(job, item, opts)
    with pytest.raises(SkipItem, match="not in the project"):
        task.derive_item(fake_job(tmp_path, {"kidney": 1}), item, opts)
    item = item_with(tmp_path, np.where(labels == TUMOR, 0, labels).astype(np.uint8), np.eye(4))
    with pytest.raises(SkipItem, match="no tumor voxels"):
        task.derive_item(job, item, opts)
    item["masks"]["s"]["format"] = "nifti_dir"
    with pytest.raises(SkipItem, match="NIfTI mask"):
        task.derive_item(job, item, opts)


def start(env: TestClient, proj: str, **settings: Any) -> dict[str, Any]:
    r = env.post(
        f"{API}/projects/{proj}/task-runs",
        json={
            "task_id": TASK,
            "settings": settings,
            "selection": {"item_ids": ITEMS[:2], "seg_id": "imported"},
        },
        headers=WHO,
    )
    assert r.status_code == 202, r.text
    return finish(env, proj, r.json())


def project(env: TestClient, pid: str) -> dict[str, Any]:
    return dict(env.get(f"{API}/projects/{pid}").json())


def test_RAD15_task_registers_a_reproducible_set_with_qc(
    env: TestClient, proj: str, data_root: Path, tmp_path: Path
) -> None:
    with_derived(env, proj, tmp_path)
    run = start(env, proj, seg_id="regions-a")
    assert run["status"] == "completed", run
    assert run["counts"]["ok"] == 2
    cfg = project(env, proj)
    by_name = {e["name"]: e["value"] for e in cfg["label_map"]}
    [seg] = [s for s in cfg["segmentations"] if s["seg_id"] == "regions-a"]
    assert seg["kind"] == "task" and seg["producer"]["task_id"] == TASK
    assert {seg["label_mapping"][k] for k in ("1", "2", "3")} == {
        by_name["tumor_core"],
        by_name["tumor_rim"],
        by_name["peritumoral"],
    }
    out = Path(run["output_dir"])
    rows = [json.loads(line) for line in (out / task.QC).read_text().splitlines()]
    assert sorted(r["item_id"] for r in rows) == sorted(ITEMS[:2])
    assert all(r["voxels"]["tumor"] == r["voxels"]["core"] + r["voxels"]["rim"] for r in rows)
    written = sorted(out.rglob("*_regions.nii.gz"))
    source = nib.load(next(data_root.rglob("seg/*case_00001.nii.gz")))
    derived = nib.load(written[0])
    assert np.allclose(derived.affine, source.affine) and derived.shape == source.shape  # type: ignore[attr-defined]
    assert int(derived.header["sform_code"]) == int(source.header["sform_code"])
    # The same inputs and settings give the same bytes in a new set; a taken name is refused
    again = start(env, proj, seg_id="regions-b")
    digest = [hashlib.sha256(p.read_bytes()).hexdigest() for p in written]
    assert digest == [
        hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(again["output_dir"]).rglob("*_regions.nii.gz"))
    ]
    r = env.post(
        f"{API}/projects/{proj}/task-runs",
        json={
            "task_id": TASK,
            "settings": {"seg_id": "regions-a"},
            "selection": {"item_ids": ITEMS[:1]},
        },
        headers=WHO,
    )
    assert r.status_code == 422


def test_RAD15_radiomics_reads_the_derived_set_and_records_an_empty_region(
    env: TestClient, proj: str, tmp_path: Path
) -> None:
    pytest.importorskip("radiomics")
    from tests.test_api_ingest import wait

    with_derived(env, proj, tmp_path)
    # A core farther than the tumor radius is empty; the rim is then the whole tumor
    assert start(env, proj, seg_id="regions-c", core_mm=20)["status"] == "completed"
    by_name = {e["name"]: e["value"] for e in project(env, proj)["label_map"]}
    core, rim = by_name["tumor_core"], by_name["tumor_rim"]
    r = env.post(
        f"{API}/projects/{proj}/task-runs",
        json={
            "task_id": "radiomics.pyradiomics",
            "settings": {},
            "selection": {"item_ids": ITEMS[:1], "labels": [core, rim], "seg_id": "regions-c"},
        },
        headers=WHO,
    )
    assert r.status_code == 202, r.text
    wait(env, r.json()["job_id"])
    rid = r.json()["run_id"]
    feats = env.get(f"{API}/projects/{proj}/radiomics/runs/{rid}/features").json()
    labels = {row["label"] for row in feats["rows"]}
    assert labels == {rim}
    errors = [
        e["radiomics"] for e in env.get(f"{API}/projects/{proj}/task-runs/{rid}/errors").json()
    ]
    assert {e["label"] for e in errors} == {core}


def extract(env: TestClient, pid: str, seg_id: str, labels: list[int], **settings: Any) -> str:
    from tests.test_api_ingest import wait

    r = env.post(
        f"{API}/projects/{pid}/task-runs",
        json={
            "task_id": "radiomics.pyradiomics",
            "settings": {"settings": settings} if settings else {},
            "selection": {"item_ids": ITEMS[:1], "labels": labels, "seg_id": seg_id},
        },
        headers=WHO,
    )
    assert r.status_code == 202, r.text
    wait(env, r.json()["job_id"])
    return str(r.json()["run_id"])


def test_RAD16_combined_run_joins_tumor_and_regions(
    env: TestClient, proj: str, tmp_path: Path
) -> None:
    pytest.importorskip("radiomics")
    with_derived(env, proj, tmp_path)
    assert start(env, proj, seg_id="regions-d", core_mm=1)["status"] == "completed"
    by_name = {e["name"]: e["value"] for e in project(env, proj)["label_map"]}
    rim = by_name["tumor_rim"]
    tumor_run = extract(env, proj, "imported", [TUMOR])
    rim_run = extract(env, proj, "regions-d", [rim])
    url = f"{API}/projects/{proj}/radiomics/runs/combine"
    body = {"run_ids": [tumor_run, rim_run], "name": "tumor + rim"}
    assert env.post(url, json=body).status_code == 428  # reviewer stamp
    r = env.post(url, json=body, headers=WHO)
    assert r.status_code == 201, r.text
    run = r.json()
    rid = run["run_id"]
    assert run["sources"] == [tumor_run, rim_run] and run["status"] == "completed"
    assert run["selection"]["labels"] == sorted([TUMOR, rim])
    assert run["selection"]["seg_id"] == "imported+regions-d"
    feats = env.get(f"{API}/projects/{proj}/radiomics/runs/{rid}/features").json()["rows"]
    assert {f["label"] for f in feats} == {TUMOR, rim} and {f["run_id"] for f in feats} == {rid}
    listed = env.get(f"{API}/projects/{proj}/task-runs", params={"task": "radiomics.pyradiomics"})
    assert rid in {x["run_id"] for x in listed.json()}
    # The dashboard reads it as any run: tumor vs rim of the same item
    pair = {"feature": "original_firstorder_Mean", "pair": {"kind": "label"}}
    view = env.post(
        f"{API}/projects/{proj}/radiomics/runs/{rid}/views/phase-side-consistency", json=pair
    )
    assert view.status_code == 200, view.text
    assert (view.json()["a"], view.json()["b"], view.json()["n_pairs"]) == (str(TUMOR), str(rim), 1)
    # Refused: shared (item, label) pairs, different settings, a finished run resumed
    again = env.post(url, json={"run_ids": [tumor_run, rid]}, headers=WHO)
    assert again.status_code == 422 and "share" in again.text
    other = extract(env, proj, "regions-d", [by_name["peritumoral"]], binWidth=10)
    differs = env.post(url, json={"run_ids": [tumor_run, other]}, headers=WHO)
    assert differs.status_code == 422 and "different settings" in differs.text
    assert env.post(f"{API}/projects/{proj}/task-runs/{rid}/resume").status_code == 409
    assert env.post(url, json={"run_ids": [tumor_run, tumor_run]}, headers=WHO).status_code == 422
