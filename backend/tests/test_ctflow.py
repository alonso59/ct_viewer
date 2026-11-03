"""CTF-02..06, CTF-09 / API-72: the console catalog, targets, plan mode and GUI parity."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.ctflow.parse import parse
from app.main import create_app
from app.tasks.models import TaskCommand
from app.tasks.registry import Registry, manifest_hash, parse_manifest
from tests.test_api_ingest import ctx_of, wait
from tests.test_contract import assert_problem
from tests.test_source_operations_api import wait_operation
from tests.test_tasks import ITEMS, builtin_threshold, finish, run_body, with_derived
from tests.test_tasks import env as env
from tests.test_tasks import plugins_root as plugins_root
from tests.test_tasks import proj as proj
from tools.dicom_fixtures import write_series

API = "/api/v1"
THR = "segment.threshold"  # test-only: callable by id, not listed


def run(c: TestClient, line: str, pid: str | None = None, **body: Any) -> Any:
    r = c.post(
        f"{API}/ctflow/eval",
        json={"line": line, "project_id": pid, **body},
        headers={"X-Reviewer": "Console T"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def problem(c: TestClient, line: str, pid: str | None, slug: str, **body: Any) -> Any:
    r = c.post(f"{API}/ctflow/eval", json={"line": line, "project_id": pid, **body})
    assert_problem(r, slug)
    return r.json()


def test_line_words_quotes_braces_and_flags() -> None:
    line = parse('/segment "/data/a b/x.nii.gz" -gpus 2 -fast -name {my run}')
    assert line.name == "segment" and line.args == ["/data/a b/x.nii.gz"]
    assert line.options == {"gpus": "2", "fast": "true", "name": "my run"}
    assert parse("x -n -1").options == {"n": "-1"}  # a negative number is a value


def test_catalog_lists_task_commands_from_manifests(env: TestClient) -> None:
    commands = {c["name"]: c for c in env.get(f"{API}/ctflow/commands").json()}
    assert {"help", "cases", "runs", "status", "convert"} <= set(commands)
    assert commands["dicom2nii"]["task_id"] == "dicom.convert"
    assert commands["radiomics"]["task_id"] == "radiomics.pyradiomics"
    assert THR not in commands  # test-only tasks stay out of the listing
    options = {o["name"]: o for o in commands["dicom2nii"]["options"]}
    assert options["phase-analyzer"]["setting"] == "phase_analyzer"
    assert options["phase-analyzer"]["type"] == "boolean" and "seg" not in options


def test_a_duplicate_command_name_makes_the_later_manifest_invalid() -> None:
    reg = Registry()
    first = builtin_threshold().model_copy(update={"command": TaskCommand(name="seg")})
    second = first.model_copy(update={"id": "segment.other"})
    reg.add(first, manifest_hash(b"1"), "builtin")
    reg.add(second, manifest_hash(b"2"), "builtin")
    assert list(reg.tasks) == [THR] and "duplicate command name" in reg.invalid[0].error


def test_console_start_equals_the_gui_start(env: TestClient, proj: str, tmp_path: Path) -> None:
    """CTF-02 parity: the same request through CTFlow and API-45 gives the same run record."""
    with_derived(env, proj, tmp_path)
    case = ITEMS[0].split(".")[0]
    out = run(env, f"{THR} {case} -threshold 100", proj)
    assert out["target"]["kind"] == "case" and ITEMS[0] in out["target"]["item_ids"]
    assert out["started"]["kind"] == "task-run"
    console = finish(
        env, proj, {"run_id": out["started"]["id"], "job_id": out["started"]["job_id"]}
    )
    body = {**run_body(), "selection": {"item_ids": out["target"]["item_ids"]}}
    started = env.post(
        f"{API}/projects/{proj}/task-runs", json=body, headers={"X-Reviewer": "Console T"}
    ).json()
    gui = finish(env, proj, started)
    same = ["task", "settings", "settings_hash", "selection", "item_ids", "runtime", "reviewer"]
    assert {k: console[k] for k in same} == {k: gui[k] for k in same}
    assert [i["image_fp"] for i in console["inputs"]] == [i["image_fp"] for i in gui["inputs"]]
    assert console["status"] == gui["status"] == "completed"
    assert console["origin"]["client"] == "console" and gui["origin"]["client"] == "gui"


def test_targets_resolve_exactly_or_refuse(
    env: TestClient, proj: str, tmp_path: Path, data_root: Path
) -> None:
    with_derived(env, proj, tmp_path)
    plan = {"plan": True}
    assert run(env, f"{THR} {ITEMS[1]}", proj, **plan)["target"]["item_ids"] == [ITEMS[1]]
    everything = run(env, f"{THR} all", proj, **plan)["target"]
    assert everything["kind"] == "all" and everything["n_items"] >= len(ITEMS)
    image = (
        ctx_of(env)
        .workspace.resolver(proj)
        .resolve(
            ctx_of(env).index.load(proj).by_id[ITEMS[2]].image.ref  # type: ignore[union-attr]
        )
    )
    by_path = run(env, f'{THR} "{image}"', proj, **plan)["target"]
    assert by_path["kind"] == "path" and by_path["item_ids"] == [ITEMS[2]]
    (data_root / "not-imported").mkdir()
    refused = problem(env, f"{THR} {data_root / 'not-imported'}", proj, "validation", **plan)
    assert set(refused["actions"]) == {"create_project", "import_source"}
    assert str(data_root) not in refused["detail"]  # no path in the problem (NFR-17)
    problem(env, f"{THR} case_99999", proj, "not-found", **plan)
    problem(env, f"{THR} nifti/x.nii.gz", proj, "validation", **plan)
    assert "create_project" in problem(env, f"{THR} {ITEMS[0]}", None, "validation")["actions"]
    problem(env, f"{THR} {ITEMS[0]} -nope 1", proj, "validation")
    problem(env, f"{THR} {ITEMS[0]} -threshold high", proj, "validation")
    problem(env, "bogus", proj, "not-found")


def test_plan_mode_checks_without_starting(env: TestClient, proj: str, tmp_path: Path) -> None:
    with_derived(env, proj, tmp_path)
    out = run(env, f"{THR} {ITEMS[0]} -threshold 100", proj, plan=True)
    assert out["started"] is None and out["plan"]["ok"] is True
    assert out["plan"]["settings"]["threshold"] == 100
    assert out["plan"]["preflight"]["n_ready"] == 1
    assert env.get(f"{API}/projects/{proj}/task-runs").json() == []
    bad = run(env, f"{THR} {ITEMS[0]} -label 999", proj, plan=True)["plan"]
    assert bad["ok"] is False and bad["issues"]


def test_mask_sets_are_chosen_explicitly_when_several_match(
    env: TestClient, proj: str, tmp_path: Path
) -> None:
    """CTF-06: several covering sets stop the command; `-seg default` is the project default."""
    pytest.importorskip("radiomics")
    with_derived(env, proj, tmp_path)
    for seg in ("thr-a", "thr-b"):
        started = env.post(f"{API}/projects/{proj}/task-runs", json=run_body(seg_id=seg)).json()
        assert finish(env, proj, started)["status"] == "completed"
    plan = {"plan": True}
    line = f"radiomics {ITEMS[0]} -labels foreground"
    ambiguous = problem(env, line, proj, "validation", **plan)
    assert "thr-a" in ambiguous["errors"][0]["msg"] and "thr-b" in ambiguous["errors"][0]["msg"]
    chosen = run(env, f"{line} -seg thr-b", proj, **plan)["target"]
    assert chosen["seg_id"] == "thr-b" and chosen["labels"]
    default = ctx_of(env).workspace.get(proj).default_seg
    assert run(env, f"{line} -seg default", proj, **plan)["target"]["seg_id"] == default
    problem(env, f"radiomics {ITEMS[0]} -seg thr-a", proj, "validation", **plan)  # no labels
    problem(env, f"{line} -seg missing", proj, "not-found", **plan)


def test_dicom2nii_runs_the_converter_window_flow(tmp_path: Path) -> None:
    """Analysis as a durable source operation, then `convert`, as the GUI does (API-69)."""
    source, derived = tmp_path / "source", tmp_path / "derived"
    write_series(source)
    derived.mkdir()
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        allowed_derived_roots=str(derived),
        dicom_memory_mb=1024,
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        started = run(client, f"dicom2nii {source} -name ct1")["started"]
        assert started["kind"] == "source-operation"
        operation = started["id"]
        deadline = time.monotonic() + 15
        while client.get(f"{API}/source-operations/{operation}").json()["stage"] != "ready":
            assert time.monotonic() < deadline
            wait_operation(client, operation)
            time.sleep(0.05)
        assert run(client, f"convert {operation}")["started"]["id"] == operation
        conversion = None
        while conversion is None and time.monotonic() < deadline + 15:
            conversion = client.get(f"{API}/source-operations/{operation}").json()["conversion_run"]
            time.sleep(0.02)
        assert conversion is not None
        wait(client, conversion["job_id"])
        op = client.get(f"{API}/source-operations/{operation}").json()
        assert op["origin"]["client"] == "console" and op["reviewer"] == "Console T"
        assert op["conversion_run"]["status"] == "completed"
        assert op["conversion_run"]["origin"]["client"] == "console"
        assert op["conversion_run"]["reviewer"] == "Console T"
        status = run(client, f"status {operation}")
        assert status["data"]["operation_id"] == operation


def test_shipped_manifests_name_their_commands() -> None:
    repo = Path(__file__).resolve().parents[2]
    names = {
        parse_manifest(repo / p)[0].command.name  # type: ignore[union-attr]
        for p in (
            "plugins/nnunet/task.json",
            "plugins/dicom/task.json",
            "backend/app/radiomics/task.json",
        )
    }
    assert names == {"segment", "dicom2nii", "radiomics"}
