"""TSK-14: a model result never certifies supervised GPU cleanup."""

import json
from pathlib import Path

from app.tasks.protocol import external_finished


def test_supervised_result_waits_for_verified_boundary_cleanup(tmp_path: Path) -> None:
    (tmp_path / "attempt.json").write_text(json.dumps({"attempt": "a"}))
    (tmp_path / "result.json").write_text("{}")
    assert external_finished(tmp_path) is False
    (tmp_path / "exit.json").write_text(
        json.dumps({"attempt": "a", "code": 0, "cleanup_verified": False})
    )
    assert external_finished(tmp_path) is False
    (tmp_path / "exit.json").write_text(
        json.dumps({"attempt": "a", "code": 0, "cleanup_verified": True})
    )
    assert external_finished(tmp_path) is True


def test_old_generation_cannot_complete_new_attempt(tmp_path: Path) -> None:
    (tmp_path / "attempt.json").write_text(json.dumps({"attempt": "new"}))
    (tmp_path / "exit.json").write_text(
        json.dumps({"attempt": "old", "code": 0, "cleanup_verified": True})
    )
    assert external_finished(tmp_path) is False


def test_legacy_cpu_completion_remains_compatible(tmp_path: Path) -> None:
    (tmp_path / "result.json").write_text("{}")
    assert external_finished(tmp_path) is True
