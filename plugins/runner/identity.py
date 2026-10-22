"""SEG-14: immutable model/input identity shared by API, admission and native wrapper."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def input_hashes(items: list[dict[str, Any]]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for item in items:
        key = item.get("item_id")
        image = item.get("image")
        if not isinstance(key, str) or not key or key in hashes or not isinstance(image, dict):
            raise ValueError("ambiguous or missing input identity")
        hashes[key] = content_hash(Path(image["path"]))
    return hashes


def freeze(manifest_hash: str, profile: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    selected = {key: profile.get(key) for key in ("id", "profile_sha256", "artifacts_sha256")}
    if any(not isinstance(value, str) or not value for value in selected.values()):
        raise ValueError("profile identity is unavailable")
    return {"identity": 1, "manifest_hash": manifest_hash, "profile": selected, "inputs": input_hashes(items)}


def verify_inputs(pin: dict[str, Any], items: list[dict[str, Any]]) -> None:
    if pin.get("identity") != 1 or input_hashes(items) != pin.get("inputs"):
        raise ValueError("pinned input changed or missing; start a new run")


def verify_profile(pin: dict[str, Any], profile: dict[str, Any]) -> None:
    selected = {key: profile.get(key) for key in ("id", "profile_sha256", "artifacts_sha256")}
    if pin.get("identity") != 1 or pin.get("profile") != selected:
        raise ValueError("pinned profile or model changed; start a new run")


def verify_files(files: dict[str, str]) -> None:
    for name, expected in files.items():
        try:
            actual = content_hash(Path(name))
        except OSError:
            raise ValueError("committed output changed or missing") from None
        if actual != expected:
            raise ValueError("committed output changed or missing")


def verify_job(spec: dict[str, Any], manifest: Path, profile: dict[str, Any]) -> None:
    pin = spec.get("identity")
    if not isinstance(pin, dict) or content_hash(manifest) != pin.get("manifest_hash"):
        raise ValueError("pinned task manifest changed or identity missing; start a new run")
    verify_profile(pin, profile)
    verify_inputs(pin, spec.get("items", []))
    verify_files(spec.get("committed_outputs", {}))
