"""API-25 mesh job: MZ3 encoding, world coordinates, winding, cache, HTTP (VW-09, BE-03/06).

Run explicitly: `cd backend && .venv/bin/python -m pytest app/imaging/mesh_test.py`.
"""

from __future__ import annotations

import asyncio
import gzip
import struct
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from numpy.typing import NDArray

from app.api.v1 import mesh as mesh_api
from app.context import AppContext
from app.core.errors import NotFound, ValidationProblem
from app.events.bus import EventBus
from app.imaging import mesh
from app.imaging.fingerprint import quick_fingerprint
from app.ingest.models import Item, PhaseInfo, VolumeRef
from app.jobs.manager import JobManager
from app.jobs.types import JobInfo
from app.main import create_app
from app.projects.models import PathRoot
from tests.conftest import make_settings
from tests.test_imaging import NPY_MSK, SEG, forbid_source_writes
from tools.make_fixtures import DATASET, generate

NEG_AFFINE = np.array(
    [[-0.8, 0, 0, 10.0], [0, -0.8, 0, -5.0], [0, 0, 1.5, 3.0], [0, 0, 0, 1.0]], dtype=np.float64
)
POS_AFFINE = np.diag([0.8, 0.8, 1.5, 1.0])


def _sphere(shape: tuple[int, int, int], center: tuple[float, ...], r: float) -> NDArray[Any]:
    g = np.indices(shape, dtype=np.float32)
    d2 = sum((g[k] - center[k]) ** 2 for k in range(3))
    return np.asarray(d2 < r * r)


def _write_nii(path: Path, arr: NDArray[Any], affine: NDArray[Any]) -> Path:
    img = nib.Nifti1Image(arr.astype(np.uint8), affine)
    img.header.set_sform(affine, code=1)
    img.header.set_qform(affine, code=1)
    nib.save(img, path)
    return path


def _signed_volume(faces: NDArray[Any], verts: NDArray[Any]) -> float:
    v = verts.astype(np.float64)
    a, b, c = v[faces[:, 0]], v[faces[:, 1]], v[faces[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def _world_bbox(mask: NDArray[Any], affine: NDArray[Any], tol: float) -> tuple[Any, Any]:
    idx = np.argwhere(mask).astype(np.float64)
    lo, hi = idx.min(0) - tol, idx.max(0) + tol
    corners = np.array(
        [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    )
    w = corners @ affine[:3, :3].T + affine[:3, 3]
    return w.min(0), w.max(0)


# --- worker ------------------------------------------------------------------------------


def test_mz3_roundtrip_world_coords(tmp_path: Path) -> None:
    arr = np.zeros((30, 30, 20), np.uint8)
    arr[_sphere(arr.shape, (12, 15, 9), 6)] = 2
    arr[_sphere(arr.shape, (25, 25, 15), 3)] = 1
    src = _write_nii(tmp_path / "m.nii.gz", arr, NEG_AFFINE)
    dst = mesh.cache_path(tmp_path / "proj", "fp", 2, 0)
    assert dst == tmp_path / "proj" / "cache" / "meshes" / "fp_2_0.mz3"

    assert mesh.build(str(src), str(dst), 2, 0) is None
    blob = dst.read_bytes()
    assert blob[:2] == b"\x1f\x8b"
    raw = gzip.decompress(blob)
    magic, attr, nface, nvert, nskip = struct.unpack_from("<HHIII", raw)
    assert (magic, attr, nskip) == (23117, 3, 0)
    assert nface > 100 and nvert > 50
    assert len(raw) == 16 + nface * 12 + nvert * 12
    faces, verts = mesh.decode_mz3(blob)
    assert faces.shape == (nface, 3) and verts.shape == (nvert, 3)
    assert faces.min() >= 0 and faces.max() < nvert
    assert np.isfinite(verts).all()
    lo, hi = _world_bbox(arr == 2, NEG_AFFINE, 0.5 + 1e-3)
    assert (verts >= lo - 1e-4).all() and (verts <= hi + 1e-4).all()
    assert _signed_volume(faces, verts) > 0
    # the sphere volume in mm³ is roughly recovered (r=6 voxels, 0.8·0.8·1.5 mm)
    expected = (arr == 2).sum() * 0.8 * 0.8 * 1.5
    assert abs(_signed_volume(faces, verts) - expected) / expected < 0.15
    # gzip is deterministic (mtime=0): rebuilding gives the same bytes
    dst2 = dst.with_name("again.mz3")
    assert mesh.build(str(src), str(dst2), 2, 0) is None
    assert dst2.read_bytes() == blob


@pytest.mark.parametrize("affine", [POS_AFFINE, NEG_AFFINE], ids=["det+", "det-"])
@pytest.mark.parametrize("smooth", [0, 1])
def test_winding_outward(tmp_path: Path, affine: NDArray[Any], smooth: int) -> None:
    arr = _sphere((24, 24, 24), (12, 11, 12), 7).astype(np.uint8)
    src = _write_nii(tmp_path / "m.nii", arr, affine)  # plain .nii too
    dst = tmp_path / "cache" / "meshes" / "x.mz3"
    assert mesh.build(str(src), str(dst), 1, smooth) is None
    faces, verts = mesh.decode_mz3(dst.read_bytes())
    assert _signed_volume(faces, verts) > 0
    lo, hi = _world_bbox(arr == 1, affine, 0.5 + 2.0 * smooth)
    assert (verts >= lo - 1e-4).all() and (verts <= hi + 1e-4).all()


def test_label_touching_border_is_closed(tmp_path: Path) -> None:
    arr = np.zeros((10, 10, 10), np.uint8)
    arr[:4, :, 3:7] = 1  # touches three faces of the volume
    src = _write_nii(tmp_path / "m.nii.gz", arr, POS_AFFINE)
    dst = tmp_path / "cache" / "b.mz3"
    assert mesh.build(str(src), str(dst), 1, 0) is None
    faces, verts = mesh.decode_mz3(dst.read_bytes())
    # closed manifold: every edge is shared by exactly two faces
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), 1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    assert (counts == 2).all()
    assert _signed_volume(faces, verts) > 0


def test_npy_mask_uses_spacing(tmp_path: Path) -> None:
    arr = _sphere((20, 20, 20), (10, 10, 10), 5).astype(np.uint8) * 3
    src = tmp_path / "m.npy"
    np.save(src, arr)
    dst = tmp_path / "cache" / "n.mz3"
    assert mesh.build(str(src), str(dst), 3, 0, [2.0, 1.0, 0.5]) is None
    _, verts = mesh.decode_mz3(dst.read_bytes())
    ext = verts.max(0) - verts.min(0)
    np.testing.assert_allclose(ext, np.array([2.0, 1.0, 0.5]) * ext[1], rtol=0.1)


def test_label_absent_and_bad_target(tmp_path: Path) -> None:
    arr = _sphere((12, 12, 12), (6, 6, 6), 3).astype(np.uint8)
    src = _write_nii(tmp_path / "m.nii.gz", arr, POS_AFFINE)
    err = mesh.build(str(src), str(tmp_path / "cache" / "a.mz3"), 5, 1)
    assert err is not None and err.startswith(mesh.LABEL_ABSENT)
    assert not (tmp_path / "cache" / "a.mz3").exists()
    err = mesh.build(str(src), str(tmp_path / "elsewhere" / "a.mz3"), 1, 0)
    assert err is not None and "cache/" in err


def test_worker_never_writes_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "data"
    root.mkdir()
    src = _write_nii(root / "m.nii.gz", _sphere((12, 12, 12), (6, 6, 6), 3), POS_AFFINE)
    seen = forbid_source_writes(monkeypatch, root)
    assert mesh.build(str(src), str(tmp_path / "cache" / "m.mz3"), 1, 1) is None
    assert str(src) in seen
    # sanity: the guard would trip on a write
    with pytest.raises(AssertionError):
        src.open("ab")


def test_param_validation() -> None:
    with pytest.raises(ValidationProblem):
        mesh.check_params(1, 2)
    with pytest.raises(ValidationProblem):
        mesh.check_params(0, 1)
    mesh.check_params(1, 0)
    mesh.check_params(7, 1)


def test_build_time_large_mask(tmp_path: Path) -> None:
    """NFR-05: one label, 400x400x200 mask with a ~150x150x120-voxel blob, < 5 s."""
    shape = (400, 400, 200)
    arr = np.zeros(shape, np.uint8)
    c, r = np.array([200.0, 200.0, 100.0]), np.array([75.0, 75.0, 60.0])
    sl = tuple(slice(int(c[k] - r[k]), int(c[k] + r[k]) + 1) for k in range(3))
    g = np.indices(tuple(s.stop - s.start for s in sl), dtype=np.float32)
    d = sum(((g[k] + sl[k].start - c[k]) / r[k]) ** 2 for k in range(3))
    arr[sl][d < 1.0] = 1
    src = _write_nii(tmp_path / "big.nii.gz", arr, POS_AFFINE)
    for smooth in (0, 1):
        dst = tmp_path / "cache" / f"big{smooth}.mz3"
        t0 = time.perf_counter()
        assert mesh.build(str(src), str(dst), 1, smooth) is None
        dt = time.perf_counter() - t0
        print(f"mesh build 400x400x200 smooth={smooth}: {dt:.2f} s, {dst.stat().st_size} B")
        assert dt < 5.0


# --- API process: ensure_mesh ------------------------------------------------------------


def test_ensure_mesh_dedupe_and_cache(tmp_path: Path) -> None:
    arr = _sphere((16, 16, 16), (8, 8, 8), 4).astype(np.uint8)
    src = _write_nii(tmp_path / "m.nii.gz", arr, POS_AFFINE)
    pdir = tmp_path / "proj"

    async def run() -> None:
        jobs = JobManager(EventBus(), workers=1, inline=True)
        await jobs.start()
        try:
            first = mesh.ensure_mesh(jobs, "p", pdir, src, "fpA", 1, 1)
            again = mesh.ensure_mesh(jobs, "p", pdir, src, "fpA", 1, 1)
            assert isinstance(first, JobInfo) and isinstance(again, JobInfo)
            assert first.kind == "mesh" and again.job_id == first.job_id
            other = mesh.ensure_mesh(jobs, "p", pdir, src, "fpA", 1, 0)
            assert isinstance(other, JobInfo) and other.job_id != first.job_id  # not exclusive
            done = await jobs.wait(first.job_id, 30)
            assert done.status == "succeeded" and done.ref == "fpA_1_1"
            await jobs.wait(other.job_id, 30)
            path = mesh.ensure_mesh(jobs, "p", pdir, src, "fpA", 1, 1)
            assert path == mesh.cache_path(pdir, "fpA", 1, 1) and path.is_file()
            mtime = path.stat().st_mtime_ns
            assert mesh.ensure_mesh(jobs, "p", pdir, src, "fpA", 1, 1) == path
            assert path.stat().st_mtime_ns == mtime

            absent = mesh.ensure_mesh(jobs, "p", pdir, src, "fpA", 9, 1)
            assert isinstance(absent, JobInfo)
            failed = await jobs.wait(absent.job_id, 30)
            assert failed.status == "failed"
            assert failed.error is not None and mesh.LABEL_ABSENT in failed.error
            with pytest.raises(NotFound):
                mesh.ensure_mesh(jobs, "p", pdir, src, "fpA", 9, 1)
            with pytest.raises(ValidationProblem):
                mesh.ensure_mesh(jobs, "p", pdir, src, "fpA", 1, 3)
        finally:
            await jobs.shutdown()

    asyncio.run(run())


# --- HTTP (router mounted on a test app, as the integrator will) -------------------------

BASE = "/api/v1/projects/{pid}/items/{iid}/mesh/{label}"
SEG_ITEM = "case_00001.01.complete.-"
NOMASK_ITEM = "case_00002.01.complete.-"
NPY_ITEM = "case_00023.01.voi.L"
GONE_ITEM = "case_00003.01.complete.-"


@dataclass
class Env:
    client: TestClient
    ctx: AppContext
    pid: str
    pdir: Path
    data_root: Path

    def url(self, iid: str, label: int, smooth: int | None = None) -> str:
        u = BASE.format(pid=self.pid, iid=iid, label=label)
        return u if smooth is None else f"{u}?smooth={smooth}"

    def wait(self, job_id: str) -> JobInfo:
        portal = self.client.portal
        assert portal is not None
        info: JobInfo = portal.call(self.ctx.jobs.wait, job_id, 30.0)
        return info


def _item(iid: str, **kw: Any) -> Item:
    case_id, scan_idx, scope, side = iid.split(".")
    return Item(
        item_id=iid,
        case_id=case_id,
        scan_idx=scan_idx,
        scope=scope,  # type: ignore[arg-type]
        side=side,  # type: ignore[arg-type]
        phase=PhaseInfo(canonical="NP"),
        import_id="01JTESTIMPORT0000000000000",
        **kw,
    )


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    fx = tmp_path / "synthetic"
    generate(fx)
    data_root = fx / DATASET
    app = create_app(make_settings(tmp_path, [data_root]), inline_jobs=True)
    app.include_router(mesh_api.router, prefix="/api/v1")
    with TestClient(app) as client:
        ctx: AppContext = client.app.state.ctx  # type: ignore[attr-defined]
        portal = client.portal
        assert portal is not None
        pid = portal.call(ctx.workspace.create, "meshes", "", "CT", ["ccrcc"]).project_id
        portal.call(ctx.workspace.set_root, pid, PathRoot(alias="DATA", path=str(data_root)))
        seg, npy = data_root / SEG, data_root / NPY_MSK
        items = [
            _item(
                SEG_ITEM,
                mask=VolumeRef(ref=f"DATA:{SEG}", fp=quick_fingerprint(seg)),
                labels_present=[1, 2, 3],
            ),
            _item(NOMASK_ITEM),
            _item(GONE_ITEM, mask=VolumeRef(ref="DATA:seg/nope.nii.gz", fp="1-x")),
            _item(NPY_ITEM, mask=VolumeRef(ref=f"DATA:{NPY_MSK}", format="npy")),
        ]
        assert npy.is_file()
        ctx.index.replace(pid, items, [], [])
        yield Env(client, ctx, pid, ctx.workspace.project_dir(pid), data_root)


def test_http_202_200_304(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_source_writes(monkeypatch, env.data_root)
    c = env.client
    fp = quick_fingerprint(env.data_root / SEG)
    url = env.url(SEG_ITEM, 2)  # smooth defaults to 1

    r = c.get(url)
    assert r.status_code == 202
    body = r.json()
    assert body["kind"] == "mesh" and body["status"] in ("queued", "running", "succeeded")
    assert body["project_id"] == env.pid
    assert r.headers["location"] == f"/api/v1/jobs/{body['job_id']}"
    assert c.get(r.headers["location"]).json()["job_id"] == body["job_id"]
    t0 = time.perf_counter()
    assert env.wait(body["job_id"]).status == "succeeded"
    print(f"fixture mesh job (64x64x48, label 2): {time.perf_counter() - t0:.3f} s")

    r = c.get(url)
    assert r.status_code == 200
    etag = f'"{fp}_2_1"'
    assert r.headers["etag"] == etag
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["cache-control"] == "no-cache"
    assert "content-encoding" not in r.headers
    cached = mesh.cache_path(env.pdir, fp, 2, 1)
    assert r.content == cached.read_bytes() and r.content[:2] == b"\x1f\x8b"
    faces, verts = mesh.decode_mz3(r.content)
    assert len(faces) > 0 and np.isfinite(verts).all()

    assert c.get(url, headers={"If-None-Match": etag}).status_code == 304
    assert c.get(url, headers={"If-None-Match": f"W/{etag}"}).status_code == 304
    # smooth=0 is a different cache entry
    r0 = c.get(env.url(SEG_ITEM, 2, 0))
    assert r0.status_code == 202
    env.wait(r0.json()["job_id"])
    r0 = c.get(env.url(SEG_ITEM, 2, 0))
    assert r0.status_code == 200 and r0.headers["etag"] == f'"{fp}_2_0"'


def test_http_npy_mask(env: Env) -> None:
    c = env.client
    r = c.get(env.url(NPY_ITEM, 1, 0))
    assert r.status_code == 202
    assert env.wait(r.json()["job_id"]).status == "succeeded"
    assert c.get(env.url(NPY_ITEM, 1, 0)).status_code == 200


def test_http_errors(env: Env) -> None:
    c = env.client
    r = c.get(env.url(SEG_ITEM, 1, 2))
    assert r.status_code == 422 and r.json()["type"] == "/problems/validation"
    r = c.get(env.url(SEG_ITEM, 0))
    assert r.status_code == 422
    r = c.get(env.url(SEG_ITEM, 7))
    assert r.status_code == 404 and r.json()["type"] == "/problems/not-found"
    r = c.get(env.url(NOMASK_ITEM, 1))
    assert r.status_code == 404 and r.json()["detail"].startswith("item has no mask")
    r = c.get(env.url(GONE_ITEM, 1))
    assert r.status_code == 409 and r.json()["type"] == "/problems/source-missing"
    r = c.get(env.url("case_09999.01.complete.-", 1))
    assert r.status_code == 404
    # no labels_present recorded: the worker decides; absent label → failed job, then 404
    r = c.get(env.url(NPY_ITEM, 9))
    assert r.status_code == 202
    failed = env.wait(r.json()["job_id"])
    assert failed.status == "failed" and mesh.LABEL_ABSENT in (failed.error or "")
    assert c.get(env.url(NPY_ITEM, 9)).status_code == 404
