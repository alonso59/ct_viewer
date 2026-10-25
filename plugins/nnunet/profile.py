"""Strict, path-safe nnU-Net model profiles."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROFILE_KEYS = {
    "profile",
    "id",
    "title",
    "dataset",
    "channels",
    "labels",
    "regions_class_order",
    "predictors",
    "postprocessing",
    "processes",
    "artifacts",
    "artifacts_sha256",
}
PROFILES_DIR = Path(__file__).with_name("profiles")


@dataclass(frozen=True)
class Predictor:
    configuration: str
    trainer: str
    plans: str
    folds: tuple[int, ...]
    checkpoint: str

    @property
    def folder(self) -> str:
        return f"{self.trainer}__{self.plans}__{self.configuration}"


@dataclass(frozen=True)
class Postprocessing:
    pickle: str
    plans: str
    dataset: str


@dataclass(frozen=True)
class Profile:
    id: str
    title: str
    dataset: str
    channels: dict[str, str]
    labels: dict[str, str]
    regions_class_order: tuple[int, ...]
    predictors: tuple[Predictor, ...]
    postprocessing: Postprocessing | None
    preprocessing_per_gpu: int
    export_per_gpu: int
    artifacts: tuple[tuple[str, str], ...]
    artifacts_sha256: str
    profile_sha256: str
    results_root: Path

    def artifact(self, relative: str) -> Path:
        return _inside(self.results_root / self.dataset, relative)


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def _inside(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe model artifact path: {relative!r}")
    path = (root / rel).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"model artifact escapes its dataset root: {relative!r}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _derived_labels(dataset_json: dict[str, Any]) -> tuple[dict[str, str], tuple[int, ...]]:
    raw_labels = _object(dataset_json.get("labels"), "dataset.json labels")
    if type(raw_labels.get("background")) is not int or raw_labels["background"] != 0:
        raise ValueError("dataset.json background must be integer zero")
    foreground = {name: value for name, value in raw_labels.items() if name not in {"background", "ignore"}}
    if not foreground:
        raise ValueError("dataset.json has no foreground labels")
    for name, value in foreground.items():
        values = value if isinstance(value, list) else [value]
        if not name or not values or any(type(number) is not int or number <= 0 for number in values):
            raise ValueError("dataset.json labels must contain positive integers")
    if not any(isinstance(value, list) and len(value) > 1 for value in foreground.values()):
        if any(type(value) is not int for value in foreground.values()):
            raise ValueError("class labels must be integers")
        if len(set(foreground.values())) != len(foreground):
            raise ValueError("duplicate class label values")
        return {str(value): name for name, value in foreground.items()}, ()
    class_order_raw = dataset_json.get("regions_class_order")
    if not isinstance(class_order_raw, list) or not all(type(value) is int and value > 0 for value in class_order_raw):
        raise ValueError("dataset.json regions_class_order must be a list of positive integers")
    region_names = list(foreground)
    if len(region_names) != len(class_order_raw) or len(set(class_order_raw)) != len(class_order_raw):
        raise ValueError("dataset.json regions do not match regions_class_order")
    for value, region in zip(class_order_raw, foreground.values(), strict=True):
        if value not in (region if isinstance(region, list) else [region]):
            raise ValueError("region export value is not in its region")
    return (
        {str(value): name for name, value in zip(region_names, class_order_raw, strict=True)},
        tuple(class_order_raw),
    )


def _profiles_dir() -> Path:
    override = os.environ.get("RW_NNUNET_PROFILES_DIR")
    return Path(override).resolve() if override else PROFILES_DIR


def load_profile(profile_id: str, *, verify_hashes: bool = True) -> Profile:
    """Load an allowlisted profile and verify all model artifacts below `nnUNet_results`."""
    if not profile_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in profile_id):
        raise ValueError("invalid profile id")
    profile_path = (_profiles_dir() / f"{profile_id}.json").resolve()
    if not profile_path.is_relative_to(_profiles_dir().resolve()) or not profile_path.is_file():
        raise ValueError(f"unknown nnU-Net profile {profile_id!r}")
    blob = profile_path.read_bytes()
    raw = _object(json.loads(blob), "profile")
    unknown = set(raw) - PROFILE_KEYS
    if unknown:
        raise ValueError(f"unknown profile fields: {sorted(unknown)}")
    if type(raw.get("profile")) is not int or raw["profile"] != 1 or raw.get("id") != profile_id:
        raise ValueError("profile version or id does not match its filename")
    results_value = os.environ.get("nnUNet_results")
    if not results_value:
        raise ValueError("nnUNet_results is not configured in the runner environment")
    results_root = Path(results_value).resolve()
    dataset = str(raw.get("dataset") or "")
    if not re.fullmatch(r"Dataset[0-9]+_[A-Za-z0-9_-]+", dataset):
        raise ValueError("profile dataset is invalid")
    if not (results_root / dataset).resolve().is_relative_to(results_root):
        raise ValueError("model dataset escapes results root")

    predictors_raw = raw.get("predictors")
    if not isinstance(predictors_raw, list) or len(predictors_raw) != 1:
        raise ValueError("this phase requires exactly one prediction configuration")
    predictors: list[Predictor] = []
    for value in predictors_raw:
        item = _object(value, "predictor")
        if set(item) != {"configuration", "trainer", "plans", "folds", "checkpoint"}:
            raise ValueError("predictor fields are invalid")
        folds = item["folds"]
        if (
            not isinstance(folds, list)
            or not folds
            or not all(type(fold) is int and fold >= 0 for fold in folds)
            or len(set(folds)) != len(folds)
        ):
            raise ValueError("predictor folds are invalid")
        if any(
            not isinstance(item[key], str) or not re.fullmatch(r"[A-Za-z0-9_]+", item[key])
            for key in ("configuration", "trainer", "plans")
        ):
            raise ValueError("predictor names must be identifiers")
        if not isinstance(item["checkpoint"], str) or not re.fullmatch(
            r"[A-Za-z0-9_][A-Za-z0-9_.-]*", item["checkpoint"]
        ):
            raise ValueError("invalid checkpoint filename")
        if "cascade" in item["configuration"].lower():
            raise ValueError("cascade models are not supported")
        predictors.append(
            Predictor(
                configuration=str(item["configuration"]),
                trainer=str(item["trainer"]),
                plans=str(item["plans"]),
                folds=tuple(folds),
                checkpoint=str(item["checkpoint"]),
            )
        )

    pp_raw = raw.get("postprocessing")
    postprocessing = None
    if pp_raw is not None:
        pp = _object(pp_raw, "postprocessing")
        if set(pp) != {"pickle", "plans", "dataset"}:
            raise ValueError("postprocessing fields are invalid")
        postprocessing = Postprocessing(str(pp["pickle"]), str(pp["plans"]), str(pp["dataset"]))

    artifacts_raw = raw.get("artifacts")
    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        raise ValueError("profile artifacts are required")
    artifacts: list[tuple[str, str]] = []
    manifest = hashlib.sha256()
    for value in artifacts_raw:
        item = _object(value, "artifact")
        if set(item) != {"path", "sha256"}:
            raise ValueError("artifact fields are invalid")
        relative, expected = str(item["path"]), str(item["sha256"])
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise ValueError(f"invalid artifact digest for {relative!r}")
        path = _inside(results_root / dataset, relative)
        if not path.is_file():
            raise ValueError(f"missing model artifact: {relative}")
        if verify_hashes and _sha256(path) != expected:
            raise ValueError(f"model artifact hash mismatch: {relative}")
        artifacts.append((relative, expected))
        manifest.update(f"{expected}  {relative}\n".encode())
    aggregate = manifest.hexdigest()
    if aggregate != raw.get("artifacts_sha256"):
        raise ValueError("model artifact manifest fingerprint mismatch")

    first = predictors[0]
    required_artifacts = {
        f"{first.folder}/dataset.json",
        f"{first.folder}/plans.json",
        *(f"{first.folder}/fold_{fold}/{first.checkpoint}" for fold in first.folds),
    }
    if postprocessing is not None:
        required_artifacts.update({postprocessing.pickle, postprocessing.plans, postprocessing.dataset})
    listed_artifacts = {relative for relative, _digest in artifacts}
    missing_fingerprints = sorted(required_artifacts - listed_artifacts)
    if missing_fingerprints:
        raise ValueError(f"runtime model artifacts are not fingerprinted: {missing_fingerprints}")
    dataset_path = _inside(results_root / dataset, f"{first.folder}/dataset.json")
    dataset_json = _object(json.loads(dataset_path.read_text(encoding="utf-8")), "dataset.json")
    labels, class_order = _derived_labels(dataset_json)
    channels = {str(k): str(v) for k, v in _object(raw.get("channels"), "channels").items()}
    actual_channels = {str(k): str(v) for k, v in _object(dataset_json.get("channel_names"), "channel_names").items()}
    expected_labels = {str(k): str(v) for k, v in _object(raw.get("labels"), "labels").items()}
    if channels != actual_channels or expected_labels != labels:
        raise ValueError("profile channels or labels differ from nnU-Net dataset.json")
    if channels != {"0": "CT"}:
        raise ValueError("only single-channel CT profiles are supported")
    expected_order = raw.get("regions_class_order")
    valid_order = expected_order == list(class_order) if class_order else expected_order in (None, [])
    if not valid_order:
        raise ValueError("profile regions_class_order differs from nnU-Net dataset.json")
    processes = _object(raw.get("processes"), "processes")
    npp, nps = processes.get("preprocessing_per_gpu"), processes.get("export_per_gpu")
    if type(npp) is not int or type(nps) is not int or not (1 <= npp <= 4 and 1 <= nps <= 4):
        raise ValueError("profile process counts must be integers from 1 to 4")

    return Profile(
        id=profile_id,
        title=str(raw.get("title") or profile_id),
        dataset=dataset,
        channels=channels,
        labels=labels,
        regions_class_order=class_order,
        predictors=tuple(predictors),
        postprocessing=postprocessing,
        preprocessing_per_gpu=npp,
        export_per_gpu=nps,
        artifacts=tuple(artifacts),
        artifacts_sha256=aggregate,
        profile_sha256="sha256:" + hashlib.sha256(blob).hexdigest(),
        results_root=results_root,
    )
