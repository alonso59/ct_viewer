"""TST-01: core primitives — path guards (BE-02), fsio, errors (BE-08), locks (BE-05)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import fsio
from app.core.errors import NotFound, PathOutsideRoot, ValidationProblem, install_handlers
from app.core.ids import item_id, new_ulid, parse_item_id, utc_now
from app.core.locks import FileLock, LockHeldError
from app.core.paths import PathGuard, PathResolver, make_ref, parse_ref
from app.imaging.fingerprint import quick_fingerprint
from app.imaging.header import HeaderError, compare_geometry, read_header


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, Path]:
    allowed = tmp_path / "allowed"
    root = allowed / "data"
    (root / "sub").mkdir(parents=True)
    (root / "sub/a.nii.gz").write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.nii.gz").write_bytes(b"s")
    return allowed, root


@pytest.mark.parametrize("ref", ["DATA:sub/a.nii.gz", "D1_X:a", "A:x/y/z.npy"])
def test_parse_ref_accepts(ref: str) -> None:
    assert str(parse_ref(ref)) == ref


@pytest.mark.parametrize(
    "ref",
    [
        "data:a",
        "DATA",
        "DATA:",
        "DATA:/abs",
        "DATA:../x",
        "DATA:a/../b",
        "DATA:a//b",
        "DATA:./a",
        "DATA:a\\b",
        "1ABC:a",
        "ABCDEFGHIJKLMNOPQ:a",
    ],
)
def test_parse_ref_rejects(ref: str) -> None:
    with pytest.raises(ValidationProblem):
        parse_ref(ref)


def test_resolve_inside_root(tree: tuple[Path, Path]) -> None:
    allowed, root = tree
    r = PathResolver({"DATA": root}, PathGuard([allowed]))
    assert r.resolve("DATA:sub/a.nii.gz") == (root / "sub/a.nii.gz").resolve()


def test_symlink_escape_is_rejected(tree: tuple[Path, Path], tmp_path: Path) -> None:
    allowed, root = tree
    os.symlink(tmp_path / "outside/secret.nii.gz", root / "sub/link.nii.gz")
    r = PathResolver({"DATA": root}, PathGuard([allowed]))
    with pytest.raises(PathOutsideRoot):
        r.resolve("DATA:sub/link.nii.gz")


def test_root_outside_allowed_is_rejected(tree: tuple[Path, Path], tmp_path: Path) -> None:
    allowed, _ = tree
    r = PathResolver({"OUT": tmp_path / "outside"}, PathGuard([allowed]))
    with pytest.raises(PathOutsideRoot):
        r.resolve("OUT:secret.nii.gz")


def test_unrestricted_guard_allows_anything(tmp_path: Path) -> None:
    g = PathGuard([])
    assert not g.restricted and g.is_allowed(tmp_path)


def test_unknown_alias(tree: tuple[Path, Path]) -> None:
    allowed, root = tree
    with pytest.raises(NotFound):
        PathResolver({"DATA": root}, PathGuard([allowed])).resolve("OTHER:a")


def test_to_ref(tree: tuple[Path, Path]) -> None:
    allowed, root = tree
    r = PathResolver({"DATA": root}, PathGuard([allowed]))
    assert r.to_ref("DATA", "./sub//a.nii.gz") == "DATA:sub/a.nii.gz"
    assert r.to_ref("DATA", str(root / "sub/a.nii.gz")) == "DATA:sub/a.nii.gz"
    for bad in ("../outside/x", "sub/../../x", "/etc/passwd", ".."):
        with pytest.raises(PathOutsideRoot):
            r.to_ref("DATA", bad)
    assert make_ref("DATA", "a/b") == "DATA:a/b"


def test_item_id_roundtrip() -> None:
    iid = item_id("case_00001", "01", "voi", "L")
    assert iid == "case_00001.01.voi.L"
    assert parse_item_id(iid) == ("case_00001", "01", "voi", "L")
    assert parse_item_id("P-7_b.01.voi.L") == ("P-7_b", "01", "voi", "L")  # slug ids (SRC-08)
    assert parse_item_id("case 1.01.voi.L") is None
    assert len(new_ulid()) == 26 and utc_now().endswith("Z")


def test_atomic_json_and_backup(tmp_path: Path) -> None:
    p = tmp_path / "d/project.json"
    fsio.atomic_write_json(p, {"v": 1}, backup=True)
    fsio.atomic_write_json(p, {"v": 2}, backup=True)
    assert fsio.read_json(p) == {"v": 2}
    assert fsio.read_json(p.with_name("project.json.bak")) == {"v": 1}
    assert not [f for f in p.parent.iterdir() if f.name.endswith(".tmp")]


def test_jsonl_append_and_iter(tmp_path: Path) -> None:
    p = tmp_path / "e.jsonl"
    fsio.append_jsonl(p, [{"a": 1}])
    fsio.append_jsonl(p, [{"a": 2}, {"a": "é"}])
    assert p.read_bytes().endswith(b"\n")
    assert fsio.read_jsonl(p) == [{"a": 1}, {"a": 2}, {"a": "é"}]
    assert fsio.read_jsonl(tmp_path / "missing.jsonl") == []


def test_problem_json_handlers() -> None:
    app = FastAPI()
    install_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise PathOutsideRoot("nope")

    @app.get("/typed/{n}")
    def typed(n: int) -> int:
        return n

    c = TestClient(app)
    r = c.get("/boom")
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == "/problems/path-outside-root"
    r = c.get("/typed/x")
    assert r.status_code == 422 and r.json()["type"] == "/problems/validation"
    assert r.json()["errors"][0]["loc"] == ["path", "n"]
    r = c.get("/nothing")
    assert r.status_code == 404 and r.json()["type"] == "/problems/not-found"


def test_file_lock_is_exclusive(tmp_path: Path) -> None:
    a, b = FileLock(tmp_path / ".server.lock"), FileLock(tmp_path / ".server.lock")
    a.acquire()
    with pytest.raises(LockHeldError):
        b.acquire()
    a.release()
    b.acquire()
    b.release()


def test_quick_fingerprint(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(os.urandom(200_000))
    fp = quick_fingerprint(p)
    assert fp.startswith("200000-") and fp == quick_fingerprint(p)
    data = bytearray(p.read_bytes())
    data[-1] ^= 0xFF
    p.write_bytes(bytes(data))
    assert quick_fingerprint(p) != fp


def test_header_reader_on_fixtures(fixtures_src: Path) -> None:
    root = fixtures_src / "Dataset900"
    img = read_header(root / "nifti/01_case_00001_0000.nii.gz")
    assert img.shape == (64, 64, 48) and img.dtype == "int16" and img.orientation == "RAS"
    assert img.spacing == pytest.approx((0.8, 0.8, 1.5))
    assert read_header(root / "nifti/01_case_00015_0000.nii.gz").affine is None
    with pytest.raises(HeaderError):
        read_header(root / "nifti/01_case_00011_0000.nii.gz")
    shifted = read_header(root / "seg/01_case_00016.nii.gz")
    assert compare_geometry(read_header(root / "nifti/01_case_00016_0000.nii.gz"), shifted) == [
        "affine"
    ]
    short = read_header(root / "seg/01_case_00017.nii.gz")
    assert compare_geometry(img, short) == ["shape"]
    npy = read_header(root / "voi/images/A/NP/01_case_00023_L.npy", spacing=(0.8, 0.8, 1.5))
    assert npy.format == "npy" and npy.shape == (32, 32, 32) and npy.affine is None
