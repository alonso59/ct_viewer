"""CTF-17: the script library — project, workspace and shipped scripts, parameters from the
header, `save` from the console, and script runs started by name."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.ctflow.lang import parse_script
from app.ctflow.library import SHIPPED, header
from tests.test_api_ingest import ctx_of
from tests.test_contract import assert_problem
from tests.test_ctflow_runs import RUNS, children, ended, until
from tests.test_tasks import ITEMS, with_derived
from tests.test_tasks import env as env
from tests.test_tasks import plugins_root as plugins_root
from tests.test_tasks import proj as proj

API = "/api/v1/ctflow"
THR = "segment.threshold"
SCRIPT = f"""# Threshold one item.
# param item -  the item to segment
# param level 100  HU threshold
set r [{THR} $item -threshold $level]
wait $r
"""


def eval_line(c: TestClient, line: str, pid: str | None = None) -> dict:  # type: ignore[type-arg]
    r = c.post(f"{API}/eval", json={"line": line, "project_id": pid})
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_shipped_examples_parse_and_declare_their_parameters() -> None:
    scripts = sorted(SHIPPED.glob("*.ctf"))
    assert {p.name for p in scripts} == {"segment-phase.ctf", "segment-then-radiomics.ctf"}
    for path in scripts:
        text = path.read_text()
        parse_script(text)
        summary, params = header(text)
        assert summary and params
    _, params = header((SHIPPED / "segment-then-radiomics.ctf").read_text())
    assert [(p.name, p.default) for p in params] == [
        ("case", None), ("labels", None), ("set", "ctflow-seg"),
    ]  # fmt: skip


def test_project_scripts_hide_workspace_and_shipped_ones(env: TestClient, proj: str) -> None:
    listed = {s["name"]: s for s in env.get(f"{API}/scripts").json()}
    assert listed["segment-phase.ctf"]["scope"] == "shipped"
    assert env.put(f"{API}/scripts/mine.ctf", json={"text": "# workspace one\nset x 1"}).is_success
    saved = env.put(
        f"{API}/scripts/mine.ctf", params={"project": proj}, json={"text": "# project one\nset x 2"}
    ).json()
    assert saved["scope"] == "project"
    assert env.get(f"{API}/scripts/mine.ctf").json()["summary"] == "workspace one"
    in_project = env.get(f"{API}/scripts/mine.ctf", params={"project": proj}).json()
    assert in_project["scope"] == "project" and in_project["text"].endswith("set x 2")
    project_dir = ctx_of(env).workspace.project_dir(proj)
    assert (project_dir / "plugins/ctflow/scripts/mine.ctf").is_file()
    assert env.delete(f"{API}/scripts/mine.ctf", params={"project": proj}).status_code == 204
    assert (
        env.get(f"{API}/scripts/mine.ctf", params={"project": proj}).json()["scope"] == "workspace"
    )
    assert_problem(env.delete(f"{API}/scripts/segment-phase.ctf"), "not-found")  # shipped stays
    assert_problem(env.put(f"{API}/scripts/../x.ctf", json={"text": "set x 1"}), "not-found")
    assert_problem(env.put(f"{API}/scripts/x.sh", json={"text": "set x 1"}), "validation")
    assert_problem(env.put(f"{API}/scripts/bad.ctf", json={"text": "puts {open"}), "validation")


def test_save_a_console_procedure_and_source_it_in_a_new_session(
    env: TestClient, proj: str
) -> None:
    first = eval_line(env, "proc twice {x} { expr {$x * 2} }; save twice", proj)
    assert first["steps"][-1]["value"] == "twice.ctf"
    root = ctx_of(env).settings.workspace_root / "plugins/ctflow/scripts/twice.ctf"
    assert root.is_file()
    assert eval_line(env, "source twice.ctf; twice 21")["value"] == "42"  # a new session
    listed = eval_line(env, "scripts")["steps"][0]["value"]
    assert "twice.ctf" in listed and "segment-phase.ctf" in listed
    eval_line(env, "proc local {} { return p }; save local -project", proj)
    assert (ctx_of(env).workspace.project_dir(proj) / "plugins/ctflow/scripts/local.ctf").is_file()


def test_a_script_run_starts_from_the_library_with_parameters(
    env: TestClient, proj: str, tmp_path: Path
) -> None:
    with_derived(env, proj, tmp_path)
    env.put(f"{API}/scripts/one.ctf", json={"text": SCRIPT})
    missing = env.post(RUNS, json={"library": "one.ctf", "project_id": proj})
    assert_problem(missing, "validation")
    assert missing.json()["errors"] == [{"loc": ["params", "item"], "msg": "required"}]
    unknown = env.post(
        RUNS, json={"library": "one.ctf", "project_id": proj, "params": {"item": "x", "zz": "1"}}
    )
    assert_problem(unknown, "validation")
    both = env.post(RUNS, json={"library": "one.ctf", "script": "set x 1"})
    assert_problem(both, "validation")
    started = env.post(
        RUNS, json={"library": "one.ctf", "project_id": proj, "params": {"item": ITEMS[0]}}
    ).json()
    assert started["params"] == {"item": ITEMS[0], "level": "100"} and started["name"] == "one.ctf"
    env.put(f"{API}/scripts/one.ctf", json={"text": "# changed\nset x 1"})  # after the start
    run = until(env, started["run_id"], ended)
    assert run["status"] == "completed" and run["script"] == SCRIPT  # the snapshot ran
    child = children(env, proj, started["run_id"])
    detail = env.get(f"/api/v1/projects/{proj}/task-runs/{child[0]['run_id']}").json()
    assert len(child) == 1 and detail["settings"]["threshold"] == 100  # the parameter's default
