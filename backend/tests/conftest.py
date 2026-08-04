from __future__ import annotations

import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def _restrict_data_access_to_each_test(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep test fixtures inside the same path policy used in production."""

    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("ALLOWED_DATA_ROOTS", raising=False)
    monkeypatch.delenv("ALLOW_UNRESTRICTED_DATA_PATHS", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("RADIOLOGY_DESKTOP_RUNTIME", raising=False)
