"""SEG-08: four GPUs cannot multiply CPU workers beyond the operator budget."""

from pathlib import Path

import pytest
from plugins.nnunet import run
from plugins.nnunet.profile import load_profile

from tests.test_nnunet import PROFILE_ID, make_model


def test_four_gpu_prediction_bounds_combined_worker_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, profiles = make_model(tmp_path)
    monkeypatch.setenv("nnUNet_results", str(results))
    monkeypatch.setenv("RW_NNUNET_PROFILES_DIR", str(profiles))
    monkeypatch.setenv("RW_CPU_WORKERS", "12")
    profile = load_profile(PROFILE_ID)
    command = run._predict_command(
        profile, profile.predictors[0], Path("input"), Path("output"), 4, 0
    )
    preprocessing = int(command[command.index("-npp") + 1])
    export = int(command[command.index("-nps") + 1])
    assert 4 * (1 + preprocessing + export) <= 12
    assert preprocessing >= 1 and export >= 1
