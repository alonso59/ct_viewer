"""SEG-14 / M2: drift is refused before touching GPU inventory, leases or native inference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from plugins.nnunet.profile import load_profile
from plugins.runner import gpu
from plugins.runner.identity import content_hash, freeze

from tests.test_nnunet import PROFILE_ID, REPO, make_model
from tests.test_runner_paths import setup


@pytest.mark.parametrize("drift", ["profile", "model", "input", "missing-pin"])
def test_drift_is_rejected_before_gpu_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    supervisor, job, _, spec = setup(tmp_path)
    results, profiles = make_model(tmp_path / "model-runtime")
    supervisor.config.update(model_roots=[str(results)], profiles_dir=str(profiles))
    monkeypatch.setenv("nnUNet_results", str(results))
    monkeypatch.setenv("RW_NNUNET_PROFILES_DIR", str(profiles))
    profile = load_profile(PROFILE_ID)
    plugin = REPO / "plugins/nnunet"
    manifest = json.loads((plugin / "task.json").read_text())
    spec["settings"] = {"profile": PROFILE_ID, "gpu_cap": 1}
    spec["items"][0]["item_id"] = "one"
    spec["identity"] = freeze(
        content_hash(plugin / "task.json"),
        {
            "id": profile.id,
            "profile_sha256": profile.profile_sha256,
            "artifacts_sha256": profile.artifacts_sha256,
        },
        spec["items"],
    )
    if drift == "profile":
        path = profiles / f"{PROFILE_ID}.json"
        raw = json.loads(path.read_text())
        raw["title"] = "Replacement profile"
        path.write_text(json.dumps(raw))
    elif drift == "model":
        next(results.rglob("checkpoint_final.pth")).write_bytes(b"replacement model")
    elif drift == "input":
        Path(spec["items"][0]["image"]["path"]).write_bytes(b"modified input")
    else:
        spec.pop("identity")
    (job / "job.json").write_text(json.dumps(spec))

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("GPU admission occurred before identity validation")

    monkeypatch.setattr(gpu, "inventory", forbidden)
    monkeypatch.setattr(supervisor.pool, "reserve", forbidden)
    with pytest.raises(ValueError, match=r"admission|identity|changed|hash"):
        supervisor.start(job, manifest, plugin, forbidden)
    assert not (job / "attempt.json").exists()
