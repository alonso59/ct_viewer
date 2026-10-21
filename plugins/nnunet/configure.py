#!/usr/bin/env python3
"""Validate or refresh a structured nnU-Net profile without copying command text."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.nnunet.profile import PROFILES_DIR, load_profile


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def refresh(profile_path: Path, results_root: Path) -> None:
    raw: dict[str, Any] = json.loads(profile_path.read_text(encoding="utf-8"))
    dataset_root = results_root / str(raw["dataset"])
    manifest = hashlib.sha256()
    for artifact in raw["artifacts"]:
        relative = str(artifact["path"])
        path = (dataset_root / relative).resolve()
        if not path.is_relative_to(dataset_root.resolve()) or not path.is_file():
            raise ValueError(f"missing or unsafe artifact: {relative}")
        digest = _sha256(path)
        artifact["sha256"] = digest
        manifest.update(f"{digest}  {relative}\n".encode())
    raw["artifacts_sha256"] = manifest.hexdigest()
    tmp = profile_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(profile_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an nnU-Net model profile")
    parser.add_argument("--profile", default="kits2023-dataset220")
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument(
        "--refresh-hashes",
        action="store_true",
        help="Rewrite the selected profile's artifact hashes from this results root",
    )
    args = parser.parse_args(argv)
    valid_profile_characters = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    if not args.profile or set(args.profile) - valid_profile_characters:
        raise ValueError("invalid profile id")
    profile_path = (PROFILES_DIR / f"{args.profile}.json").resolve()
    if not profile_path.is_relative_to(PROFILES_DIR.resolve()) or not profile_path.is_file():
        raise ValueError(f"unknown nnU-Net profile {args.profile!r}")
    if args.refresh_hashes:
        refresh(profile_path, args.results_root.resolve())
    os.environ["nnUNet_results"] = str(args.results_root.resolve())
    profile = load_profile(args.profile)
    print(
        json.dumps(
            {
                "profile": profile.id,
                "dataset": profile.dataset,
                "artifacts": len(profile.artifacts),
                "artifacts_sha256": profile.artifacts_sha256,
                "labels": profile.labels,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
