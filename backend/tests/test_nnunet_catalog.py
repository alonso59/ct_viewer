"""SEG-02/03/06: independently validated profiles, class/region labels and safe roots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from plugins.nnunet.configure import refresh
from plugins.nnunet.profile import _derived_labels, load_profile

from tests.test_nnunet import DATASET_ID, PROFILE_ID, make_model


def model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    results, profiles = make_model(tmp_path)
    monkeypatch.setenv("nnUNet_results", str(results))
    monkeypatch.setenv("RW_NNUNET_PROFILES_DIR", str(profiles))
    return results, profiles


def test_integer_class_model_does_not_require_region_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results, profiles = model(tmp_path, monkeypatch)
    dataset = {"channel_names": {"0": "CT"}, "labels": {"background": 0, "liver": 1, "lesion": 2}}
    for path in (results / DATASET_ID).rglob("dataset.json"):
        path.write_text(json.dumps(dataset))
    profile_path = profiles / f"{PROFILE_ID}.json"
    raw = json.loads(profile_path.read_text())
    raw["labels"] = {"1": "liver", "2": "lesion"}
    raw.pop("regions_class_order")
    profile_path.write_text(json.dumps(raw))
    refresh(profile_path, results)
    profile = load_profile(PROFILE_ID)
    assert profile.labels == {"1": "liver", "2": "lesion"}
    assert profile.regions_class_order == ()


@pytest.mark.parametrize(
    "dataset",
    [
        {"labels": {"background": True, "organ": 1}},
        {"labels": {"background": 0, "organ": True}},
        {"labels": {"background": 0, "organ": 1, "duplicate": 1}},
        {"labels": {"background": 0, "organ": -1}},
        {"labels": {"background": 0, "organ": 1.5}},
        {"labels": {"background": 0, "organ": [1, 2]}, "regions_class_order": [True]},
        {"labels": {"background": 0, "organ": [1, 2], "lesion": 2}, "regions_class_order": [1, 1]},
        {"labels": {"background": 0, "organ": [1, 2]}, "regions_class_order": [9]},
    ],
)
def test_ambiguous_labels_fail_closed(dataset: dict[str, Any]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _derived_labels(dataset)


def test_model_dataset_symlink_cannot_escape_results_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results, _ = model(tmp_path, monkeypatch)
    dataset = results / DATASET_ID
    outside = tmp_path / "outside-model"
    dataset.rename(outside)
    dataset.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match=r"escape|root"):
        load_profile(PROFILE_ID)


def test_catalog_isolates_invalid_siblings_and_has_a_stable_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.nnunet.catalog import catalog

    _, profiles = model(tmp_path, monkeypatch)
    (profiles / "broken.json").write_text('{"profile":')
    first = catalog()
    assert first == catalog()
    rows = {entry["id"]: entry for entry in first["profiles"]}
    assert rows[PROFILE_ID]["available"] is True
    assert rows["broken"]["available"] is False
    assert rows["broken"]["reason"]
    assert rows[PROFILE_ID]["labels"] == {"1": "kidney", "3": "masses", "2": "tumor"}
    (profiles / "broken.json").write_text("{}")
    assert catalog()["generation"] != first["generation"]
