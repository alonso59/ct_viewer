# ruff: noqa: F811  (module-scoped fixtures imported from test_analytics_support)
"""Analysis tables (ADR-0060): radiomics runs and task tables read by the dashboard and analyses."""

from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from plugins.protocol import Job

from app.tables.models import TABLE_SCHEMA
from app.tables.service import store_task_table
from app.tasks.models import TaskManifest
from app.tasks.registry import manifest_hash
from tests.test_analytics_support import (  # noqa: F401  (fixtures)
    MEAN,
    VOLUME,
    Synthetic,
    mod_client,
    ok,
    syn,
)
from tests.test_api_ingest import ctx_of
from tests.test_contract import assert_problem
from tests.test_tasks import API, ITEMS, finish
from tests.test_tasks import env as env
from tests.test_tasks import plugins_root as plugins_root
from tests.test_tasks import proj as proj

TASK = "x.lesions"
SPEC: dict[str, Any] = {
    "kind": "demo_lesions",
    "title": "Demo lesions",
    "grain": "instance",
    "instance_name": "lesion",
    "columns": [
        {"name": "volume_ml", "group": "size", "unit": "mL"},
        {"name": "hu_mean", "group": "intensity", "unit": "HU"},
    ],
    "roles": {"volume": "volume_ml"},
}


def lesion_rows(items: list[dict[str, Any]]) -> pa.Table:
    """Two lesions per item on two sides: lesion 1 (right) is the larger; lesion 2 (left) is the
    same everywhere. `first` must take lesion 1 although `L` sorts before `R`."""
    rows: dict[str, list[Any]] = {n: [] for n in TABLE_SCHEMA.names}
    for k, it in enumerate(items):
        meta = it.get("meta") or {}
        for inst, vol, hu in (("1", 30.0 + k, 40.0 + k), ("2", 10.0, 20.0)):
            for group, name, value in (("size", "volume_ml", vol), ("intensity", "hu_mean", hu)):
                for key, v in (
                    ("item_id", it["item_id"]),
                    ("case_id", it.get("case_id") or str(it["item_id"]).split(".")[0]),
                    ("scan_idx", str(meta.get("scan_idx") or "01")),
                    ("scope", "complete"),
                    ("side", "R" if inst == "1" else "L"),
                    ("phase", str(meta.get("phase") or "UNK")),
                    ("label", 2),
                    ("instance", inst),
                    ("group", group),
                    ("name", name),
                    ("value", value),
                ):
                    rows[key].append(v)
    return pa.Table.from_pydict(rows, schema=TABLE_SCHEMA)


def lesion_task(job_dir: str) -> int:
    """A builtin task that writes one analysis table with two lesions per item."""
    job = Job(job_dir)
    for it in job.items:
        job.item(str(it["item_id"]), "ok")
    path = job.dir / "tables" / "lesions.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(lesion_rows(job.items), path)
    job.table("lesions", path, SPEC)
    job.finish()
    return 0


@pytest.fixture
def table_env(env: TestClient) -> TestClient:
    m = TaskManifest.model_validate(
        {
            "manifest": 1,
            "id": TASK,
            "version": "0.1.0",
            "title": "Lesions (test)",
            "description": "Writes an analysis table with two lesions per item.",
            "kind": "features",
            "input": "items",
            "outputs": ["tables"],
            "requires": {"modality": ["CT"]},
            "settings_schema": {"type": "object", "properties": {}},
            "runtime": {"type": "builtin", "entry": "tests.test_tables:lesion_task"},
            "resources": {"gpu": "none"},
            "test_only": True,
        }
    )
    ctx_of(env).registry.add(m, manifest_hash(m.model_dump_json().encode()), "builtin")
    return env


def run_task(c: TestClient, pid: str) -> dict[str, Any]:
    r = c.post(
        f"{API}/projects/{pid}/task-runs",
        json={"task_id": TASK, "selection": {"item_ids": ITEMS}},
        headers={"X-Reviewer": "T"},
    )
    assert r.status_code == 202, r.text
    run = finish(c, pid, r.json())
    assert run["status"] == "completed", run
    return run


def test_a_task_table_is_registered_listed_and_analyzed(table_env: TestClient, proj: str) -> None:
    c = table_env
    run = run_task(c, proj)
    tid = f"{run['run_id']}-lesions"
    [out] = [o for o in run["outputs"] if o["kind"] == "table"]
    assert out["detail"] == tid and out["ref"] == f"tasks/runs/{run['run_id']}/tables/lesions"
    [row] = [t for t in ok(c.get(f"{API}/projects/{proj}/tables")) if t["table_id"] == tid]
    assert row["kind"] == "demo_lesions" and row["grain"] == "instance"
    assert row["producer"] == {"task": TASK, "run_id": run["run_id"]}
    assert row["counts"] == {"items": 3, "columns": 2, "observations": 6}
    assert row["labels"] == [2]
    m = ok(c.get(f"{API}/projects/{proj}/tables/{tid}"))
    assert [col["name"] for col in m["columns"]] == ["volume_ml", "hu_mean"]

    views = f"{API}/projects/{proj}/tables/{tid}/views"
    over = ok(c.post(f"{views}/run-overview", json={}))
    assert over["table_id"] == tid and over["name"] == "Demo lesions"
    assert over["n_items_ok"] == 3 and over["n_features"] == 2
    assert (over["n_instances"], over["n_cases_with_several"]) == (6, 3)
    size = ok(c.post(f"{views}/missing-matrix", json={"groups": ["size"]}))
    assert [f["feature"] for f in size["features"]] == ["volume_ml"]
    vol = ok(c.post(f"{views}/feature-vs-volume", json={"feature": "hu_mean"}))
    assert vol["volume_feature"] == "volume_ml" and vol["n"] == 6

    # The unit: `first` takes lesion 1 of each case, `mean` both, `none` keeps every lesion.
    def analyze(aggregate: str) -> dict[str, Any]:
        spec = {"table_id": tid, "question": "explore", "unit": {"aggregate": aggregate}}
        return dict(ok(c.post(f"{API}/projects/{proj}/analyses", json=spec), 201))

    def tidy(a: dict[str, Any]) -> list[float]:
        r = c.get(f"{API}/projects/{proj}/analyses/{a['analysis_id']}/export")
        return sorted(float(x["volume_ml"]) for x in csv.DictReader(io.StringIO(r.text)))

    first, mean, every = analyze("first"), analyze("mean"), analyze("none")
    assert tidy(first) == [30.0, 31.0, 32.0]
    assert tidy(mean) == [20.0, 20.5, 21.0]
    assert tidy(every) == [10.0, 10.0, 10.0, 30.0, 31.0, 32.0]
    assert "REC-NONINDEP" in {r["code"] for r in every["recommendations"]}
    assert "REC-NONINDEP" not in {r["code"] for r in first["recommendations"]}

    wide = c.get(f"{API}/projects/{proj}/tables/{tid}/export")
    rows = list(csv.DictReader(io.StringIO(wide.text)))
    assert len(rows) == 6 and {"instance", "volume_ml", "hu_mean"} <= set(rows[0])
    long = c.get(f"{API}/projects/{proj}/tables/{tid}/export", params={"shape": "long"})
    assert len(list(csv.DictReader(io.StringIO(long.text)))) == 12
    parquet = c.get(f"{API}/projects/{proj}/tables/{tid}/export", params={"format": "parquet"})
    assert pq.read_table(io.BytesIO(parquet.content)).num_rows == 6


def test_radiomics_runs_are_tables(mod_client: TestClient, syn: Synthetic) -> None:
    c = mod_client
    [row] = [
        t for t in ok(c.get(f"{API}/projects/{syn.pid}/tables")) if t["table_id"] == syn.run_id
    ]
    assert row["kind"] == "radiomics" and row["grain"] == "label"
    over = ok(c.post(f"{API}/projects/{syn.pid}/tables/{syn.run_id}/views/run-overview", json={}))
    assert (over["n_instances"], over["n_cases_with_several"]) == (0, 0)
    assert row["roles"] == {"volume": VOLUME}
    m = ok(c.get(f"{API}/projects/{syn.pid}/tables/{syn.run_id}"))
    groups = {col["name"]: col["group"] for col in m["columns"]}
    assert groups[MEAN] == "firstorder" and groups[VOLUME] == "shape"
    assert m["counts"]["columns"] == len(m["columns"])
    assert_problem(c.get(f"{API}/projects/{syn.pid}/tables/nope"), "not-found")
    assert_problem(c.get(f"{API}/projects/{syn.pid}/tables/..%2Fx"), "not-found")


def declared(tmp_path: Path, table: pa.Table, **entry: Any) -> tuple[Path, dict[str, Any]]:
    job = tmp_path / "job"
    path = job / "t.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return job, {"name": "lesions", "path": "t.parquet", "sha256": sha, "spec": SPEC, **entry}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": "Bad-Name"}, "lower-case"),
        ({"path": "../t.parquet"}, "not a file in the job folder"),
        ({"sha256": "0" * 64}, "changed after"),
        ({"spec": {**SPEC, "roles": {"volume": "nope"}}}, "no column nope"),
        ({"spec": {**SPEC, "grain": "label"}}, "one row per label"),
        ({"spec": {**SPEC, "extra": 1}}, "extra"),
    ],
)
def test_task_tables_are_checked(tmp_path: Path, change: dict[str, Any], message: str) -> None:
    items = [{"item_id": "case_00001.01.complete.-"}]
    job, entry = declared(tmp_path, lesion_rows(items), **change)
    run = tmp_path / "01JAAAAAAAAAAAAAAAAAAAAAAA"
    with pytest.raises(ValueError, match=message):
        store_task_table(run, TASK, "completed", entry, job)
    assert not (run / "tables").exists()


def test_a_table_without_the_canonical_columns_is_refused(tmp_path: Path) -> None:
    t = lesion_rows([{"item_id": "a"}]).drop_columns(["instance"])
    job, entry = declared(tmp_path, t)
    with pytest.raises(ValueError, match="analysis table columns"):
        store_task_table(tmp_path / "run", TASK, "completed", entry, job)
