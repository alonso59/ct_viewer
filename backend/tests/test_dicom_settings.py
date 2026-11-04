"""DCM-27: one settings schema for ct_viewer, the CLI and the Python API."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from rw_dicom import pipeline
from rw_dicom.settings import conversion_settings, task_manifest

from tools import gen_dicom_schema

MANIFEST = Path(__file__).parents[2] / "plugins" / "dicom" / "task.json"


def test_packaged_schema_equals_the_task_manifest() -> None:
    """DCM-27: drift check; `make gen-dicom-schema` regenerates the package copy."""
    assert gen_dicom_schema.main(["--check"]) == 0
    manifest = json.loads(MANIFEST.read_text())
    assert task_manifest()["settings_schema"] == manifest["settings_schema"]


def test_runtime_settings_cover_the_schema_with_its_defaults() -> None:
    """DCM-27: every conversion setting exists at runtime with the schema's default."""
    properties = task_manifest()["settings_schema"]["properties"]
    fields = {f.name: f for f in dataclasses.fields(pipeline.Settings)}
    assert set(properties) - set(fields) == {"phase_analyzer"}  # read by the task, not the pipeline
    assert set(fields) <= set(properties)
    for name, spec in properties.items():
        if name in fields and "default" in spec:
            assert fields[name].default == spec["default"], name


def test_conversion_settings_refuse_unknown_keys_and_hash_like_the_app() -> None:
    """DCM-27: unknown keys are refused; equal settings give equal hashes."""
    with pytest.raises(ValueError, match="sidecar: Unknown setting"):
        conversion_settings({"sidecar": False})
    first, digest = conversion_settings({"anonymize": "basic"})
    again, same = conversion_settings({"anonymize": "basic", "sidecars": True})
    assert first == again and digest == same and first["sidecars"] is True
