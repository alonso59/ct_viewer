"""Streaming helpers, npy→NIfTI conversion, thumbnails (BE-03, BE-04, IMP-10, IMP-12)."""

from __future__ import annotations

import asyncio
import builtins
import io
import os
import pathlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from app.core.errors import ValidationProblem
from app.imaging import npy_convert, streaming, thumbnails
from app.imaging.fingerprint import quick_fingerprint

CT = "nifti/01_case_00001_0000.nii.gz"
SEG = "seg/01_case_00001.nii.gz"
NPY_IMG = "voi/images/A/NP/01_case_00023_L.npy"
NPY_MSK = "voi/mask/A/NP/01_case_00023_L.npy"
COLORS = {1: (0, 255, 255), 2: (255, 255, 0), 3: (255, 0, 255)}

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def forbid_source_writes(monkeypatch: pytest.MonkeyPatch, root: Path) -> list[str]:
    """Fail any write-mode open of a path under `root` (BE-03, R1); returns seen read paths."""
    real_root = Path(os.path.realpath(root))
    seen: list[str] = []

    def under(p: Any) -> bool:
        if isinstance(p, int):
            return False
        rp = Path(os.path.realpath(os.fspath(p)))
        return rp == real_root or real_root in rp.parents

    def check_mode(p: Any, mode: str) -> None:
        if under(p):
            if any(c in mode for c in "wax+"):
                raise AssertionError(f"write-mode open of source file: {p} ({mode})")
            seen.append(os.fspath(p))

    orig_open = builtins.open
    orig_path_open = pathlib.Path.open
    orig_os_open = os.open

    def g_open(file: Any, mode: str = "r", *a: Any, **k: Any) -> Any:
        check_mode(file, mode)
        return orig_open(file, mode, *a, **k)

    def g_path_open(self: Path, mode: str = "r", *a: Any, **k: Any) -> Any:
        check_mode(self, mode)
        return orig_path_open(self, mode, *a, **k)

    def g_os_open(path: Any, flags: int, *a: Any, **k: Any) -> int:
        if under(path) and flags & _WRITE_FLAGS:
            raise AssertionError(f"write-mode os.open of source file: {path}")
        return orig_os_open(path, flags, *a, **k)

    monkeypatch.setattr(builtins, "open", g_open)
    monkeypatch.setattr(io, "open", g_open)
    monkeypatch.setattr(pathlib.Path, "open", g_path_open)
    monkeypatch.setattr(os, "open", g_os_open)
    return seen


@pytest.fixture
def guarded(monkeypatch: pytest.MonkeyPatch, data_root: Path) -> list[str]:
    return forbid_source_writes(monkeypatch, data_root)


def test_write_guard_trips(guarded: list[str], data_root: Path) -> None:
    with pytest.raises(AssertionError):
        (data_root / "x.txt").open("w")
    with pytest.raises(AssertionError):
        os.open(data_root / "y.txt", os.O_WRONLY | os.O_CREAT)


# --- streaming (BE-04) ---------------------------------------------------------------


def _stream_app(path: Path, name: str) -> Starlette:
    fp = quick_fingerprint(path)

    async def vol(request: Request) -> Response:
        return streaming.volume_response(path, fp, name, request)

    return Starlette(routes=[Route("/v", vol, methods=["GET", "HEAD"])])


def test_etag_matches() -> None:
    assert streaming.etag_matches('"a", W/"b"', '"b"')
    assert streaming.etag_matches("*", '"x"')
    assert not streaming.etag_matches('"a"', '"b"')
    assert not streaming.etag_matches(None, '"b"')


def test_volume_response_full_range_304(guarded: list[str], data_root: Path) -> None:
    path = data_root / CT
    raw = path.read_bytes()
    fp = quick_fingerprint(path)
    with TestClient(_stream_app(path, path.name)) as c:
        r = c.get("/v")
        assert r.status_code == 200
        assert r.content == raw
        assert r.headers["etag"] == f'"{fp}"'
        assert r.headers["cache-control"] == "no-cache"
        assert r.headers["accept-ranges"] == "bytes"
        assert r.headers["content-type"] == "application/octet-stream"
        assert r.headers["content-disposition"] == f'inline; filename="{path.name}"'
        assert r.headers["x-volume-name"] == path.name

        r = c.get("/v", headers={"Range": "bytes=0-99"})
        assert r.status_code == 206
        assert r.content == raw[:100]
        assert r.headers["content-range"] == f"bytes 0-99/{len(raw)}"

        r = c.get("/v", headers={"If-None-Match": f'"{fp}"'})
        assert r.status_code == 304
        assert r.headers["etag"] == f'"{fp}"'

        r = c.head("/v")
        assert r.status_code == 200
        assert int(r.headers["content-length"]) == len(raw)
    assert guarded  # the source was actually read through the guard


# --- npy → NIfTI (IMP-10) -------------------------------------------------------------


def test_convert_npy(guarded: list[str], data_root: Path, tmp_path: Path) -> None:
    src = data_root / NPY_IMG
    dst = tmp_path / "proj" / "cache" / "npy" / "fp.nii.gz"
    assert npy_convert.convert(str(src), str(dst), [0.8, 0.8, 1.5]) is None
    img: Any = nib.load(dst)
    np.testing.assert_array_equal(np.asarray(img.dataobj), np.load(src))
    np.testing.assert_allclose(img.affine, np.diag([0.8, 0.8, 1.5, 1.0]))
    assert int(img.header["sform_code"]) == 1
    assert not [p for p in dst.parent.iterdir() if p.name.endswith(".tmp")]


def test_convert_refuses_outside_cache(data_root: Path, tmp_path: Path) -> None:
    err = npy_convert.convert(str(data_root / NPY_IMG), str(tmp_path / "x.nii.gz"), [1, 1, 1])
    assert err is not None and "cache" in err


def test_convert_bad_npy(tmp_path: Path) -> None:
    bad = tmp_path / "bad.npy"
    bad.write_bytes(b"not an npy")
    err = npy_convert.convert(str(bad), str(tmp_path / "cache" / "o.nii.gz"), [1, 1, 1])
    assert err is not None
    two_d = tmp_path / "2d.npy"
    np.save(two_d, np.zeros((4, 4)))
    err = npy_convert.convert(str(two_d), str(tmp_path / "cache" / "p.nii.gz"), [1])
    assert err is not None and "3D" in err


def test_nifti_name() -> None:
    assert npy_convert.nifti_name("01_case_00023_L.npy") == "01_case_00023_L.nii.gz"


class _Runner:
    def __init__(self) -> None:
        self.calls = 0

    async def run_in_worker(self, fn: Callable[..., Any], *args: Any) -> Any:
        self.calls += 1
        await asyncio.sleep(0.05)
        return await asyncio.to_thread(fn, *args)


def test_ensure_nifti_dedupes(guarded: list[str], data_root: Path, tmp_path: Path) -> None:
    src = data_root / NPY_MSK
    dst = npy_convert.cache_path(tmp_path / "proj", quick_fingerprint(src))
    runner = _Runner()

    async def go() -> list[Path]:
        return list(
            await asyncio.gather(
                *(npy_convert.ensure_nifti(runner, src, dst, [0.8, 0.8, 1.5]) for _ in range(5))
            )
        )

    assert asyncio.run(go()) == [dst] * 5
    assert runner.calls == 1
    assert asyncio.run(go()) == [dst] * 5  # cached: no new conversion
    assert runner.calls == 1


def test_ensure_nifti_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.npy"
    bad.write_bytes(b"junk")
    dst = tmp_path / "cache" / "npy" / "x.nii.gz"
    with pytest.raises(ValidationProblem):
        asyncio.run(npy_convert.ensure_nifti(_Runner(), bad, dst, [1, 1, 1]))


# --- thumbnails (IMP-12) --------------------------------------------------------------


def _thumb(tmp_path: Path, name: str = "t.webp") -> Path:
    return tmp_path / "proj" / "cache" / "thumbs" / name


def test_render_fixture(guarded: list[str], data_root: Path, tmp_path: Path) -> None:
    out = _thumb(tmp_path)
    err = thumbnails.render(str(data_root / CT), str(data_root / SEG), str(out), 400, 50, COLORS)
    assert err is None
    with Image.open(out) as im:
        assert im.format == "WEBP"
        # 64x64 in-plane at 0.8 mm: square → 128x128
        assert im.size == (128, 128)
        px = np.asarray(im.convert("RGB")).reshape(-1, 3).astype(int)
    cyan = (px == (0, 255, 255)).all(axis=1)  # lossless: exact label colours
    yellow = (px == (255, 255, 0)).all(axis=1)
    assert cyan.sum() > 10
    assert yellow.sum() > 5
    assert not [p for p in out.parent.iterdir() if p.name.endswith(".tmp")]


def test_render_without_mask_is_gray(data_root: Path, tmp_path: Path) -> None:
    out = _thumb(tmp_path)
    assert thumbnails.render(str(data_root / CT), None, str(out), 400, 50, COLORS) is None
    with Image.open(out) as im:
        px = np.asarray(im.convert("RGB")).astype(int)
    assert np.abs(px[..., 0] - px[..., 1]).max() < 16


def _marker_volume(affine: np.ndarray[Any, Any], path: Path) -> None:
    """Bright block at patient right (RAS+ x > 0) and anterior (y > 0) on the mid slice."""
    data = np.zeros((20, 30, 9), dtype=np.int16)
    inv = np.linalg.inv(affine)
    for wx in np.linspace(6.0, 9.0, 4):
        for wy in np.linspace(9.0, 13.0, 5):
            ijk = np.rint(inv @ np.array([wx, wy, 0.0, 1.0]))[:3].astype(int)
            data[tuple(ijk)] = 1000
    img = nib.Nifti1Image(data, affine)
    img.header.set_sform(affine, code=1)
    nib.save(img, path)


@pytest.mark.parametrize("lps", [False, True])
def test_render_orientation(tmp_path: Path, lps: bool) -> None:
    # 20 x 30 x 9 voxels of 1 x 1 x 2 mm centred on the origin; LPS stores x/y flipped.
    sign = -1.0 if lps else 1.0
    aff = np.diag([sign, sign, 2.0, 1.0])
    aff[:3, 3] = [-9.5 * sign, -14.5 * sign, -8.0]
    src = tmp_path / "m.nii.gz"
    _marker_volume(aff, src)
    out = _thumb(tmp_path)
    assert thumbnails.render(str(src), None, str(out), 400, 50, {}) is None
    with Image.open(out) as im:
        w, h = im.size
        g = np.asarray(im.convert("L")).astype(float)
    assert (w, h) == (85, 128)  # 20 mm x 30 mm, longest side 128 px
    ys, xs = np.nonzero(g > 128)
    assert xs.mean() < w / 2  # patient right on image left (radiological)
    assert ys.mean() < h / 2  # anterior up


def test_render_bad_input_returns_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.nii.gz"
    bad.write_bytes(b"nope")
    err = thumbnails.render(str(bad), None, str(_thumb(tmp_path)), 400, 50, {})
    assert isinstance(err, str)


def test_render_batch_and_hex() -> None:
    assert thumbnails.hex_to_rgb("#00FFff") == (0, 255, 255)
    assert thumbnails.render_batch([]) == []
