"""TST-22: publishing depends on the required verification DAG and bounded test commands."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def test_verification_context_includes_the_root_lint_configuration() -> None:
    context = (REPO / "Dockerfile.verify.dockerignore").read_text().splitlines()
    assert "!ruff.toml" in context, "the built verification image cannot run make lint"


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
    jobs = workflow["jobs"]
    commands = "\n".join(
        step.get("run", "") for name in ("verify", "browser") for step in jobs[name]["steps"]
    )
    for required in (
        "make check",
        "FULL_TESTS=1",
        "make test-runner",
        "PYTEST_WORKERS=0",
        "make fixtures e2e",
    ):
        assert required in commands, f"required gate missing: {required}"
    browser = jobs["browser"]
    assert browser["needs"] == "verify"
    assert set(browser["strategy"]["matrix"]["project"]) == {"chromium", "firefox"}
    browser_commands = "\n".join(step.get("run", "") for step in browser["steps"])
    assert "PROJECT=${{ matrix.project }}" in browser_commands
    assert "SPEC=" not in browser_commands, "each browser must run every spec"
    assert set(jobs["image"]["needs"]) == {"verify", "browser"}


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


def test_product_image_lifecycle_gate_precedes_export_and_preserves_diagnostics() -> None:
    steps = yaml.safe_load((REPO / ".github/workflows/verify.yml").read_text())["jobs"]["image"][
        "steps"
    ]
    lifecycle = [
        i for i, step in enumerate(steps) if "tools.dicom_image_smoke" in step.get("run", "")
    ]
    exported = [i for i, step in enumerate(steps) if "docker save" in step.get("run", "")]
    assert len(lifecycle) == len(exported) == 1
    assert lifecycle[0] < exported[0], "export only an image that passed native DICOM recovery"
    command = steps[lifecycle[0]]["run"]
    assert '"$(id -u):$(id -g)"' in command
    assert "radiology-workbench:verification" in command
    assert "--evidence /evidence" in command
    namespaces = [
        i
        for i, step in enumerate(steps)
        if "scripts/dicom-namespace-smoke.py" in step.get("run", "")
    ]
    assert len(namespaces) == 1 and lifecycle[0] < namespaces[0] < exported[0]
    assert "radiology-workbench:verification" in steps[namespaces[0]]["run"]
    assert any(
        step.get("if") == "failure()"
        and {"build/ci/image-lifecycle", "build/ci/image-namespaces"}
        <= set(step.get("with", {}).get("path", "").splitlines())
        for step in steps
    ), "retain synthetic lifecycle evidence when acceptance fails"
