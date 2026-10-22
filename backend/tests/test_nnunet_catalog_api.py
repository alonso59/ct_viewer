"""SEG-02/07: API settings use a fresh validated runner catalog, never browser paths."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.tasks.registry import parse_manifest
from tests.test_api_ingest import ctx_of
from tests.test_nnunet import PROFILE_ID, REPO

API = "/api/v1"


def advertise(
    client: TestClient,
    *,
    age: int = 0,
    generation: str = "sha256:catalog",
    name: str = "host",
    execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = ctx_of(client)
    manifest = REPO / "plugins/nnunet/task.json"
    if "segment.nnunet" not in ctx.registry.tasks:
        parsed, digest = parse_manifest(manifest)
        ctx.registry.add(parsed, digest, "plugins_root", manifest)
    catalog = {
        "generation": generation,
        "profiles": [
            {
                "id": key,
                "title": key,
                "available": True,
                "profile_sha256": "sha256:profile",
                "artifacts_sha256": "artifacts",
                "channels": {"0": "CT"},
                "labels": {"1": "organ"},
            }
            for key in (PROFILE_ID, "other-ct")
        ]
        + [{"id": "broken", "title": "Broken", "available": False, "reason": "missing artifact"}],
    }
    folder = ctx.settings.workspace_root / "queue/runners"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(
        json.dumps(
            {
                "tasks": ["segment.nnunet"],
                "at": (datetime.now(UTC) - timedelta(seconds=age)).isoformat(),
                "model_catalog": catalog,
                "execution": execution
                or {
                    "backend": "server",
                    "limits": {"cpus": 12, "gpus": 4},
                    "write_network_confinement": True,
                },
            }
        )
    )
    return catalog


def test_available_settings_come_from_valid_catalog_siblings(client: TestClient) -> None:
    catalog = advertise(client)
    info = client.get(f"{API}/tasks/segment.nnunet").json()
    assert info["model_catalog"]["generation"] == catalog["generation"]
    assert [(p["id"], p["available"]) for p in info["model_catalog"]["profiles"]] == [
        (p["id"], p["available"]) for p in catalog["profiles"]
    ]
    assert info["manifest"]["settings_schema"]["properties"]["profile"]["enum"] == [
        PROFILE_ID,
        "other-ct",
    ]
    assert ctx_of(client).registry.get("segment.nnunet").manifest.settings_schema["properties"][
        "profile"
    ]["enum"] == [PROFILE_ID]
    assert (
        client.post(
            f"{API}/tasks/segment.nnunet/validate", json={"settings": {"profile": "other-ct"}}
        ).json()["ok"]
        is True
    )
    assert (
        client.post(
            f"{API}/tasks/segment.nnunet/validate", json={"settings": {"profile": "broken"}}
        ).json()["ok"]
        is False
    )


@pytest.mark.parametrize("age", [60, -600])
def test_stale_or_future_catalog_cannot_admit_a_new_profile(client: TestClient, age: int) -> None:
    advertise(client, age=age)
    info = client.get(f"{API}/tasks/segment.nnunet").json()
    assert info["runner_online"] is False
    assert info["model_catalog"] is None
    assert (
        client.post(
            f"{API}/tasks/segment.nnunet/validate", json={"settings": {"profile": "other-ct"}}
        ).json()["ok"]
        is False
    )


def test_conflicting_runner_catalogs_are_not_silently_combined(client: TestClient) -> None:
    advertise(client, name="one")
    advertise(client, name="two", generation="sha256:different")
    info = client.get(f"{API}/tasks/segment.nnunet").json()
    assert info["available"] is False
    assert "conflict" in info["unavailable_reason"].lower()


def test_gpu_settings_follow_the_runner_pool(client: TestClient) -> None:
    """G1: only the runner's approved devices are offered and accepted; the cap fits the pool."""

    def device(index: str, busy: bool) -> dict[str, Any]:
        used = 3000 if busy else 14
        return {"index": index, "uuid": f"GPU-{index}", "name": "NVIDIA A40",
                "total_mb": 46068, "used_mb": used, "busy": busy}  # fmt: skip

    advertise(
        client,
        execution={
            "backend": "server",
            "limits": {"cpus": 12, "gpus": 2},
            "inventory": {"devices": [device("0", False), device("6", True)]},
        },
    )
    props = client.get(f"{API}/tasks/segment.nnunet").json()["manifest"]["settings_schema"]
    props = props["properties"]
    assert props["gpu_ids"]["items"]["enum"] == ["0", "6"]
    names = props["gpu_ids"]["items"]["x-enumNames"]
    assert "A40" in names[0] and "busy" in names[1].lower()
    assert props["gpu_cap"]["maximum"] == 2 and props["gpu_cap"]["default"] <= 2
    assert props["profile"]["x-enumNames"] == [PROFILE_ID, "other-ct"]

    def ok(settings: dict[str, Any]) -> bool:
        body = {"settings": {"profile": PROFILE_ID, **settings}}
        return bool(client.post(f"{API}/tasks/segment.nnunet/validate", json=body).json()["ok"])

    assert ok({"gpu_ids": ["6"], "gpu_cap": 2})
    assert not ok({"gpu_ids": ["1"]})
    assert not ok({"gpu_cap": 3})
