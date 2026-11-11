"""ADR-0055 §7-§10 and ADR-0056 on the API side: profiles, storage locations, backups."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.tasks import catalog
from app.tasks.models import TaskInfo
from tests.conftest import make_settings

API = "/api/v1"
PROFILE = {
    "name": "One GPU",
    "account": "lab",
    "partition": "gpu_short",
    "gpus": 1,
    "cpus": 8,
    "memory_mb": 16384,
    "seconds": 28800,
}


def beat(workspace: Path, scheduler: dict[str, Any], **execution: Any) -> None:
    """What a scheduler runner publishes in its heartbeat."""
    folder = workspace / "queue/runners"
    folder.mkdir(parents=True, exist_ok=True)
    limits = {"cpus": 8, "memory_mb": 32768, "tasks": 64, "seconds": 86400, "gpus": 2}
    body = {
        "tasks": ["segment.nnunet"],
        "pid": 1,
        "at": datetime.now(UTC).isoformat(),
        "execution": {"backend": "slurm", "limits": limits, "scheduler": scheduler, **execution},
    }
    (folder / "node-1.json").write_text(json.dumps(body))


@pytest.fixture
def site(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    data, derived = tmp_path / "data", tmp_path / "derived"
    (data / "scans").mkdir(parents=True)
    derived.mkdir()
    settings = make_settings(tmp_path, [data]).model_copy(
        update={"allowed_derived_roots": str(derived), "backup_max_mb": 1, "backup_total_mb": 1}
    )
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        yield client, tmp_path


def test_without_a_runner_nothing_about_the_scheduler_is_claimed(
    site: tuple[TestClient, Path],
) -> None:
    client, _ = site
    state = client.get(f"{API}/compute").json()
    assert state["backend"] is None and state["partitions"] is None and state["accounts"] is None
    assert state["profiles"] == []


def test_a_profile_is_stored_and_takes_its_verdict_from_the_runner(
    site: tuple[TestClient, Path],
) -> None:
    client, root = site
    saved = client.put(f"{API}/compute/profiles/one-gpu", json=PROFILE).json()
    assert [(p["id"], p["status"]) for p in saved["profiles"]] == [("one-gpu", "unchecked")]
    verdict = {"status": "valid", "reason": "", "estimated_start": "2026-11-12T10:00:00"}
    beat(
        root / "workspace",
        {
            "at": "2026-11-11T10:00:00Z",
            "error": None,
            "accounts": ["lab"],
            "partitions": [{"name": "gpu_short", "up": True, "max_seconds": None, "gpus": True}],
            "request": "r1",
            "profiles": [{"id": "one-gpu", **PROFILE, **verdict}],
        },
    )
    state = client.get(f"{API}/compute").json()
    assert (state["backend"], state["accounts"], state["answered"]) == ("slurm", ["lab"], "r1")
    assert state["partitions"][0]["max_seconds"] is None
    (profile,) = state["profiles"]
    assert (profile["status"], profile["estimated_start"]) == ("valid", "2026-11-12T10:00:00")
    # a changed definition is unchecked until the runner has tested the new one
    changed = client.put(f"{API}/compute/profiles/one-gpu", json={**PROFILE, "cpus": 4}).json()
    assert changed["profiles"][0]["status"] == "unchecked"
    assert client.post(f"{API}/compute/check").status_code == 202
    assert client.delete(f"{API}/compute/profiles/one-gpu").json()["profiles"][0]["implicit"]
    assert client.delete(f"{API}/compute/profiles/one-gpu").status_code == 404


@pytest.mark.parametrize(
    "change",
    [{"gpus": 3}, {"partition": "gpu --wrap=id"}, {"account": "a;b"}, {"seconds": 0}, {"name": ""}],
)
def test_the_browser_cannot_store_flags_or_more_than_two_gpus(
    site: tuple[TestClient, Path], change: dict[str, Any]
) -> None:
    client, _ = site
    assert client.put(f"{API}/compute/profiles/p", json={**PROFILE, **change}).status_code == 422
    assert client.put(f"{API}/compute/profiles/Bad_Id", json=PROFILE).status_code == 422


def test_the_task_form_offers_only_valid_profiles(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "required": ["profile"],
        "properties": {
            "profile": {"type": "string"},
            "gpu_ids": {"type": "array"},
            "compute_profile": {"type": "string"},
        },
    }
    raw = {
        "id": "segment.nnunet",
        "version": "1.0.0",
        "title": "Segment",
        "kind": "segmentation",
        "input": "items",
        "outputs": ["masks"],
        "runtime": {"type": "external", "command": ["x"]},
        "settings_schema": schema,
    }
    info = TaskInfo.model_validate(
        {"manifest": raw, "source": "builtin", "manifest_hash": "0" * 64}
    )
    profiles = [
        {"id": "ok", **PROFILE, "status": "valid"},
        {"id": "no", **PROFILE, "status": "rejected"},
    ]
    info.execution = {"backend": "slurm", "scheduler": {"profiles": profiles}}
    catalog._gpu_fields(info)
    properties = info.manifest.settings_schema["properties"]
    assert "gpu_ids" not in properties and properties["compute_profile"]["enum"] == ["ok"]
    assert "8 CPU" in properties["compute_profile"]["x-enumNames"][0]
    assert "compute_profile" in info.manifest.settings_schema["required"] and info.available
    info.execution = {"backend": "slurm", "scheduler": {"profiles": profiles[1:]}}
    catalog._gpu_fields(info)
    assert not info.available and "Settings" in (info.unavailable_reason or "")
    local = TaskInfo.model_validate(
        {"manifest": raw, "source": "builtin", "manifest_hash": "0" * 64}
    )
    local.execution = {"backend": "server"}
    catalog._gpu_fields(local)
    assert "compute_profile" not in local.manifest.settings_schema["properties"]


def test_locations_are_registered_only_inside_the_operator_s_roots(
    site: tuple[TestClient, Path],
) -> None:
    client, root = site
    scans = root / "data/scans"
    state = client.get(f"{API}/storage").json()
    assert state["registrable"] and state["locations"] == [] and state["discovered"] is None
    outside = client.post(f"{API}/storage/locations", json={"path": str(root)})
    assert outside.status_code == 403
    (root / "data/escape").symlink_to(root)
    assert (
        client.post(f"{API}/storage/locations", json={"path": f"{root}/data/escape"}).status_code
        == 403
    )
    traversal = f"{root}/data/scans/../../workspace"
    assert client.post(f"{API}/storage/locations", json={"path": traversal}).status_code == 403
    assert (
        client.post(f"{API}/storage/locations", json={"path": f"{scans}/missing"}).status_code
        == 422
    )
    added = client.post(f"{API}/storage/locations", json={"path": str(scans), "label": "Scans"})
    assert added.status_code == 201
    (location,) = added.json()["locations"]
    assert (location["kind"], location["available"], location["writable"]) == (
        "local_directory",
        True,
        True,
    )
    assert added.json()["default_location"] == location["id"]
    assert client.post(f"{API}/storage/locations", json={"path": str(scans)}).status_code == 422
    # a dataset folder is checked by permissions alone: nothing is written into a source
    tested = client.post(f"{API}/storage/locations/{location['id']}/test").json()
    assert tested["method"] == "permissions" and list(scans.iterdir()) == []
    # the browser now starts at the location and cannot leave it; choosing a new one still can
    listed = client.post(f"{API}/fs/list", json={}).json()
    assert [entry["path"] for entry in listed["entries"]] == [str(scans)]
    assert client.post(f"{API}/fs/list", json={"path": str(root / "data")}).status_code == 403
    assert (
        client.post(
            f"{API}/fs/list", json={"path": str(root / "data"), "scope": "allowed"}
        ).status_code
        == 200
    )
    scans.rmdir()
    gone = client.get(f"{API}/storage").json()["locations"][0]
    assert not gone["available"] and not gone["writable"]
    assert client.delete(f"{API}/storage/locations/{location['id']}").json()["locations"] == []


def test_a_derived_location_is_probed_and_a_read_only_one_cannot_be_the_default(
    site: tuple[TestClient, Path],
) -> None:
    client, root = site
    added = client.post(f"{API}/fs/list", json={"role": "derived"})
    assert added.status_code == 200
    scans = client.post(
        f"{API}/storage/locations", json={"path": str(root / "data/scans"), "access": "read_only"}
    ).json()
    (location,) = scans["locations"]
    assert not location["writable"] and scans["default_location"] is None
    refused = client.put(f"{API}/storage/default", json={"location_id": location["id"]})
    assert refused.status_code == 422
    assert client.post(f"{API}/storage/locations/{location['id']}/test").json()["method"] == "none"


def test_managed_workspaces_come_from_the_runner_and_show_their_expiry(
    site: tuple[TestClient, Path],
) -> None:
    client, root = site
    expires = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    items = [
        {
            "name": "scans",
            "path": str(root / "data/scans"),
            "filesystem": "scratch",
            "expires": expires,
            "extensions": 2,
        },
        {
            "name": "far",
            "path": str(root / "elsewhere"),
            "filesystem": "scratch",
            "expires": None,
            "extensions": None,
        },
    ]
    beat(
        root / "workspace",
        {"workspaces": {"at": "2026-11-11T10:00:00Z", "error": None, "items": items}},
    )
    found = {w["name"]: w for w in client.get(f"{API}/storage").json()["discovered"]}
    assert found["scans"]["blocked"] == "" and "operator" in found["far"]["blocked"]
    state = client.post(f"{API}/storage/locations", json={"path": str(root / "data/scans")}).json()
    (location,) = state["locations"]
    assert location["kind"] == "managed_hpc_workspace"
    assert (location["workspace"]["name"], location["workspace"]["filesystem"]) == (
        "scans",
        "scratch",
    )
    assert location["workspace"]["extensions"] == 2
    assert 2 * 86400 < location["remaining_seconds"] <= 3 * 86400
    assert [w["name"] for w in state["discovered"]] == ["far"]


def test_the_application_state_folder_is_never_browsable(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, [tmp_path])
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        inside = client.post(f"{API}/fs/list", json={"path": str(tmp_path / "workspace")})
        assert inside.status_code == 403
        added = client.post(f"{API}/storage/locations", json={"path": str(tmp_path / "workspace")})
        assert added.status_code == 422


def test_nothing_is_registrable_without_operator_roots(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path), inline_jobs=True)) as client:
        assert not client.get(f"{API}/storage").json()["registrable"]
        assert (
            client.post(f"{API}/storage/locations", json={"path": str(tmp_path)}).status_code == 422
        )


def dataset_project(client: TestClient, dataset: Path) -> str:
    created = client.post(f"{API}/projects", json={"name": "Study", "dataset_root": str(dataset)})
    assert created.status_code == 201, created.text
    return str(created.json()["project_id"])


def test_a_backup_holds_the_project_state_only_and_respects_the_limits(
    site: tuple[TestClient, Path],
) -> None:
    client, root = site
    dataset = root / "data/scans"
    pid = dataset_project(client, dataset)
    folder = dataset / ".workbench/projects" / pid
    (folder / "volume.nii.gz").write_bytes(b"x" * 4096)
    state = client.get(f"{API}/projects/{pid}/backups").json()
    assert state["blocked"] == "" and state["backups"] == [] and state["estimate_bytes"] > 0
    assert (state["limit_bytes"], state["total_limit_bytes"]) == (1024**2, 1024**2)
    made = client.post(f"{API}/projects/{pid}/backups")
    assert made.status_code == 201, made.text
    archive = root / "workspace/backups" / pid / made.json()["name"]
    names = zipfile.ZipFile(archive).namelist()
    assert f"{pid}/project.json" in names and not any(n.endswith(".nii.gz") for n in names)
    assert [p.name for p in archive.parent.iterdir()] == [archive.name]
    # too large for the limit: refused before writing, and the existing backup is untouched
    (folder / "notes.bin").write_bytes(bytes(range(256)) * 8192)
    blocked = client.get(f"{API}/projects/{pid}/backups").json()
    assert "limit" in blocked["blocked"]
    assert client.post(f"{API}/projects/{pid}/backups").status_code == 422
    assert [p.name for p in archive.parent.iterdir()] == [archive.name]
    download = client.get(f"{API}/projects/{pid}/backups/{archive.name}")
    assert download.status_code == 200 and download.content == archive.read_bytes()
    assert client.get(f"{API}/projects/{pid}/backups/..%2Fx.zip").status_code == 404
    assert client.delete(f"{API}/projects/{pid}/backups/..%2Fx.zip").status_code == 404
    assert client.delete(f"{API}/projects/{pid}/backups/{archive.name}").status_code == 204
    assert not archive.exists()


def test_a_lost_workspace_keeps_the_project_in_the_registry_marked_unavailable(
    site: tuple[TestClient, Path],
) -> None:
    client, root = site
    dataset = root / "data/scans"
    pid = dataset_project(client, dataset)
    kept = root / "kept"
    dataset.rename(kept)
    rows = client.get(f"{API}/projects").json()
    (row,) = [r for r in rows if r["project_id"] == pid]
    assert row["name"] == "Study" and row["storage_available"] is False
    assert "unavailable" in client.get(f"{API}/projects/{pid}/backups").json()["blocked"]
    assert client.post(f"{API}/projects/{pid}/backups").status_code == 422
    kept.rename(dataset)
    (row,) = [r for r in client.get(f"{API}/projects").json() if r["project_id"] == pid]
    assert row["storage_available"] is True
