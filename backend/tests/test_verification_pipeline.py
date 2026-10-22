"""TST-22: publishing depends on the required verification DAG and bounded test commands."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def test_image_publication_depends_on_reusable_verification() -> None:
    workflow = yaml.safe_load((REPO / ".github/workflows/build.yml").read_text())
    jobs = workflow["jobs"]
    assert "verify" in jobs, "publication has no verification dependency"
    assert jobs["verify"]["uses"] == "./.github/workflows/verify.yml"
    dependency = jobs["build"].get("needs", [])
    assert "verify" in ([dependency] if isinstance(dependency, str) else dependency)
    assert "always()" not in str(jobs["build"].get("if", ""))


def test_verification_runs_full_checks_serial_safety_and_both_browsers() -> None:
    path = REPO / ".github/workflows/verify.yml"
    assert path.exists(), "no enforced verification workflow exists"
    workflow = yaml.safe_load(path.read_text())
    commands = "\n".join(step.get("run", "") for step in workflow["jobs"]["verify"]["steps"])
    for required in (
        "make check",
        "FULL_TESTS=1",
        "make test-runner",
        "PYTEST_WORKERS=0",
        "make fixtures e2e",
    ):
        assert required in commands, f"required gate missing: {required}"
    assert "--project=" not in commands, "the browser gate must exercise both configured browsers"


def test_test_target_uses_explicit_bounded_worker_counts() -> None:
    result = subprocess.run(
        ["make", "-n", "test", "RUNTIME=native", "PYTEST_WORKERS=3", "VITEST_WORKERS=2"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "-n 3 --dist loadscope" in result.stdout
    assert "--maxWorkers=2" in result.stdout
    assert "OMP_NUM_THREADS=1" in result.stdout
