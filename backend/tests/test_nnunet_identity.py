"""SEG-14: pin full content, rather than trusting quick file metadata or mutable settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest


def inputs(tmp_path: Path) -> list[dict[str, Any]]:
    image = tmp_path / "image.nii.gz"
    image.write_bytes(b"synthetic-input")
    return [{"item_id": "one", "image": {"path": str(image), "format": "nifti"}}]


def test_pinned_inputs_detect_content_drift_with_unchanged_size_and_mtime(tmp_path: Path) -> None:
    from plugins.runner.identity import freeze, verify_inputs

    items = inputs(tmp_path)
    pin = freeze(
        "sha256:manifest",
        {"id": "ct", "profile_sha256": "sha256:profile", "artifacts_sha256": "model"},
        items,
    )
    verify_inputs(pin, items)
    path = Path(items[0]["image"]["path"])
    before = path.stat()
    path.write_bytes(b"changed---input")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError, match=r"input.*changed"):
        verify_inputs(pin, items)


@pytest.mark.parametrize("field", ["id", "profile_sha256", "artifacts_sha256"])
def test_profile_replacement_requires_a_new_run(tmp_path: Path, field: str) -> None:
    from plugins.runner.identity import freeze, verify_profile

    profile = {"id": "ct", "profile_sha256": "sha256:profile", "artifacts_sha256": "model"}
    pin = freeze("sha256:manifest", profile, inputs(tmp_path))
    verify_profile(pin, profile)
    with pytest.raises(ValueError, match=r"profile.*changed"):
        verify_profile(pin, {**profile, field: "replacement"})


def test_missing_or_duplicated_inputs_cannot_reuse_an_identity(tmp_path: Path) -> None:
    from plugins.runner.identity import freeze, verify_inputs

    items = inputs(tmp_path)
    pin = freeze(
        "manifest", {"id": "ct", "profile_sha256": "profile", "artifacts_sha256": "model"}, items
    )
    with pytest.raises(ValueError, match="input"):
        verify_inputs(pin, [])
    with pytest.raises(ValueError, match="input"):
        verify_inputs(pin, items * 2)


def test_committed_outputs_are_verified_before_reusing_them(tmp_path: Path) -> None:
    from plugins.runner.identity import content_hash, verify_files

    path = tmp_path / "registered.nii.gz"
    path.write_bytes(b"complete-output")
    files = {str(path): content_hash(path)}
    verify_files(files)
    path.write_bytes(b"modified-output")
    with pytest.raises(ValueError, match=r"output.*changed"):
        verify_files(files)
