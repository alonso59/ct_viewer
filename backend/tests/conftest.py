"""Shared fixtures. Synthetic data: `make fixtures` → .fixtures/synthetic (TST-11)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tools.make_fixtures import DATASET, generate

REPO = Path(__file__).resolve().parents[2]
SYNTHETIC = REPO / ".fixtures" / "synthetic"


@pytest.fixture(scope="session")
def fixtures_src(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Pristine generated fixtures (session-scoped; never mutate: copy with `fixtures_copy`)."""
    out = tmp_path_factory.mktemp("fx") / "synthetic"
    generate(out)
    return out


@pytest.fixture
def fixtures_copy(fixtures_src: Path, tmp_path: Path) -> Path:
    """A per-test mutable copy of the synthetic fixtures; data root is `<copy>/Dataset900`."""
    dst = tmp_path / "synthetic"
    shutil.copytree(fixtures_src, dst)
    return dst


@pytest.fixture
def data_root(fixtures_copy: Path) -> Path:
    return fixtures_copy / DATASET


def make_settings(tmp_path: Path, allowed: list[Path] | None = None) -> Settings:
    return Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=":".join(str(p.resolve()) for p in (allowed or [])),
        job_workers=2,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def settings(tmp_path: Path, fixtures_copy: Path) -> Settings:
    """Workspace in tmp; ALLOWED_DATA_ROOTS = the fixture data root only (so `outside/` is out)."""
    return make_settings(tmp_path, [fixtures_copy / DATASET])


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings, inline_jobs=True)
    with TestClient(app) as c:
        yield c
