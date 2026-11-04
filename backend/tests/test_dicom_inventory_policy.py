"""D07/D32/D37, DCM-21: aggregate inventory admission and retention preserve recoverable work."""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_api_ingest import ctx_of
from tests.test_source_operations_api import wait_operation
from tests.test_sources import ct, nii

API = "/api/v1/source-operations"


def start(client: TestClient, source: Path, key: str, **extra: object) -> dict:
    response = client.post(
        API,
        json={
            "path": str(source),
            "purpose": "discover",
            "idempotency_key": key,
            **extra,
        },
    )
    assert response.status_code == 202, response.text
    return wait_operation(client, response.json()["operation_id"])


def test_aggregate_budget_refuses_growth_and_resumes_after_budget_increase(tmp_path: Path) -> None:
    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace",
        allowed_data_roots=str(source),
        dicom_inventory_total_mb=1,
        _env_file=None,
    )  # type: ignore[call-arg]
    root = settings.workspace_root / "plugins/dicom/operations"
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        first = start(client, source, "aggregate-first")
        assert first["status"] == "completed", first
        database = root / first["operation_id"] / "inventory.sqlite"
        digest = hashlib.sha256(database.read_bytes()).hexdigest()
        refused = start(client, source, "aggregate-second")
        assert refused["status"] == "failed", refused
        assert "DICOM_INVENTORY_TOTAL_MB" in refused["error"]
        assert not (root / refused["operation_id"] / "inventory.sqlite").exists()
        assert hashlib.sha256(database.read_bytes()).hexdigest() == digest
    settings = settings.model_copy(update={"dicom_inventory_total_mb": 2})
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        current = client.get(f"{API}/{refused['operation_id']}").json()
        response = client.post(
            f"{API}/{current['operation_id']}/resume",
            json={
                "expected_revision": current["revision"],
                "expected_attempt": current["attempt"],
            },
        )
        assert response.status_code == 202, response.text
        resumed = wait_operation(client, current["operation_id"])
        assert resumed["status"] == "completed", resumed
        assert resumed["operation_id"] == refused["operation_id"]
        assert hashlib.sha256(database.read_bytes()).hexdigest() == digest


def test_retention_protects_open_sessions_import_drafts_and_interrupted_work(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    root = settings.workspace_root / "plugins/dicom/operations"
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        finished = start(client, source, "retention-finished")
        opened = start(client, source, "retention-open", purpose="open")
        draft = start(client, source, "retention-draft", import_context={"alias": "IMAGES"})
        recoverable = start(client, source, "retention-interrupted")
        for record in (finished, opened, draft, recoverable):
            path = root / record["operation_id"] / "operation.json"
            data = json.loads(path.read_text())
            data["updated_at"] = "2000-01-01T00:00:00Z"
            if record is recoverable:
                data["status"] = "interrupted"
            path.write_text(json.dumps(data))
        service = ctx_of(client).source_operations
        assert client.portal is not None
        assert client.portal.call(service.prune_inventories) == 1
        assert not (root / finished["operation_id"] / "inventory.sqlite").exists()
        assert client.get(f"{API}/{finished['operation_id']}/series").status_code == 409
        assert client.get(f"{API}/{finished['operation_id']}").json()["summary"][
            "inventory_expired"
        ]
        for record in (opened, draft, recoverable):
            assert (root / record["operation_id"] / "inventory.sqlite").is_file()
        assert client.portal.call(service.prune_inventories) == 0
        response = client.post(f"{API}/{opened['operation_id']}/open")
        assert response.status_code == 201, response.text
        assert client.delete(f"/api/v1/open/{opened['operation_id']}").status_code == 204
        assert client.portal.call(service.prune_inventories) == 1
        assert (root / draft["operation_id"] / "inventory.sqlite").is_file()
        assert (root / recoverable["operation_id"] / "inventory.sqlite").is_file()


@pytest.mark.parametrize("damage", ["torn_json", "old_version", "future_version", "missing_source"])
def test_corrupt_history_does_not_prevent_startup_or_other_operations(
    tmp_path: Path, damage: str
) -> None:
    source = tmp_path / "source"
    nii(source / "image.nii.gz", ct())
    settings = Settings(
        workspace_root=tmp_path / "workspace", allowed_data_roots=str(source), _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        original = start(client, source, "damaged-history")
    record = (
        settings.workspace_root
        / "plugins/dicom/operations"
        / original["operation_id"]
        / "operation.json"
    )
    saved = json.loads(record.read_text())
    if damage == "torn_json":
        damaged = b'{"version": '
    else:
        if damage == "missing_source":
            del saved["source"]
        else:
            saved["version"] = 0 if damage == "old_version" else 2
        damaged = json.dumps(saved).encode()
    record.write_bytes(damaged)
    with TestClient(create_app(settings, inline_jobs=True)) as client:
        response = client.get(f"{API}/{original['operation_id']}")
        assert response.status_code == 409
        assert "damaged" in response.json()["detail"]
        assert client.get(API).status_code == 200
        fresh = start(client, source, "after-damaged-history")
        assert fresh["status"] == "completed", fresh
        assert record.read_bytes() == damaged


def test_projection_warns_early_when_the_source_would_exceed_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rw_dicom import inventory as source_inventory

    from app.tasks.source_inventory import SourceInventory
    from tools.dicom_fixtures import write_series

    source = tmp_path / "source"
    write_series(source / "series", shape=(3, 3, 40), marker=(1, 1, 39))
    monkeypatch.setattr(source_inventory, "PROJECTION_MIN_READS", 10)
    rows: list[dict] = []
    with SourceInventory(tmp_path / "state" / "inventory.sqlite", source) as inventory:
        inventory.precount()
        inventory._set("precount_files", "1000000")  # a much larger source than the fixture
        summary = inventory.scan(batch_size=8, max_bytes=1024**2, on_progress=rows.append)
    projection = summary["inventory_projection"]
    assert projection["cap_bytes"] == 1024**2 // 4 == summary["inventory_cap_bytes"]
    assert projection["warning"] and projection["projected_bytes"] > projection["cap_bytes"]
    assert any(row.get("inventory_projection", {}).get("warning") for row in rows)
    assert summary["files"] == 40  # the warning never stops the scan


def test_projection_stays_quiet_below_the_threshold_and_before_enough_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rw_dicom import inventory as source_inventory

    from app.tasks.source_inventory import SourceInventory
    from tools.dicom_fixtures import write_series

    source = tmp_path / "source"
    write_series(source / "series", shape=(3, 3, 40), marker=(1, 1, 39))
    with SourceInventory(tmp_path / "early" / "inventory.sqlite", source) as inventory:
        inventory.precount()
        assert inventory.scan(batch_size=8)["inventory_projection"] is None
    monkeypatch.setattr(source_inventory, "PROJECTION_MIN_READS", 10)
    with SourceInventory(tmp_path / "ok" / "inventory.sqlite", source) as inventory:
        inventory.precount()
        projection = inventory.scan(batch_size=8)["inventory_projection"]
    assert projection is not None and not projection["warning"]


def test_limit_message_names_cap_setting_and_need() -> None:
    from app.tasks.source_operations import inventory_limit_message

    mb = 1024**2
    summary = {
        "inventory_cap_bytes": 1536 * mb,
        "inventory_projection": {"projected_bytes": int(3.9 * 1024**3), "cap_bytes": 1536 * mb},
    }
    message = inventory_limit_message(summary)
    assert message.startswith(
        "Inventory reached its 1,536 MB cap (a quarter of DICOM_INVENTORY_MB=6144)."
    )
    assert "about 3.9 GB" in message and "raise DICOM_INVENTORY_MB to 15975" in message
    assert message.endswith("then resume.")
    huge = {**summary, "inventory_projection": {"projected_bytes": 9 * 1024**4}}
    assert "raise" not in inventory_limit_message(huge).split("GB")[1]
    unknown = {"inventory_cap_bytes": 256 * mb}
    assert "(a quarter of DICOM_INVENTORY_MB=1024)" in inventory_limit_message(unknown)
    assert ".md" not in message and "DCM-" not in message
