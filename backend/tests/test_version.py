"""One version source: `backend/pyproject.toml` (image tag, compose default, API-01)."""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.main import app

REPO = Path(__file__).resolve().parents[2]
VERSION: str = tomllib.loads((REPO / "backend" / "pyproject.toml").read_text())["project"][
    "version"
]


def test_version_is_a_valid_docker_tag() -> None:
    assert re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", VERSION)


def test_package_and_health_report_the_pyproject_version() -> None:
    assert __version__ == VERSION  # the image uninstalls the dist, so this is a literal
    assert TestClient(app).get("/api/v1/health").json()["version"] == VERSION


def test_compose_and_env_example_default_to_the_pyproject_version() -> None:
    compose = (REPO / "docker-compose.yml").read_text()
    m = re.search(r"radiology-workbench:\$\{RW_VERSION:-([^}]+)\}", compose)
    assert m is not None and m.group(1) == VERSION
    env = (REPO / ".env.example").read_text()
    assert re.findall(r"^RW_VERSION=(.*)$", env, re.MULTILINE) == [VERSION]


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
def test_makefile_image_tag_reads_pyproject() -> None:
    out = subprocess.run(
        ["make", "-n", "image"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    assert f"radiology-workbench:{VERSION} " in out
