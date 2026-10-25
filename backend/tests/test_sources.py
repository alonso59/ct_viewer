"""TST-15 sources (SRC-01..12): formats, detect (API-19), `nifti-files` adapter, single-file
import, identity registry stability, Open mode (API-07/08), refusal `actions[]`; and the
NumPy half of TST-13 (xyz/zyx marker at the expected RAS mm)."""

from __future__ import annotations

import hashlib
import json
import string
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from app.config import Settings
from app.core.ids import CASE_ID_RE
from app.imaging import npy_convert
from app.imaging.header import read_header
from app.main import create_app
from app.sources import formats
from app.sources.identity import IdentityRegistry, slug
from app.sources.nifti_files import NiftiOptions, plan
from tests.test_api_ingest import ctx_of, pages, wait
from tests.test_contract import assert_problem

API = "/api/v1"


def nii(path: Path, data: np.ndarray, affine: np.ndarray | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(
        nib.Nifti1Image(data, np.diag([0.8, 0.8, 1.5, 1.0]) if affine is None else affine), path
    )
    return path


def ct(shape: tuple[int, int, int] = (8, 9, 5)) -> np.ndarray:
    """Float HU test volume."""
    return (np.arange(np.prod(shape)).reshape(shape) * 0.37 - 100).astype(np.float32)


def lab(shape: tuple[int, int, int] = (8, 9, 5)) -> np.ndarray:
    a = np.zeros(shape, np.uint8)
    a[2:4, 2:5, 1:3] = 1
    return a


@pytest.fixture
def src(tmp_path: Path) -> Path:
    """A plain NIfTI folder (images + seg/), no metadata.jsonl."""
    root = tmp_path / "src"
    for case in ("alpha", "beta"):
        nii(root / "images" / f"{case}.nii.gz", ct())
        nii(root / "seg" / f"{case}.nii.gz", lab())
    nii(root / "other" / "loose scan.nii", ct())
    (root / "notes.txt").write_text("x")
    (root / "arr.npz").write_bytes(b"PK")
    return root


@pytest.fixture
def sclient(tmp_path: Path, src: Path) -> Iterator[TestClient]:
    s = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(src.resolve()),
        _env_file=None,  # type: ignore[call-arg]
    )
    with TestClient(create_app(s, inline_jobs=True)) as c:
        yield c


def project(c: TestClient) -> str:
    return str(
        c.post(f"{API}/projects", json={"name": "s", "packs": ["ccrcc"]}).json()["project_id"]
    )


def tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_classify(tmp_path: Path) -> None:
    from tools.dicom_fixtures import write_series

    folder = tmp_path / "series"
    write_series(folder, shape=(3, 3, 1), marker=(1, 1, 0))
    dcm = tmp_path / "IM0001"
    dcm.write_bytes(next(folder.iterdir()).read_bytes())
    assert formats.classify(dcm) == "dicom"
    (tmp_path / "x.dcm").write_bytes(b"")
    assert formats.classify(tmp_path / "x.dcm") is None  # SRC-18: suffix alone is not an image
    assert formats.classify(tmp_path / "a.nii.gz") == "nifti"
    assert formats.classify(tmp_path / "a.NII") == "nifti"
    assert formats.classify(tmp_path / "a.npy") == "npy"
    (tmp_path / "IM2").write_bytes(b"no magic")
    assert formats.classify(tmp_path / "IM2") is None
    assert formats.classify(tmp_path / "a.npz") is None


def test_detect_folder_file_and_refusal(sclient: TestClient, src: Path, fixtures_src: Path) -> None:
    r = sclient.post(f"{API}/sources/detect", json={"path": str(src)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "folder" and body["counts"]["nifti"] == 5
    assert body["ignored"] == {".txt": 1, ".npz": 1}
    assert [c["adapter"] for c in body["candidates"]] == ["nifti-files", "open"]
    assert body["candidates"][0]["confidence"] == "high"
    one = src / "other" / "loose scan.nii"
    body = sclient.post(f"{API}/sources/detect", json={"path": str(one)}).json()
    assert body["kind"] == "file" and body["root"] == str(one.parent)
    assert body["candidates"][0]["options"] == {"include": ["loose scan.nii"]}
    (src / "empty").mkdir()
    (src / "empty" / "a.txt").write_text("x")
    r = sclient.post(f"{API}/sources/detect", json={"path": str(src / "empty")})
    assert_problem(r, "unsupported-format")
    assert r.json()["actions"] == ["choose_another_path"] and "1 .txt" in r.json()["detail"]
    assert_problem(sclient.post(f"{API}/sources/detect", json={"path": "/"}), "path-outside-root")
    dcm = src / "d" / "IM1"
    dcm.parent.mkdir()
    dcm.write_bytes(next((fixtures_src / "dicom").rglob("*.dcm")).read_bytes())
    cand = sclient.post(f"{API}/sources/detect", json={"path": str(dcm)}).json()["candidates"][0]
    assert cand["adapter"] == "dicom.convert"


def test_detect_prefers_metadata_v1(client: TestClient, data_root: Path) -> None:
    body = client.post(f"{API}/sources/detect", json={"path": str(data_root)}).json()
    assert [c["adapter"] for c in body["candidates"]][:2] == ["metadata-v1", "nifti-files"]
    assert body["candidates"][1]["confidence"] == "low"


def test_plan_conventions(src: Path) -> None:
    p = plan(src, NiftiOptions(), IdentityRegistry())
    rows = {r["case_id"]: r for r in p.rows}
    assert set(rows) == {"alpha", "beta", "loose_scan"}  # one case per stem
    a = rows["alpha"]
    assert a["scan_idx"] == "01" and a["modality"] == "CT" and "channel" not in a
    assert a["seg_path"] == "seg/alpha.nii.gz"
    assert rows["loose_scan"]["scan_idx"] == "01" and "seg_path" not in rows["loose_scan"]
    assert p.unmatched == [] and p.orphan_masks == []
    assert all(r["source_kind"] == "nifti" for r in p.rows)


def test_plan_nnunet_names_are_not_special(tmp_path: Path) -> None:
    """nnU-Net naming belongs to the nnU-Net plugin (TSK-08), not to core import."""
    root = tmp_path / "r"
    nii(root / "imagesTr" / "01_CT_alpha_0000.nii.gz", ct())
    nii(root / "imagesTr" / "01_CT_alpha_0001.nii.gz", ct())
    nii(root / "labelsTr" / "01_CT_alpha.nii.gz", lab())
    p = plan(root, NiftiOptions(), IdentityRegistry())
    assert sorted(r["source_name"] for r in p.rows) == [
        "01_CT_alpha",
        "01_CT_alpha_0000",
        "01_CT_alpha_0001",
    ]
    assert not any("seg_path" in r or "channel" in r for r in p.rows) and p.skipped_channels == 0
    with pytest.raises(ValueError, match="unknown mask conventions"):
        NiftiOptions(mask_conventions=["labelsTr/{case}.nii.gz"])


def test_plan_user_pattern_channels_and_converter_layout(tmp_path: Path) -> None:
    root = tmp_path / "r"
    # metadata-v1 / converter layout: seg/{name minus _0000}
    nii(root / "nifti" / "01_case_00001_0000.nii.gz", ct())
    nii(root / "nifti" / "01_case_00001_0001.nii.gz", ct())
    nii(root / "seg" / "01_case_00001.nii.gz", lab())
    pattern = r"^(?P<scan_idx>\d+)_(?P<case_id>.+?)_(?P<channel>\d{4})$"
    p = plan(root, NiftiOptions(pattern=pattern), IdentityRegistry())
    [row] = p.rows
    assert (row["case_id"], row["scan_idx"], row["channel"]) == ("case_00001", "01", "0000")
    assert row["seg_path"] == "seg/01_case_00001.nii.gz"
    assert row["channels"] == ["nifti/01_case_00001_0001.nii.gz"] and p.skipped_channels == 1


def test_plan_seg_dir_suffix_and_sequential(tmp_path: Path) -> None:
    root = tmp_path / "r"
    nii(root / "nifti" / "a.nii.gz", ct())
    nii(root / "seg" / "a.nii.gz", lab())
    nii(root / "b.nii.gz", ct())
    nii(root / "b_mask.nii.gz", lab())
    nii(root / "orphan_seg.nii.gz", lab())
    p = plan(root, NiftiOptions(case_id_from="sequential", modality="MR"), IdentityRegistry())
    by_name = {r["source_name"]: r for r in p.rows}
    assert by_name["a"]["seg_path"] == "seg/a.nii.gz"
    assert by_name["b"]["seg_path"] == "b_mask.nii.gz"
    assert sorted(r["case_id"] for r in p.rows) == ["case_00000", "case_00001"]
    assert {r["modality"] for r in p.rows} == {"MR"}
    assert p.orphan_masks == ["orphan_seg.nii.gz"]
    # same registry, same answer (SRC-07): nothing renumbers
    again = plan(root, NiftiOptions(case_id_from="sequential"), p.registry)
    assert [r["case_id"] for r in again.rows] == [r["case_id"] for r in p.rows]


def test_modality_codes_mri_is_mr(tmp_path: Path) -> None:
    """DCM-12: modality values are DICOM codes; `MRI` (file names, converter CLI) becomes `MR`."""
    from plugins.dicom.rows import header_row
    from plugins.dicom.scan import Inspection, Series
    from pydicom.dataset import Dataset

    root = tmp_path / "r"
    nii(root / "01_MRI_alpha.nii.gz", ct())
    nii(root / "01_CT_beta.nii.gz", ct())
    pattern = r"^(?P<scan_idx>\d+)_(?P<modality>[A-Z]+)_(?P<case_id>.+)$"
    p = plan(root, NiftiOptions(pattern=pattern), IdentityRegistry())
    assert {r["case_id"]: r["modality"] for r in p.rows} == {"alpha": "MR", "beta": "CT"}
    for code, want in (("MRI", "MR"), ("MR", "MR"), ("CT", "CT")):
        ds = Dataset()
        ds.Modality = code
        row = header_row(ds, Series(tmp_path, "s1", (tmp_path / "a.dcm",)), "p1", Inspection())
        assert row["modality"] == want


def test_options_are_validated() -> None:
    with pytest.raises(ValueError, match="unknown named groups"):
        NiftiOptions(pattern=r"(?P<nope>.+)")
    with pytest.raises(ValueError, match="invalid regular expression"):
        NiftiOptions(pattern="(")
    with pytest.raises(ValueError, match="unknown mask conventions"):
        NiftiOptions(mask_conventions=["x"])


@settings(max_examples=60, deadline=None)
@given(
    names=st.lists(
        st.text(
            alphabet=string.ascii_letters + string.digits + " _-.()", min_size=1, max_size=14
        ).filter(
            lambda n: not n.startswith(".")  # hidden files are skipped by design
        ),
        min_size=1,
        max_size=8,
        unique=True,
    )
)
def test_plan_any_names_give_slug_ids(
    tmp_path_factory: pytest.TempPathFactory, names: list[str]
) -> None:
    """Hypothesis (TST-15): any file names → valid, unique slug case ids (SRC-08)."""
    root = tmp_path_factory.mktemp("h")
    for n in names:
        (root / f"{n}.nii").write_bytes(b"")  # names only; headers are read by the index job
    p = plan(root, NiftiOptions(), IdentityRegistry())
    assert all(CASE_ID_RE.match(r["case_id"]) for r in p.rows)
    assert all(CASE_ID_RE.match(r["scan_idx"]) for r in p.rows)
    assert p.rows  # every name yields a row (duplicates are flagged later, IMP-08)


def test_slug_and_registry_merge() -> None:
    assert slug("a b/c.d") == "a_b_c_d" and slug("...") == "x" and len(slug("x" * 99)) == 64
    a = IdentityRegistry()
    a.case_id("k1")
    b = IdentityRegistry(cases={"k1": 7, "k2": 3}, next_index=8)
    m = a.merge(b)
    assert m.cases == {"k1": 0, "k2": 3} and m.next_index == 8  # existing keys never change
    assert m.case_id("k3") == "case_00008"
    t = IdentityRegistry(table={"k": "P 1"})
    assert t.case_id("k") == "P_1"


def import_nifti(
    c: TestClient, pid: str, root: Path, options: dict[str, Any] | None = None
) -> dict[str, Any]:
    r = c.post(
        f"{API}/projects/{pid}/imports/preview",
        json={"root": str(root), "adapter": "nifti-files", "options": options or {}},
    )
    assert r.status_code == 200, r.text
    pv = r.json()
    r = c.post(f"{API}/projects/{pid}/imports", json={"preview_id": pv["preview_id"]})
    assert r.status_code == 202, r.text
    assert wait(c, r.json()["job_id"]).status == "succeeded"
    return dict(pv, import_id=r.json()["import_id"])


def test_nifti_folder_import(sclient: TestClient, src: Path) -> None:
    before = tree(src)
    pid = project(sclient)
    pv = import_nifti(sclient, pid, src)
    assert pv["adapter"] == "nifti-files" and pv["files"][0]["source"] == "generated"
    assert {s["case_id"] for s in pv["sample"]} == {"alpha", "beta", "loose_scan"}
    assert pv["unmatched"] == [] and pv["ignored"] == {".txt": 1, ".npz": 1}
    items = {
        i["item_id"]: i
        for s in sclient.get(f"{API}/projects/{pid}/cases/alpha").json()["scans"]
        for i in s["items"]
    }
    it = items["alpha.01.complete.-"]
    assert it["modality"] == "CT" and it["phase"]["canonical"] == "UNK"
    assert it["masks"]["imported"]["ref"] == "DATA:seg/alpha.nii.gz"
    assert it["extra"]["source_name"] == "alpha" and it["geometry"]["shape"] == [8, 9, 5]
    pdir = ctx_of(sclient).workspace.project_dir(pid)
    source = json.loads((pdir / "sources" / pv["import_id"] / "source.json").read_text())
    assert source["adapter"] == "nifti-files" and source["options"]["modality"] == "CT"
    assert tree(src) == before  # R1


def test_incremental_import_keeps_identity(sclient: TestClient, src: Path) -> None:
    pid = project(sclient)
    opts = {"case_id_from": "sequential"}
    import_nifti(sclient, pid, src, opts)
    pdir = ctx_of(sclient).workspace.project_dir(pid)
    first = json.loads((pdir / "sources" / "identity.json").read_text())
    cases1 = {c["case_id"] for c in sclient.get(f"{API}/projects/{pid}/cases").json()["items"]}
    nii(src / "images" / "aaa.nii.gz", ct())  # sorts first: must not renumber
    import_nifti(sclient, pid, src, opts)
    second = json.loads((pdir / "sources" / "identity.json").read_text())
    assert all(second["cases"][k] == v for k, v in first["cases"].items())
    assert second["cases"]["aaa"] == first["next_index"]
    cases2 = {c["case_id"] for c in sclient.get(f"{API}/projects/{pid}/cases").json()["items"]}
    assert cases1 < cases2 and len(cases2 - cases1) == 1


def test_single_file_import(sclient: TestClient, src: Path) -> None:
    pid = project(sclient)
    one = src / "other" / "loose scan.nii"
    r = sclient.post(f"{API}/projects/{pid}/imports/preview", json={"root": str(one)})
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["root"] == str(one.parent) and pv["options"]["include"] == ["loose scan.nii"]
    assert pv["counts"]["scan_rows"] == 1
    r = sclient.post(f"{API}/projects/{pid}/imports", json={"preview_id": pv["preview_id"]})
    assert wait(sclient, r.json()["job_id"]).status == "succeeded"
    cases = sclient.get(f"{API}/projects/{pid}/cases").json()["items"]
    assert [c["case_id"] for c in cases] == ["loose_scan"]
    txt = src / "notes.txt"
    r = sclient.post(f"{API}/projects/{pid}/imports/preview", json={"root": str(txt)})
    assert_problem(r, "unsupported-format")


def test_single_file_with_attached_mask_and_quiet_warnings(sclient: TestClient, src: Path) -> None:
    """AUD-A2-12 (SRC-04/05, ADR-0027): the Open-mode attachment travels as `masks`, from a
    sibling folder under the common parent; `nifti-files` rows get no phase warning (UNK by
    design) and no metadata-v1 `seg/` guess under the image's own folder."""
    nii(src / "seg" / "renamed mask.nii.gz", lab())
    pid = project(sclient)
    opts = {"include": ["images/alpha.nii.gz", "seg/renamed mask.nii.gz"],
            "masks": {"images/alpha.nii.gz": "seg/renamed mask.nii.gz"}}  # fmt: skip
    pv = import_nifti(sclient, pid, src, opts)
    assert pv["counts"]["scan_rows"] == 1 and pv["sample"][0]["mask"] == "seg/renamed mask.nii.gz"
    it = sclient.get(f"{API}/projects/{pid}/items/alpha.01.complete.-").json()
    assert it["masks"]["imported"]["ref"] == "DATA:seg/renamed mask.nii.gz"
    warns = pages(sclient, f"{API}/projects/{pid}/warnings")
    assert warns == [], warns
    # one file, no mask: only `missing_seg`, without a path under the image's folder
    pid2 = project(sclient)
    import_nifti(sclient, pid2, src / "images", {"include": ["beta.nii.gz"]})
    codes = [
        (w["code"], w.get("path_ref")) for w in pages(sclient, f"{API}/projects/{pid2}/warnings")
    ]
    assert codes == [("missing_seg", None)]


def test_metadata_refusal_suggests_nifti_files(sclient: TestClient, src: Path) -> None:
    pid = project(sclient)
    r = sclient.post(f"{API}/projects/{pid}/imports/preview", json={"root": str(src)})
    assert_problem(r, "validation")
    body = r.json()
    assert body["detail"] == "No metadata.jsonl under the root; 5 NIfTI files found"
    assert body["actions"] == ["import_as:nifti-files", "open"]
    bad = sclient.post(
        f"{API}/projects/{pid}/imports/preview",
        json={"root": str(src), "adapter": "nifti-files", "options": {"pattern": "("}},
    )
    assert_problem(bad, "validation")


def open_(c: TestClient, path: Path) -> dict[str, Any]:
    r = c.post(f"{API}/open", json={"path": str(path)})
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_open_nifti_file_is_always_an_image(sclient: TestClient, src: Path) -> None:
    ws = ctx_of(sclient).settings.workspace_root
    registry_before = (ws / "workspace.json").read_bytes()
    s = open_(sclient, src / "images" / "alpha.nii.gz")
    assert s["kind"] == "file" and len(s["items"]) == 1
    it = s["items"][0]
    assert it["item_id"] == "open.0" and it["kind"] == "image" and it["n_slices"] == 5
    assert it["modality"] is None  # NIfTI: unknown → percentiles (VW-05)
    r = sclient.get(f"{API}/open/{s['sid']}/items/0/image")
    assert r.status_code == 200
    assert r.content == (src / "images" / "alpha.nii.gz").read_bytes()
    # SRC-09: no label guessing; a segmentation opened alone and a small integer CT are images
    lab_s = open_(sclient, src / "seg" / "alpha.nii.gz")
    assert lab_s["items"][0]["kind"] == "image"
    small_ct = nii(src / "small_ct.nii.gz", np.full((8, 9, 5), -1024, np.int16))
    assert open_(sclient, small_ct)["items"][0]["kind"] == "image"
    # nothing written to projects or the registry (SRC-09)
    assert (ws / "workspace.json").read_bytes() == registry_before
    assert not any((ws / "projects").glob("[0-9A-Z]*"))
    assert sclient.delete(f"{API}/open/{s['sid']}").status_code == 204
    assert_problem(sclient.get(f"{API}/open/{s['sid']}"), "not-found")


def test_open_folder_and_attach(sclient: TestClient, src: Path, tmp_path: Path) -> None:
    s = open_(sclient, src)
    names = {i["rel"]: i for i in s["items"]}
    assert "seg/alpha.nii.gz" in names and s["ignored"] == {".txt": 1, ".npz": 1}
    n = names["images/alpha.nii.gz"]["n"]
    r = sclient.post(
        f"{API}/open/{s['sid']}/items/{n}/attach",
        json={"path": str(src / "seg/alpha.nii.gz")},
    )
    assert r.status_code == 200, r.text
    added = r.json()["items"][-1]
    assert added["attached_to"] == n and added["kind"] == "label"
    bad = nii(src / "wrong.nii.gz", lab((4, 4, 4)))
    r = sclient.post(f"{API}/open/{s['sid']}/items/{n}/attach", json={"path": str(bad)})
    assert_problem(r, "geometry-mismatch")
    assert "[8, 9, 5]" in r.json()["detail"] and "[4, 4, 4]" in r.json()["detail"]
    aff = np.diag([0.8, 0.8, 1.5, 1.0])
    aff[0, 3] = 5.0
    shifted = nii(src / "shifted.nii.gz", lab(), aff)
    assert_problem(
        sclient.post(f"{API}/open/{s['sid']}/items/{n}/attach", json={"path": str(shifted)}),
        "geometry-mismatch",
    )
    # SRC-10: only a NIfTI segmentation can be attached
    np.save(src / "seg.npy", lab())
    assert_problem(
        sclient.post(
            f"{API}/open/{s['sid']}/items/{n}/attach", json={"path": str(src / "seg.npy")}
        ),
        "unsupported-format",
    )
    (src / "empty").mkdir()
    r = sclient.post(f"{API}/open", json={"path": str(src / "empty")})
    assert_problem(r, "unsupported-format")


def test_open_numpy_axis_order(sclient: TestClient, src: Path) -> None:
    arr = np.zeros((5, 9, 8), np.int16)  # zyx of an (8, 9, 5) volume
    arr[3, 4, 6] = 1000
    np.save(src / "vol.npy", arr)
    s = open_(sclient, src / "vol.npy")
    it = s["items"][0]
    assert it["needs_axis_order"] and it["axis_order"] is None
    r = sclient.get(f"{API}/open/{s['sid']}/items/0/image")
    assert_problem(r, "ambiguous-axis-order")
    assert r.json()["actions"] == ["axis_order:xyz", "axis_order:zyx"]
    png = sclient.get(f"{API}/open/{s['sid']}/items/0/preview", params={"axis_order": "zyx"})
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    r = sclient.get(f"{API}/open/{s['sid']}/items/0/image", params={"axis_order": "zyx"})
    assert r.status_code == 200
    out = src.parent / "o.nii.gz"
    out.write_bytes(r.content)
    img: Any = nib.load(out)
    assert img.shape == (8, 9, 5) and np.asanyarray(img.dataobj)[6, 4, 3] == 1000
    scratch = ctx_of(sclient).settings.workspace_root / ".scratch" / "open"
    assert any(scratch.iterdir())
    # a sidecar decides the order (SRC-12)
    (src / "vol.npy.json").write_text(json.dumps({"axis_order": "zyx", "spacing": [0.5, 1, 2]}))
    it = open_(sclient, src / "vol.npy")["items"][0]
    assert it["axis_order"] == "zyx" and not it["needs_axis_order"]
    assert it["geometry"]["shape"] == [8, 9, 5] and it["geometry"]["spacing"] == [0.5, 1.0, 2.0]


@pytest.mark.parametrize("order", ["xyz", "zyx"])
def test_numpy_marker_lands_at_expected_ras_mm(tmp_path: Path, order: str) -> None:
    xyz = np.zeros((6, 7, 8), np.int16)
    xyz[3, 5, 7] = 1  # asymmetric marker: i=3 (x), j=5 (y), k=7 (z)
    arr = xyz if order == "xyz" else np.transpose(xyz, (2, 1, 0))
    src = tmp_path / "m.npy"
    np.save(src, arr)
    dst = tmp_path / "cache" / "m.nii.gz"
    assert npy_convert.convert(str(src), str(dst), [0.5, 1.0, 2.0], order) is None  # type: ignore[arg-type]
    img: Any = nib.load(dst)
    ijk = np.argwhere(np.asanyarray(img.dataobj) == 1)[0]
    mm = img.affine @ np.array([*ijk, 1.0])
    assert tuple(ijk) == (3, 5, 7)
    assert np.allclose(mm[:3], [1.5, 5.0, 14.0])  # spacing is x, y, z whatever the order
    assert read_header(src, spacing=(0.5, 1.0, 2.0), axis_order=order).shape == (6, 7, 8)


def test_decide_axis_order() -> None:
    assert npy_convert.decide_axis_order((2, 3, 4), "zyx") == "zyx"
    assert npy_convert.decide_axis_order((2, 3, 4), None, (2, 3, 4)) == "xyz"
    assert npy_convert.decide_axis_order((2, 3, 4), None, (4, 3, 2)) == "zyx"
    assert npy_convert.decide_axis_order((3, 3, 3), None, (3, 3, 3)) is None  # both
    assert npy_convert.decide_axis_order((2, 3, 4), None, (9, 9, 9)) is None  # neither
    assert npy_convert.decide_axis_order((2, 3, 4)) is None


def one_hot(shape: tuple[int, int, int], x: int) -> np.ndarray:
    a = np.zeros(shape, np.uint8)
    a[x, 2:5, 1:3] = 1
    return a


@pytest.fixture
def per_case(src: Path) -> Path:
    """A PanTS-like layout: `ImageTr/{case}/ct.nii.gz` + `LabelTr/{case}/segmentations/*`."""
    root = src / "pants"
    for case, organs in (("P_001", ("liver", "pancreas")), ("P_002", ("pancreas",))):
        nii(root / "ImageTr" / case / "ct.nii.gz", ct())
        for k, organ in enumerate(organs):
            nii(
                root / "LabelTr" / case / "segmentations" / f"{organ}.nii.gz", one_hot((8, 9, 5), k)
            )
    return root


def test_plan_path_pattern_template_and_mask_set(per_case: Path) -> None:
    from app.sources.nifti_files import FOLDER_PATTERN

    p = plan(per_case, NiftiOptions(), IdentityRegistry())
    assert [r["case_id"] for r in p.rows] == ["ct", "liver", "pancreas"]
    assert len(p.collisions) == 2  # every ct.nii.gz is case `ct`: refused, never merged
    opts = NiftiOptions(
        pattern=r"^ImageTr/(?P<case_id>[^/]+)/ct$", mask_template="LabelTr/{case_id}/segmentations"
    )
    p = plan(per_case, opts, IdentityRegistry())
    rows = {r["case_id"]: r for r in p.rows}
    assert set(rows) == {"P_001", "P_002"} and p.collisions == [] and p.orphan_masks == []
    assert rows["P_001"]["seg_path"] == "LabelTr/P_001/segmentations"
    # one value per name across the import
    assert rows["P_001"]["seg_labels"] == {"liver": 1, "pancreas": 2}
    assert rows["P_002"]["seg_labels"] == {"pancreas": 2}
    assert rows["P_001"]["source_name"] == "ImageTr/P_001/ct"
    # the generic folder pattern: case = the image's parent folder, at any depth
    p = plan(per_case / "ImageTr", NiftiOptions(pattern=FOLDER_PATTERN), IdentityRegistry())
    assert [(r["case_id"], r["scan_idx"]) for r in p.rows] == [("P_001", "01"), ("P_002", "01")]


def test_mask_template_is_validated() -> None:
    with pytest.raises(ValueError, match="inside the root"):
        NiftiOptions(mask_template="../labels/{case_id}.nii.gz")
    with pytest.raises(ValueError, match="mask_template uses"):
        NiftiOptions(mask_template="labels/{scan_idx}.nii.gz")  # not a group of the pattern
    NiftiOptions(mask_template="labels/{case_id}_{stem}.nii.gz")


def test_collisions_are_refused_with_the_folder_pattern(
    sclient: TestClient, per_case: Path
) -> None:
    from app.sources.nifti_files import FOLDER_PATTERN

    pid = project(sclient)
    r = sclient.post(
        f"{API}/projects/{pid}/imports/preview",
        json={"root": str(per_case / "ImageTr"), "adapter": "nifti-files", "options": {}},
    )
    assert_problem(r, "validation")
    assert r.json()["actions"] == [f"use_pattern:{FOLDER_PATTERN}"]
    assert "collapse into one item" in r.json()["detail"]
    body = sclient.post(f"{API}/sources/detect", json={"path": str(per_case)}).json()
    assert body["candidates"][0]["sample"][0] == "ImageTr/P_001/ct.nii.gz"


def test_mask_set_imports_and_reads_as_one_label_map(sclient: TestClient, per_case: Path) -> None:
    before = tree(per_case)
    pid = str(sclient.post(f"{API}/projects", json={"name": "p", "packs": []}).json()["project_id"])
    opts = {
        "pattern": r"^ImageTr/(?P<case_id>[^/]+)/ct$",
        "mask_template": "LabelTr/{case_id}/segmentations",
    }
    import_nifti(sclient, pid, per_case, opts)
    item = sclient.get(f"{API}/projects/{pid}/items/P_001.01.complete.-").json()
    mask = item["masks"]["imported"]
    assert mask["format"] == "nifti_dir" and mask["labels"] == {"liver": 1, "pancreas": 2}
    assert item["labels_present"] == [1, 2]
    labels = sclient.get(f"{API}/projects/{pid}").json()["label_map"]
    assert [(lb["value"], lb["name"]) for lb in labels] == [(1, "liver"), (2, "pancreas")]
    r = sclient.get(f"{API}/projects/{pid}/items/P_001.01.complete.-/mask")
    assert r.status_code == 200, r.text
    out = per_case.parent / "composed.nii.gz"
    out.write_bytes(r.content)
    arr = np.asanyarray(nib.load(out).dataobj)
    assert arr[0, 3, 1] == 1 and arr[1, 3, 1] == 2 and arr.max() == 2
    again = sclient.get(
        f"{API}/projects/{pid}/items/P_001.01.complete.-/mask",
        headers={"If-None-Match": r.headers["etag"]},
    )
    assert again.status_code == 304
    out.unlink()
    m = sclient.get(f"{API}/projects/{pid}/items/P_001.01.complete.-/mesh/2")
    assert m.status_code in (200, 202), m.text  # built from the composed label map
    assert tree(per_case) == before  # R1


def test_mask_set_cache_tracks_member_changes(sclient: TestClient, per_case: Path) -> None:
    """SRC-04/API-24: a source edit invalidates the composed mask and its mesh key."""
    pid = project(sclient)
    import_nifti(
        sclient,
        pid,
        per_case,
        {
            "pattern": r"^ImageTr/(?P<case_id>[^/]+)/ct$",
            "mask_template": "LabelTr/{case_id}/segmentations",
        },
    )
    url = f"{API}/projects/{pid}/items/P_001.01.complete.-"
    first = sclient.get(f"{url}/mask")
    assert first.status_code == 200, first.text
    mesh_before = sclient.get(f"{url}/mesh/1")
    assert mesh_before.status_code in (200, 202), mesh_before.text
    if mesh_before.status_code == 202:
        wait(sclient, mesh_before.json()["job_id"])
        mesh_before = sclient.get(f"{url}/mesh/1")
    assert mesh_before.status_code == 200
    # Simulate an external source edit; the app must not mutate or reuse old bytes.
    nii(per_case / "LabelTr/P_001/segmentations/liver.nii.gz", one_hot((8, 9, 5), 3))
    before = tree(per_case)
    changed = sclient.get(f"{url}/mask", headers={"If-None-Match": first.headers["etag"]})
    assert changed.status_code == 200, changed.text
    assert changed.headers["etag"] != first.headers["etag"]
    assert changed.content != first.content
    mesh_after = sclient.get(f"{url}/mesh/1")
    assert mesh_after.status_code in (200, 202), mesh_after.text
    if mesh_after.status_code == 202:
        wait(sclient, mesh_after.json()["job_id"])
        mesh_after = sclient.get(f"{url}/mesh/1")
    assert mesh_after.status_code == 200
    assert mesh_after.headers["etag"] != mesh_before.headers["etag"]
    assert tree(per_case) == before


def test_mask_set_radiomics_uses_the_imported_structure_values(
    sclient: TestClient, per_case: Path
) -> None:
    """SRC-04/RAD-05: extraction uses the composed set's globally assigned labels."""
    pid = project(sclient)
    import_nifti(
        sclient,
        pid,
        per_case,
        {
            "pattern": r"^ImageTr/(?P<case_id>[^/]+)/ct$",
            "mask_template": "LabelTr/{case_id}/segmentations",
        },
    )
    before = tree(per_case)
    started = sclient.post(
        f"{API}/projects/{pid}/task-runs",
        headers={"X-Reviewer": "mask-set regression"},
        json={
            "task_id": "radiomics.pyradiomics",
            "settings": {"features": {"firstorder": ["Mean"]}},
            "selection": {"labels": [1, 2]},
        },
    )
    assert started.status_code == 202, started.text
    run = started.json()
    wait(sclient, run["job_id"])
    detail = sclient.get(f"{API}/projects/{pid}/task-runs/{run['run_id']}").json()
    assert detail["status"] == "completed", detail
    features = sclient.get(f"{API}/projects/{pid}/radiomics/runs/{run['run_id']}/features").json()
    rows = features["rows"]
    assert len(rows) == 3, features
    expected = {("P_001", 1): 0, ("P_001", 2): 1, ("P_002", 2): 0}
    for row in rows:
        assert row["feature"] == "Mean"
        x = expected[(row["case_id"], row["label"])]
        assert np.isclose(row["value"], ct()[one_hot((8, 9, 5), x) > 0].mean(), rtol=1e-6)
    assert tree(per_case) == before


def test_mask_set_refuses_a_member_replaced_with_a_symbolic_link(
    sclient: TestClient, per_case: Path, tmp_path: Path
) -> None:
    """SRC-04/BE-02: a changed source cannot make a volume request escape its mask folder."""
    pid = project(sclient)
    import_nifti(
        sclient,
        pid,
        per_case,
        {
            "pattern": r"^ImageTr/(?P<case_id>[^/]+)/ct$",
            "mask_template": "LabelTr/{case_id}/segmentations",
        },
    )
    member = per_case / "LabelTr/P_001/segmentations/liver.nii.gz"
    external = tmp_path / "external.nii.gz"
    external.write_bytes(member.read_bytes())
    member.unlink()
    member.symlink_to(external)
    response = sclient.get(f"{API}/projects/{pid}/items/P_001.01.complete.-/mask")
    assert_problem(response, "validation")
    assert "symbolic link" in response.json()["detail"]
