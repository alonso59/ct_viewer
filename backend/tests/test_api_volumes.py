"""API-23/24/26 over HTTP: bytes, Range, ETag/304, npy cache, thumbnails (BE-03/04, IMP-10/12)."""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.context import AppContext
from app.imaging import npy_convert, thumbnails
from app.imaging.fingerprint import quick_fingerprint
from app.imaging.header import VolumeFormat
from app.ingest.models import Geometry, Item, PhaseInfo, VolumeRef
from app.jobs.manager import JobManager
from app.projects.models import PathRoot
from app.projects.service import Workspace
from tests.test_imaging import CT, NPY_IMG, NPY_MSK, SEG, forbid_source_writes


def _skeleton() -> bool:
    fns: list[Any] = [
        Workspace.open,
        Workspace.get,
        Workspace.create,
        Workspace.set_root,
        Workspace.resolver,
        Workspace.project_dir,
        JobManager.start,
        JobManager.submit,
        JobManager.wait,
        JobManager.active,
        JobManager.run_in_worker,
    ]
    return any("raise NotImplementedError" in inspect.getsource(f) for f in fns)


pytestmark = pytest.mark.skipif(
    _skeleton(), reason="Workspace (sub-agent A) / JobManager (sub-agent D) not implemented yet"
)

BASE = "/api/v1/projects/{pid}/items/{iid}"
CT_ITEM = "case_00001.01.complete.-"
NOMASK_ITEM = "case_00002.01.complete.-"
MISSING_ITEM = "case_00003.01.complete.-"
OUTSIDE_ITEM = "case_00004.01.complete.-"
NPY_ITEM = "case_00023.01.voi.L"


@dataclass
class Env:
    client: TestClient
    ctx: AppContext
    pid: str
    pdir: Path
    data_root: Path

    def url(self, iid: str, what: str) -> str:
        return BASE.format(pid=self.pid, iid=iid) + f"/{what}"


def _vol(root: Path, rel: str, fmt: VolumeFormat = "nifti") -> VolumeRef:
    p = root / rel
    return VolumeRef(
        ref=f"DATA:{rel}", format=fmt, fp=quick_fingerprint(p) if p.is_file() else None
    )


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
def env(client: TestClient, data_root: Path, fixtures_copy: Path) -> Env:
    ctx: AppContext = client.app.state.ctx  # type: ignore[attr-defined]
    portal = client.portal
    assert portal is not None
    cfg = portal.call(ctx.workspace.create, "volumes")
    pid = cfg.project_id
    portal.call(ctx.workspace.set_root, pid, PathRoot(alias="DATA", path=str(data_root)))
    # symlink inside the root pointing outside ALLOWED_DATA_ROOTS (test copy only)
    link = data_root / "nifti" / "escape.nii.gz"
    os.symlink(fixtures_copy / "outside" / "01_case_00012_0000.nii.gz", link)
    geo = Geometry(shape=[32, 32, 32], spacing=[0.8, 0.8, 1.5], dtype="int16")
    items = [
        _item(CT_ITEM, image=_vol(data_root, CT), mask=_vol(data_root, SEG)),
        _item(NOMASK_ITEM, image=_vol(data_root, "nifti/01_case_00002_0000.nii.gz")),
        _item(MISSING_ITEM, image=_vol(data_root, "nifti/nope.nii.gz")),
        _item(OUTSIDE_ITEM, image=VolumeRef(ref="DATA:nifti/escape.nii.gz", fp="1-x")),
        _item(
            NPY_ITEM,
            image=_vol(data_root, NPY_IMG, "npy"),
            mask=_vol(data_root, NPY_MSK, "npy"),
            geometry=geo,
        ),
    ]
    ctx.index.replace(pid, items, [], [])
    return Env(client, ctx, pid, ctx.workspace.project_dir(pid), data_root)


def test_image_bytes_range_etag(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_source_writes(monkeypatch, env.data_root)
    c, url = env.client, env.url(CT_ITEM, "image")
    raw = (env.data_root / CT).read_bytes()
    etag = f'"{quick_fingerprint(env.data_root / CT)}"'

    r = c.get(url)
    assert r.status_code == 200
    assert r.content == raw
    assert r.headers["etag"] == etag
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["x-volume-name"] == "01_case_00001_0000.nii.gz"
    assert r.headers["content-disposition"] == 'inline; filename="01_case_00001_0000.nii.gz"'

    r = c.get(url, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100 and r.content == raw[:100]
    assert r.headers["content-range"] == f"bytes 0-99/{len(raw)}"

    r = c.get(url, headers={"If-None-Match": etag})
    assert r.status_code == 304

    r = c.head(url)
    assert r.status_code == 200
    assert r.headers["etag"] == etag

    r = c.get(env.url(CT_ITEM, "mask"))
    assert r.status_code == 200
    assert r.content == (env.data_root / SEG).read_bytes()
    assert r.headers["x-volume-name"] == "01_case_00001.nii.gz"


def test_errors(env: Env) -> None:
    c = env.client
    r = c.get(env.url(NOMASK_ITEM, "mask"))
    assert r.status_code == 404
    assert r.json()["type"] == "/problems/not-found"
    assert r.json()["detail"] == "item has no mask"

    r = c.get(env.url("case_09999.01.complete.-", "image"))
    assert r.status_code == 404

    r = c.get(env.url(MISSING_ITEM, "image"))
    assert r.status_code == 409
    assert r.json()["type"] == "/problems/source-missing"

    r = c.get(env.url(OUTSIDE_ITEM, "image"))
    assert r.status_code == 403
    assert r.json()["type"] == "/problems/path-outside-root"


def test_npy_converted_and_cached(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_source_writes(monkeypatch, env.data_root)
    c = env.client
    fp = quick_fingerprint(env.data_root / NPY_IMG)
    r = c.get(env.url(NPY_ITEM, "image"))
    assert r.status_code == 200
    assert r.headers["etag"] == f'"{fp}"'
    assert r.headers["x-volume-name"] == "01_case_00023_L.nii.gz"
    cached = npy_convert.cache_path(env.pdir, fp)
    assert cached.is_file()
    assert r.content == cached.read_bytes()
    img: Any = nib.load(cached)
    np.testing.assert_array_equal(np.asarray(img.dataobj), np.load(env.data_root / NPY_IMG))
    np.testing.assert_allclose(np.diag(img.affine)[:3], [0.8, 0.8, 1.5])

    mtime = cached.stat().st_mtime_ns
    assert c.get(env.url(NPY_ITEM, "image")).status_code == 200
    assert cached.stat().st_mtime_ns == mtime  # reused, not reconverted
    r = c.get(env.url(NPY_ITEM, "image"), headers={"If-None-Match": f'"{fp}"'})
    assert r.status_code == 304

    r = c.get(env.url(NPY_ITEM, "mask"), headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100


def test_thumbnails(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_source_writes(monkeypatch, env.data_root)
    c, ctx = env.client, env.ctx
    url = env.url(CT_ITEM, "thumbnail")
    r = c.get(url)
    assert r.status_code == 404
    assert r.json()["detail"] == "thumbnail not generated"

    portal = c.portal
    assert portal is not None

    async def schedule() -> Any:
        return await thumbnails.schedule_thumbnails(ctx.workspace, ctx.index, ctx.jobs, env.pid)

    job = portal.call(schedule)
    assert job is not None and job.kind == "thumbnail"
    done = portal.call(ctx.jobs.wait, job.job_id, 30.0)
    assert done.status == "succeeded"

    fp = quick_fingerprint(env.data_root / CT)
    assert thumbnails.thumb_path(env.pdir, fp).is_file()
    r = c.get(url)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    assert r.headers["etag"] == f'"{fp}"'
    assert r.content[:4] == b"RIFF" and r.content[8:12] == b"WEBP"
    assert c.get(url, headers={"If-None-Match": f'"{fp}"'}).status_code == 304
    assert c.get(env.url(NOMASK_ITEM, "thumbnail")).status_code == 200
    # voi items never get thumbnails
    assert c.get(env.url(NPY_ITEM, "thumbnail")).status_code == 404
    # nothing left to do
    assert portal.call(schedule) is None
